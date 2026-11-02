/**
 * IR → DOM SVG（零 wasm，见 `docs/notes/viewer.md`）。
 *
 * 坐标口径（`docs/notes/ir.md` §1 / §4）：
 *
 * - 页面 y 向下、原点左上，单位 pt；`viewport.transform` 把子坐标映射到父坐标，
 *   沿树合成出**页面变换**；
 * - `viewport.clip_rect` 是**页面绝对坐标**，不跟 `transform` 走，所以裁剪框
 *   必须放在没有任何 `transform` 的祖先里。这里的做法是把几何烘焙到页面坐标，
 *   容器 `<g>` 一律不带 transform，裁剪 `<g clip-path>` 就能直接用页面矩形；
 *   文字 / 位图这类需要保留局部方向的原语，只在自己的叶子上带一个 transform。
 * - 线宽（`lwd`）/ 虚线（`lty`）在 IR 里是局部单位下的 pt（设备 `concat` 之后画），
 *   烘焙到页面坐标后按变换的平均缩放（√|det|）折算，与 `ggskia` 的
 *   `canvas.concat()` 口径一致。
 */

import { curvePoints, xsplinePoints } from "./curves.js";
import { bufValue, nodeRows, paramNumber, paramString } from "./ir.js";
import type { Color, FloatBuffer, Gpar, IrNode, IrScene } from "./ir.js";
import { IrError } from "./ir.js";

export type Matrix = [number, number, number, number, number, number];

export const IDENTITY: Matrix = [1, 0, 0, 1, 0, 0];

export interface Box {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface RenderedLeaf {
  /** 节点 id：`0/3/2`（根视口是 `0`）。 */
  id: string;
  kind: string;
  /** 最近一层具名视口（`panel-1-1` / `guide-0-key-0`）；没有名字时是 `""`。 */
  viewport: string;
  /** 在节点缓冲里的行号（数据行）；文本节点是 texts 的下标，聚合元素固定为 0。 */
  row: number;
  /** 节点缓冲总行数；一个元素覆盖多行时 tooltip 显示 `1–rows` 的范围。 */
  rows: number;
  text: string;
  element: SVGElement;
  bbox: Box;
}

export interface RenderedViewport {
  id: string;
  name: string;
  group: SVGGElement;
  bbox: Box | null;
}

export interface RenderResult {
  svg: SVGSVGElement;
  leaves: RenderedLeaf[];
  viewports: RenderedViewport[];
  /** 所有节点（含容器），用于计数与调试。 */
  nodeCount: number;
}

const SVG_NS = "http://www.w3.org/2000/svg";
const XLINK_NS = "http://www.w3.org/1999/xlink";
const DEFAULT_FONT_STACK = "sans-serif";
/** grid 的缺省 `lineheight = 1.2`，绘制行距 = 1.2 × 1.2 × size（`docs/notes/ir.md` §7）。 */
const LINE_SPACING = 1.44;

export function compose(parent: Matrix, child: Matrix): Matrix {
  const [a1, b1, c1, d1, e1, f1] = parent;
  const [a2, b2, c2, d2, e2, f2] = child;
  return [
    a1 * a2 + c1 * b2,
    b1 * a2 + d1 * b2,
    a1 * c2 + c1 * d2,
    b1 * c2 + d1 * d2,
    a1 * e2 + c1 * f2 + e1,
    b1 * e2 + d1 * f2 + f1,
  ];
}

export function mapPoint(matrix: Matrix, x: number, y: number): [number, number] {
  const [a, b, c, d, e, f] = matrix;
  return [a * x + c * y + e, b * x + d * y + f];
}

export function matrixScale(matrix: Matrix): number {
  return Math.sqrt(Math.abs(matrix[0] * matrix[3] - matrix[1] * matrix[2]));
}

function isAxisAligned(matrix: Matrix): boolean {
  return Math.abs(matrix[1]) < 1e-9 && Math.abs(matrix[2]) < 1e-9;
}

function isUniform(matrix: Matrix): boolean {
  return isAxisAligned(matrix) && Math.abs(Math.abs(matrix[0]) - Math.abs(matrix[3])) < 1e-9;
}

function num(value: number): string {
  // 固定 3 位小数：够渲染，DOM 也小；不参与任何逐字节比较的口径。
  const rounded = Math.round(value * 1000) / 1000;
  return Object.is(rounded, -0) ? "0" : String(rounded);
}

function el<K extends keyof SVGElementTagNameMap>(
  name: K,
  attrs: Record<string, string | number> = {},
): SVGElementTagNameMap[K] {
  const element = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attrs)) {
    element.setAttribute(key, String(value));
  }
  return element;
}

function colourValue(colour: Color | null): string | null {
  if (colour === null) return null;
  const [r, g, b] = colour;
  return `#${[r, g, b].map((value) => value.toString(16).padStart(2, "0")).join("")}`;
}

function colourOpacity(colour: Color | null, alpha: number): number {
  if (colour === null) return 0;
  return (colour[3] / 255) * alpha;
}

/** 一条 `d` 属性里的子路径：`move` + 若干段。NaN 是缺口（断线），跳过整段。 */
type SubPath = { move: [number, number]; segments: Array<["L" | "C", number[]]> };

function pushSubPath(out: SubPath[], move: [number, number]): SubPath {
  const sub: SubPath = { move, segments: [] };
  out.push(sub);
  return sub;
}

function pathData(subpaths: SubPath[], closed: boolean): string {
  const parts: string[] = [];
  for (const sub of subpaths) {
    if (!Number.isFinite(sub.move[0]) || !Number.isFinite(sub.move[1])) continue;
    if (sub.segments.length === 0) continue;
    parts.push(`M${num(sub.move[0])} ${num(sub.move[1])}`);
    for (const [command, values] of sub.segments) {
      if (values.some((value) => !Number.isFinite(value))) continue;
      parts.push(command + values.map(num).join(" "));
    }
    if (closed) parts.push("Z");
  }
  return parts.join("");
}

/** 按 `id` 分组：值一变化就切一条子路径；NaN 顶点断开当前子路径（`ir.md` §4 / §5）。 */
function groupedPoints(
  node: IrNode,
  name: string,
  matrix: Matrix,
  closed: boolean,
): string {
  const points: FloatBuffer = node.bufs[name];
  const ids = node.bufs["id"] ?? null;
  const subpaths: SubPath[] = [];
  let current: SubPath | null = null;
  let lastId: number | null = null;
  let previousValid = false;
  for (let row = 0; row < points.rows; row++) {
    const x = points.data[row * 2] as number;
    const y = points.data[row * 2 + 1] as number;
    const id = ids ? (ids.data[row] as number) : 0;
    const valid = Number.isFinite(x) && Number.isFinite(y);
    const point = mapPoint(matrix, x, y);
    if (current === null || id !== lastId || !valid || !previousValid) {
      current = pushSubPath(subpaths, point);
    } else {
      current.segments.push(["L", [point[0], point[1]]]);
    }
    lastId = id;
    previousValid = valid;
  }
  return pathData(subpaths, closed);
}

// ---------------------------------------------------------------------------
// 原语 → SVG
// ---------------------------------------------------------------------------

function styleAttributes(gpar: Gpar, scale: number, options: { fill?: boolean; stroke?: boolean } = {}): Record<string, string> {
  const useFill = options.fill ?? true;
  const useStroke = options.stroke ?? true;
  const attrs: Record<string, string> = {};
  const fill = useFill ? colourValue(gpar.fill) : null;
  const col = useStroke ? colourValue(gpar.col) : null;
  attrs["fill"] = fill ?? "none";
  if (fill !== null) attrs["fill-opacity"] = num(colourOpacity(gpar.fill, gpar.alpha));
  attrs["stroke"] = col ?? "none";
  if (col !== null) {
    attrs["stroke-opacity"] = num(colourOpacity(gpar.col, gpar.alpha));
    const width = gpar.lwd * scale;
    attrs["stroke-width"] = num(width);
    attrs["stroke-linecap"] = gpar.lineend;
    attrs["stroke-linejoin"] = gpar.linejoin;
    attrs["stroke-miterlimit"] = num(gpar.linemitre);
    if (gpar.lty.length > 0) {
      attrs["stroke-dasharray"] = gpar.lty.map((segment) => num(segment * scale)).join(" ");
    }
  }
  return attrs;
}

function gparOf(node: IrNode): Gpar {
  if (node.gpar === null) {
    throw new IrError(`${node.kind} 没有 gpar`, node.kind);
  }
  return node.gpar;
}

/**
 * 字形坐标以 `size` 为单位（R 的 `GESymbol()` 口径，见 `ggskia/pch.py`）：符号
 * 半径是 `0.375 × size`，直径只有 size 的 3/4。只用绝对 M / L / C / Z，坐标全部
 * 过矩阵，不用圆弧（`A` 的 rx/ry/flag 不是坐标，套矩阵会写出非法 `d`）。
 */
type GlyphOp = ["M" | "L" | "C" | "Z", number[]];

// R `engine.c::GESymbol()` 的常量（与 `ggskia/pch.py` 同一张表，别改成 0.5）。
const RADIUS = 0.375;
const SMALL = 0.25;
const SQRC = 0.886226925452758;
const DMDC = 1.2533141373155003;
const TRC0 = 1.5551203015562142;
const TRC1 = 1.3467736870885984;
const TRC2 = 0.7775601507781071;
/** `pch = 46`（`'.'`）：R 画 0.01 inch 的实心方块，与 `size` 无关。 */
const DOT_HALF_PT = 0.36;

function circleOps(radius = RADIUS): GlyphOp[] {
  const r = radius;
  const k = 0.5523 * r;
  return [
    ["M", [0, -r]],
    ["C", [k, -r, r, -k, r, 0]],
    ["C", [r, k, k, r, 0, r]],
    ["C", [-k, r, -r, k, -r, 0]],
    ["C", [-r, -k, -k, -r, 0, -r]],
    ["Z", []],
  ];
}

function polygonOps(vertices: Array<[number, number]>): GlyphOp[] {
  return [
    ["M", vertices[0]],
    ...vertices.slice(1).map((point): GlyphOp => ["L", point]),
    ["Z", []],
  ];
}

function lineOps(pairs: Array<[[number, number], [number, number]]>): GlyphOp[] {
  return pairs.flatMap(([start, end]): GlyphOp[] => [
    ["M", start],
    ["L", end],
  ]);
}

/** R 的三角形：TRC0/TRC1/TRC2 把等边三角形摆正（坐标已翻成 y 向下）。 */
function triangleOps(down: boolean): GlyphOp[] {
  const r = TRC0 * RADIUS;
  const yc = TRC2 * RADIUS;
  const xc = TRC1 * RADIUS;
  return down
    ? polygonOps([
        [0, r],
        [xc, -yc],
        [-xc, -yc],
      ])
    : polygonOps([
        [0, -r],
        [xc, yc],
        [-xc, yc],
      ]);
}

const SQUARE_OPS = polygonOps([
  [-RADIUS, -RADIUS],
  [RADIUS, -RADIUS],
  [RADIUS, RADIUS],
  [-RADIUS, RADIUS],
]);
const TRIANGLE_UP_OPS = triangleOps(false);
const TRIANGLE_DOWN_OPS = triangleOps(true);
const DIAMOND_OPS = polygonOps([
  [-RADIUS, 0],
  [0, -RADIUS],
  [RADIUS, 0],
  [0, RADIUS],
]);
/** pch 3：加号，臂长 √2 × RADIUS。 */
const PLUS_OPS = lineOps([
  [
    [-Math.SQRT2 * RADIUS, 0],
    [Math.SQRT2 * RADIUS, 0],
  ],
  [
    [0, -Math.SQRT2 * RADIUS],
    [0, Math.SQRT2 * RADIUS],
  ],
]);
const CROSS_OPS = lineOps([
  [
    [-RADIUS, -RADIUS],
    [RADIUS, RADIUS],
  ],
  [
    [-RADIUS, RADIUS],
    [RADIUS, -RADIUS],
  ],
]);
/** pch 5：菱形，顶点距 √2 × RADIUS（比 pch 18 大一圈）。 */
const BIG_DIAMOND_OPS = polygonOps([
  [-Math.SQRT2 * RADIUS, 0],
  [0, -Math.SQRT2 * RADIUS],
  [Math.SQRT2 * RADIUS, 0],
  [0, Math.SQRT2 * RADIUS],
]);
/** pch 11：上下两个三角（TRC 常量与单三角一致）。 */
function doubleTriangleOps(): GlyphOp[] {
  const r = TRC0 * RADIUS;
  const yc = 0.5 * (TRC2 * RADIUS + r);
  const xc = TRC1 * RADIUS;
  return [
    ...polygonOps([
      [0, r],
      [xc, -yc],
      [-xc, -yc],
    ]),
    ...polygonOps([
      [0, -r],
      [xc, yc],
      [-xc, yc],
    ]),
  ];
}

interface Glyph {
  ops: GlyphOp[];
  /** `col` = 用 gpar.col 填充（grid 的实心 pch），`gpar` = 用 gpar.fill 填充（pch 21..25）。 */
  fill: "none" | "col" | "gpar";
  stroke: boolean;
  /** 坐标已是 pt（`pch = 46`），不再乘 `size`。 */
  fixed?: boolean;
}

/**
 * grid `pch` → 字形（R `GESymbol()` 的几何与上色方式，逐条对照
 * `ggskia/pch.py`）。未知编号按 `pch = 1`（空心圆）处理。
 */
function glyphFor(pch: number): Glyph {
  switch (pch) {
    case 0:
      return { ops: SQUARE_OPS, fill: "none", stroke: true };
    case 1:
      return { ops: circleOps(), fill: "none", stroke: true };
    case 2:
      return { ops: TRIANGLE_UP_OPS, fill: "none", stroke: true };
    case 3:
      return { ops: PLUS_OPS, fill: "none", stroke: true };
    case 4:
      return { ops: CROSS_OPS, fill: "none", stroke: true };
    case 5:
      return { ops: BIG_DIAMOND_OPS, fill: "none", stroke: true };
    case 6:
      return { ops: TRIANGLE_DOWN_OPS, fill: "none", stroke: true };
    case 7:
      return { ops: [...SQUARE_OPS, ...CROSS_OPS], fill: "none", stroke: true };
    case 8:
      return {
        ops: [
          ...CROSS_OPS,
          ...lineOps([
            [
              [-Math.SQRT2 * RADIUS, 0],
              [Math.SQRT2 * RADIUS, 0],
            ],
            [
              [0, -Math.SQRT2 * RADIUS],
              [0, Math.SQRT2 * RADIUS],
            ],
          ]),
        ],
        fill: "none",
        stroke: true,
      };
    case 9:
      return {
        ops: [
          ...lineOps([
            [
              [-Math.SQRT2 * RADIUS, 0],
              [Math.SQRT2 * RADIUS, 0],
            ],
            [
              [0, -Math.SQRT2 * RADIUS],
              [0, Math.SQRT2 * RADIUS],
            ],
          ]),
          ...BIG_DIAMOND_OPS,
        ],
        fill: "none",
        stroke: true,
      };
    case 10:
      return {
        ops: [
          ...circleOps(),
          ...lineOps([
            [
              [-RADIUS, 0],
              [RADIUS, 0],
            ],
            [
              [0, -RADIUS],
              [0, RADIUS],
            ],
          ]),
        ],
        fill: "none",
        stroke: true,
      };
    case 11:
      return { ops: doubleTriangleOps(), fill: "none", stroke: true };
    case 12:
      return {
        ops: [...SQUARE_OPS, ...lineOps([
          [
            [-RADIUS, 0],
            [RADIUS, 0],
          ],
          [
            [0, -RADIUS],
            [0, RADIUS],
          ],
        ])],
        fill: "none",
        stroke: true,
      };
    case 13:
      return { ops: [...circleOps(), ...CROSS_OPS], fill: "none", stroke: true };
    case 14:
      return { ops: [...triangleOps(false), ...SQUARE_OPS], fill: "none", stroke: true };
    case 15:
      return { ops: SQUARE_OPS, fill: "col", stroke: false };
    case 16:
      return { ops: circleOps(), fill: "col", stroke: false };
    case 17:
      return { ops: TRIANGLE_UP_OPS, fill: "col", stroke: false };
    case 18:
      return { ops: DIAMOND_OPS, fill: "col", stroke: false };
    case 19:
      return { ops: circleOps(), fill: "col", stroke: true };
    case 20:
      return { ops: circleOps(SMALL), fill: "col", stroke: true };
    case 21:
      return { ops: circleOps(), fill: "gpar", stroke: true };
    case 22: {
      const d = RADIUS * SQRC;
      return {
        ops: polygonOps([
          [-d, -d],
          [d, -d],
          [d, d],
          [-d, d],
        ]),
        fill: "gpar",
        stroke: true,
      };
    }
    case 23: {
      const d = RADIUS * DMDC;
      return {
        ops: polygonOps([
          [0, -d],
          [d, 0],
          [0, d],
          [-d, 0],
        ]),
        fill: "gpar",
        stroke: true,
      };
    }
    case 24:
      return { ops: TRIANGLE_UP_OPS, fill: "gpar", stroke: true };
    case 25:
      return { ops: TRIANGLE_DOWN_OPS, fill: "gpar", stroke: true };
    case 46:
      return {
        ops: polygonOps([
          [-DOT_HALF_PT, -DOT_HALF_PT],
          [DOT_HALF_PT, -DOT_HALF_PT],
          [DOT_HALF_PT, DOT_HALF_PT],
          [-DOT_HALF_PT, DOT_HALF_PT],
        ]),
        fill: "col",
        stroke: false,
        fixed: true,
      };
    default:
      return { ops: circleOps(), fill: "none", stroke: true };
  }
}

function glyphPath(ops: GlyphOp[], matrix: Matrix): string {
  const parts: string[] = [];
  for (const [command, values] of ops) {
    if (command === "Z") {
      parts.push("Z");
      continue;
    }
    const mapped: string[] = [];
    for (let index = 0; index + 1 < values.length; index += 2) {
      const [x, y] = mapPoint(matrix, values[index], values[index + 1]);
      mapped.push(num(x), num(y));
    }
    parts.push(command + mapped.join(" "));
  }
  return parts.join("");
}

// ---------------------------------------------------------------------------
// 主渲染
// ---------------------------------------------------------------------------

class Renderer {
  private readonly svg: SVGSVGElement;
  private readonly defs: SVGDefsElement;
  private readonly leaves: RenderedLeaf[] = [];
  private readonly viewports: RenderedViewport[] = [];
  private readonly boxes = new Map<SVGGElement, Box>();
  private readonly stack: SVGGElement[] = [];
  private clipCount = 0;
  private nodeCount = 0;

  constructor(private readonly scene: IrScene) {
    this.svg = el("svg", {
      class: "gg-svg",
      viewBox: `0 0 ${num(scene.size[0])} ${num(scene.size[1])}`,
      width: `${num(scene.size[0])}pt`,
      height: `${num(scene.size[1])}pt`,
      "data-size": `${num(scene.size[0])}x${num(scene.size[1])}`,
    });
    this.defs = el("defs");
    // 导出 outerHTML 时要有命名空间声明：`<svg>` 在 DOM 里属于 SVG 命名空间，
    // 但 `outerHTML` 不会自动补默认 xmlns；独立文件（resvg / XML 解析器）需要它。
    this.svg.setAttribute("xmlns", SVG_NS);
    // resvg 同样要求 `xlink` 前缀有声明（raster 的 `<image>` 仍写 `xlink:href`）。
    this.svg.setAttribute("xmlns:xlink", XLINK_NS);
    this.svg.append(this.defs);
  }

  run(): RenderResult {
    this.walk(this.scene.root, "0", this.svg, IDENTITY, "");
    return {
      svg: this.svg,
      leaves: this.leaves,
      viewports: this.viewports,
      nodeCount: this.nodeCount,
    };
  }

  private walk(
    node: IrNode,
    id: string,
    parent: SVGElement,
    matrix: Matrix,
    viewport: string,
  ): void {
    this.nodeCount += 1;
    const kind = node.kind;
    if (kind === "null" || kind === "zero") return;

    if (kind === "gtree") {
      const group = el("g", { class: "ir-node ir-group", "data-node": id, "data-kind": kind });
      parent.append(group);
      this.enter(group);
      node.children.forEach((child, index) =>
        this.walk(child, `${id}/${index}`, group, matrix, viewport),
      );
      this.exit();
      return;
    }

    if (kind === "viewport") {
      const name = paramString(node, "name");
      const group = el("g", {
        class: "ir-node ir-vp",
        "data-node": id,
        "data-kind": kind,
        "data-vp": name,
      });
      if (name) group.setAttribute("data-vp-named", name);
      parent.append(group);
      const record: RenderedViewport = { id, name, group, bbox: null };
      this.viewports.push(record);
      this.enter(group);
      const next = compose(matrix, node.params["transform"] as Matrix);
      const clipped = this.clipWrapper(node, group);
      const container = clipped ?? group;
      node.children.forEach((child, index) =>
        this.walk(child, `${id}/${index}`, container, next, name || viewport),
      );
      this.exit();
      record.bbox = this.boxes.get(group) ?? null;
      return;
    }

    if (kind === "clip") {
      const group = el("g", { class: "ir-node ir-clip", "data-node": id, "data-kind": kind });
      parent.append(group);
      this.enter(group);
      const clipPath = this.clipPathFor(node, matrix);
      const inner = el("g", { "clip-path": `url(#${clipPath})` });
      group.append(inner);
      node.children.forEach((child, index) =>
        this.walk(child, `${id}/${index}`, inner, matrix, viewport),
      );
      this.exit();
      return;
    }

    this.drawLeaf(node, id, parent, matrix, viewport);
  }

  /** 视口裁剪：`clip_rect` 是页面坐标，所以包一层**没有 transform** 的 `<g>`。 */
  private clipWrapper(node: IrNode, group: SVGGElement): SVGGElement | null {
    if (node.params["clip"] !== true) return null;
    const rect = node.bufs["clip_rect"];
    if (!rect) return null;
    // `clip_rect` 是页面绝对坐标（`ir.md` §4），**不**乘任何 transform：
    // 容器 `<g>` 都不带 transform，所以 clipPath 里的页面矩形就是对的。
    const page = normaliseBox(
      rect.data[0] as number,
      rect.data[1] as number,
      rect.data[2] as number,
      rect.data[3] as number,
    );
    const id = this.addClipRect(page);
    const wrapper = el("g", { class: "ir-clip-frame", "clip-path": `url(#${id})` });
    group.append(wrapper);
    return wrapper;
  }

  private clipPathFor(node: IrNode, matrix: Matrix): string {
    const id = `ggv-clip-${this.clipCount++}`;
    const clipPath = el("clipPath", { id });
    if (node.bufs["rect"]) {
      const rect = node.bufs["rect"];
      const points = [
        mapPoint(matrix, rect.data[0] as number, rect.data[1] as number),
        mapPoint(matrix, rect.data[2] as number, rect.data[3] as number),
      ];
      const box = normaliseBox(points[0][0], points[0][1], points[1][0], points[1][1]);
      clipPath.append(
        el("rect", {
          x: num(box.x0),
          y: num(box.y0),
          width: num(box.x1 - box.x0),
          height: num(box.y1 - box.y0),
        }),
      );
    } else {
      const d = groupedPoints(node, "points", matrix, true);
      const path = el("path", { d, "fill-rule": fillRule(node) });
      clipPath.append(path);
    }
    this.defs.append(clipPath);
    return id;
  }

  private addClipRect(box: Box): string {
    const id = `ggv-clip-${this.clipCount++}`;
    const clipPath = el("clipPath", { id });
    clipPath.append(
      el("rect", {
        x: num(box.x0),
        y: num(box.y0),
        width: num(Math.max(0, box.x1 - box.x0)),
        height: num(Math.max(0, box.y1 - box.y0)),
      }),
    );
    this.defs.append(clipPath);
    return id;
  }

  private enter(group: SVGGElement): void {
    this.stack.push(group);
  }

  private exit(): void {
    this.stack.pop();
  }

  private track(box: Box): void {
    if (!Number.isFinite(box.x0) || !Number.isFinite(box.y1)) return;
    for (const group of this.stack) {
      const current = this.boxes.get(group);
      this.boxes.set(
        group,
        current === undefined
          ? { ...box }
          : {
              x0: Math.min(current.x0, box.x0),
              y0: Math.min(current.y0, box.y0),
              x1: Math.max(current.x1, box.x1),
              y1: Math.max(current.y1, box.y1),
            },
      );
    }
  }

  private emit(
    node: IrNode,
    id: string,
    parent: SVGElement,
    viewport: string,
    element: SVGElement,
    row: number,
    rows: number,
    bbox: Box,
    text = "",
  ): void {
    element.setAttribute("data-node", id);
    element.setAttribute("data-kind", node.kind);
    element.setAttribute("data-row", String(row));
    element.setAttribute("data-vp", viewport);
    parent.append(element);
    this.leaves.push({
      id,
      kind: node.kind,
      viewport,
      row,
      rows,
      text,
      element,
      bbox,
    });
    this.track(bbox);
  }

  private drawLeaf(
    node: IrNode,
    id: string,
    parent: SVGElement,
    matrix: Matrix,
    viewport: string,
  ): void {
    const gpar = gparOf(node);
    const scale = matrixScale(matrix);
    const kind = node.kind;
    const rows = nodeRows(node);
    switch (kind) {
      case "rect": {
        for (let row = 0; row < rows; row++) {
          const x0 = bufValue(node, "rect", row, 0);
          const y0 = bufValue(node, "rect", row, 1);
          const x1 = bufValue(node, "rect", row, 2);
          const y1 = bufValue(node, "rect", row, 3);
          if (![x0, y0, x1, y1].every(Number.isFinite)) continue;
          const a = mapPoint(matrix, x0, y0);
          const b = mapPoint(matrix, x1, y1);
          const box = normaliseBox(a[0], a[1], b[0], b[1]);
          const attrs = styleAttributes(gpar, scale);
          if (isAxisAligned(matrix)) {
            // 轴对齐 → 真的 <rect>：DOM 小，也方便测试按元素数对账。
            this.emit(
              node,
              id,
              parent,
              viewport,
              el("rect", {
                x: num(box.x0),
                y: num(box.y0),
                width: num(box.x1 - box.x0),
                height: num(box.y1 - box.y0),
                ...attrs,
              }),
              row,
              rows,
              box,
            );
          } else {
            const corners = [
              mapPoint(matrix, x0, y0),
              mapPoint(matrix, x1, y0),
              mapPoint(matrix, x1, y1),
              mapPoint(matrix, x0, y1),
            ];
            const d = `M${corners.map(([x, y]) => `${num(x)} ${num(y)}`).join("L")}Z`;
            this.emit(
              node,
              id,
              parent,
              viewport,
              el("path", { d, ...attrs }),
              row,
              rows,
              box,
            );
          }
        }
        return;
      }
      case "circle": {
        for (let row = 0; row < rows; row++) {
          const cx = bufValue(node, "circle", row, 0);
          const cy = bufValue(node, "circle", row, 1);
          const radius = bufValue(node, "circle", row, 2);
          const [px, py] = mapPoint(matrix, cx, cy);
          const rx = Math.abs(radius * scale);
          const box = { x0: px - rx, y0: py - rx, x1: px + rx, y1: py + rx };
          const attrs = styleAttributes(gpar, scale);
          if (isUniform(matrix)) {
            this.emit(
              node,
              id,
              parent,
              viewport,
              el("circle", { cx: num(px), cy: num(py), r: num(Math.abs(radius * matrix[0])), ...attrs }),
              row,
              rows,
              box,
            );
          } else {
            const unit = glyphPath(
              circleOps(),
              compose(matrix, [radius * 2, 0, 0, radius * 2, cx, cy]),
            );
            this.emit(node, id, parent, viewport, el("path", { d: unit, ...attrs }), row, rows, box);
          }
        }
        return;
      }
      case "segments": {
        const subpaths: SubPath[] = [];
        for (let row = 0; row < rows; row++) {
          const a = mapPoint(matrix, bufValue(node, "segments", row, 0), bufValue(node, "segments", row, 1));
          const b = mapPoint(matrix, bufValue(node, "segments", row, 2), bufValue(node, "segments", row, 3));
          const sub = pushSubPath(subpaths, a);
          sub.segments.push(["L", [b[0], b[1]]]);
        }
        const d = pathData(subpaths, false);
        const box = boxOfPathData(d);
        this.emit(
          node,
          id,
          parent,
          viewport,
          el("path", { d, ...styleAttributes(gpar, scale, { fill: false }) }),
          0,
          rows,
          box,
        );
        return;
      }
      case "lines":
      case "polyline":
      case "polygon":
      case "path": {
        const closed = kind === "polygon" || kind === "path";
        const d = groupedPoints(node, "points", matrix, closed);
        const attrs = styleAttributes(gpar, scale, { fill: closed });
        if (kind === "path") attrs["fill-rule"] = fillRule(node);
        if (kind === "lines") attrs["fill"] = "none";
        this.emit(
          node,
          id,
          parent,
          viewport,
          el("path", { d, ...attrs }),
          0,
          rows,
          boxOfPathData(d),
        );
        return;
      }
      case "xspline": {
        // R `xspline.c` 的采样（与桌面设备的 `ggskia.curves` 同一份公式）。
        const shape = node.params["shape"] as number;
        const open = node.params["open"] as boolean;
        const points = node.bufs["points"];
        const ids = node.bufs["id"] ?? null;
        const page: [number, number] = [this.scene.size[0], this.scene.size[1]];
        const subpaths: SubPath[] = [];
        let start = 0;
        for (let row = 1; row <= points.rows; row++) {
          const changed = row === points.rows || (ids !== null && ids.data[row] !== ids.data[start]);
          if (!changed) continue;
          const control: Array<[number, number]> = [];
          for (let index = start; index < row; index++) {
            control.push([points.data[index * 2] as number, points.data[index * 2 + 1] as number]);
          }
          if (control.length >= (open ? 2 : 3)) {
            const sampled = xsplinePoints(control, shape, { open, page }).map(([x, y]) =>
              mapPoint(matrix, x, y),
            );
            const sub = pushSubPath(subpaths, sampled[0]);
            for (const point of sampled.slice(1)) {
              sub.segments.push(["L", [point[0], point[1]]]);
            }
          }
          start = row;
        }
        const d = pathData(subpaths, !open);
        this.emit(
          node,
          id,
          parent,
          viewport,
          el("path", { d, ...styleAttributes(gpar, scale, { fill: !open }) }),
          0,
          rows,
          boxOfPathData(d),
        );
        return;
      }
      case "bezier": {
        const control = node.bufs["control"];
        const subpaths: SubPath[] = [];
        for (let row = 0; row + 3 < control.rows; row += 4) {
          const points = [0, 1, 2, 3].map((offset) =>
            mapPoint(
              matrix,
              control.data[(row + offset) * 2] as number,
              control.data[(row + offset) * 2 + 1] as number,
            ),
          );
          const sub = pushSubPath(subpaths, points[0]);
          sub.segments.push(["C", [...points[1], ...points[2], ...points[3]]]);
        }
        const d = pathData(subpaths, false);
        this.emit(
          node,
          id,
          parent,
          viewport,
          el("path", { d, ...styleAttributes(gpar, scale, { fill: false }) }),
          0,
          rows,
          boxOfPathData(d),
        );
        return;
      }
      case "curve": {
        // `curve_points()` 的 `angle` 定义在 R 的 y 向上坐标系里：先翻成 R 坐标
        // 求值，再把折线翻回页面坐标（`ggskia/skia.py::_draw_curve` 同一口径）。
        const ends = node.bufs["ends"];
        const open = node.params["open"] as boolean;
        const height = this.scene.size[1];
        const page: [number, number] = [this.scene.size[0], this.scene.size[1]];
        const subpaths: SubPath[] = [];
        for (let row = 0; row < ends.rows; row++) {
          const x1 = ends.data[row * 4] as number;
          const y1 = ends.data[row * 4 + 1] as number;
          const x2 = ends.data[row * 4 + 2] as number;
          const y2 = ends.data[row * 4 + 3] as number;
          if (![x1, y1, x2, y2].every(Number.isFinite)) continue;
          const sampled = curvePoints(x1, height - y1, x2, height - y2, {
            curvature: node.params["curvature"] as number,
            angle: node.params["angle"] as number,
            ncp: node.params["ncp"] as number,
            shape: node.params["shape"] as number,
            square: node.params["square"] as boolean,
            inflect: node.params["inflect"] as boolean,
            open,
            page,
          }).map(([x, y]) => mapPoint(matrix, x, height - y));
          if (sampled.length < 2) continue;
          const sub = pushSubPath(subpaths, sampled[0]);
          for (const point of sampled.slice(1)) {
            sub.segments.push(["L", [point[0], point[1]]]);
          }
        }
        const d = pathData(subpaths, !open);
        this.emit(
          node,
          id,
          parent,
          viewport,
          el("path", { d, ...styleAttributes(gpar, scale, { fill: !open }) }),
          0,
          rows,
          boxOfPathData(d),
        );
        return;
      }
      case "points": {
        const pch = node.params["pch"] as number;
        const size = node.params["size"] as number;
        const glyph = glyphFor(pch);
        const attrs = styleAttributes(gpar, scale, {
          fill: glyph.fill === "gpar",
          stroke: glyph.stroke,
        });
        if (glyph.fill === "col") {
          // grid 的实心 pch 用 `col` 填充（`ggskia` 的 `use_col=True` 同一口径）。
          const col = colourValue(gpar.col);
          attrs["fill"] = col ?? "none";
          if (col !== null) attrs["fill-opacity"] = num(colourOpacity(gpar.col, gpar.alpha));
        }
        // 半透明的点必须**一行一个元素**：SVG 对一个 `<path>` 只做一次合成，
        // 两个重叠点半透明时整节点合成一次只算一层，比桌面（逐点绘制）更浅。
        // 不透明的点仍按 IR 的 bulk 口径合成单个 `<path>`（10k 行 = 1 个 DOM 元素）。
        const transparent =
          gpar.alpha < 1 ||
          (gpar.col !== null && gpar.col[3] < 255) ||
          (gpar.fill !== null && gpar.fill[3] < 255);
        // `pch = 46` 的字形坐标是绝对 pt（不吃 size），其余以 size 为单位。
        const unit = glyph.fixed === true ? 1 : size;
        const extent = glyph.fixed === true ? DOT_HALF_PT * 2 : size;
        const half = Math.abs((extent * scale) / 2);
        let d = "";
        let box: Box | null = null;
        for (let row = 0; row < rows; row++) {
          const x = bufValue(node, "points", row, 0);
          const y = bufValue(node, "points", row, 1);
          if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
          const glyphMatrix = compose(matrix, [unit, 0, 0, unit, x, y]);
          const glyphD = glyphPath(glyph.ops, glyphMatrix);
          const [px, py] = mapPoint(matrix, x, y);
          const rowBox = { x0: px - half, y0: py - half, x1: px + half, y1: py + half };
          box =
            box === null
              ? rowBox
              : {
                  x0: Math.min(box.x0, rowBox.x0),
                  y0: Math.min(box.y0, rowBox.y0),
                  x1: Math.max(box.x1, rowBox.x1),
                  y1: Math.max(box.y1, rowBox.y1),
                };
          if (transparent) {
            this.emit(node, id, parent, viewport, el("path", { d: glyphD, ...attrs }), row, rows, rowBox);
          } else {
            d += glyphD;
          }
        }
        if (box === null) return;
        if (transparent) return;
        const element = el("path", { d, ...attrs });
        element.setAttribute("data-rows", rows > 0 ? `0-${rows - 1}` : "0");
        this.emit(node, id, parent, viewport, element, 0, rows, box);
        return;
      }
      case "text": {
        this.drawText(node, id, parent, matrix, viewport);
        return;
      }
      case "raster": {
        this.drawRaster(node, id, parent, matrix, viewport);
        return;
      }
      default:
        throw new IrError(`没有 ${kind} 的画法`, id);
    }
  }

  private drawText(
    node: IrNode,
    id: string,
    parent: SVGElement,
    matrix: Matrix,
    viewport: string,
  ): void {
    const gpar = gparOf(node);
    const font = paramString(node, "font");
    const size = paramNumber(node, "size");
    const anchor = paramString(node, "anchor");
    const baseline = paramString(node, "baseline");
    const angle = paramNumber(node, "angle");
    const rows = nodeRows(node);
    const fill = colourValue(gpar.col);
    for (let row = 0; row < rows; row++) {
      const x = bufValue(node, "pos", row, 0);
      const y = bufValue(node, "pos", row, 1);
      const width = bufValue(node, "width", row, 0);
      const lines = node.texts[row].split("\n");
      // 页面变换 ∘ 平移到锚点 ∘ 绕锚点转 `angle`（度，逆时针 → SVG 顺时针取负）。
      const anchorMatrix = compose(matrix, [1, 0, 0, 1, x, y]);
      const element = el("text", {
        x: 0,
        y: 0,
        transform: `matrix(${matrix.map(num).join(" ")}) translate(${num(x)} ${num(y)}) rotate(${num(-angle)})`,
        "font-family": fontStack(font),
        "font-size": num(size),
        "text-anchor": anchor === "left" ? "start" : anchor === "right" ? "end" : "middle",
        "dominant-baseline": baselineAttribute(baseline),
        fill: fill ?? "none",
        "fill-opacity": num(colourOpacity(gpar.col, gpar.alpha)),
      });
      if (lines.length === 1) {
        element.textContent = lines[0];
      } else {
        // 多行：grid 缺省 lineheight = 1.2（绘制行距 1.44 × size，ir.md §7）。
        const dy = size * LINE_SPACING;
        const offset = baseline === "top" ? 0 : baseline === "bottom" ? -(lines.length - 1) * dy : (-(lines.length - 1) * dy) / 2;
        lines.forEach((line, index) => {
          const tspan = el("tspan", { x: 0, y: num(offset + index * dy) });
          tspan.textContent = line;
          element.append(tspan);
        });
      }
      // 文本的包围盒按 IR 给的最终宽度估：宽度是跨端对账的字段（ir.md §7）。
      const left = anchor === "right" ? -width : anchor === "center" ? -width / 2 : 0;
      const top = baseline === "top" ? 0 : baseline === "bottom" ? -size : -size / 2;
      const corners = [
        mapPoint(anchorMatrix, left, top),
        mapPoint(anchorMatrix, left + width, top + size * lines.length),
      ];
      const box = normaliseBox(corners[0][0], corners[0][1], corners[1][0], corners[1][1]);
      this.emit(node, id, parent, viewport, element, row, rows, box, node.texts[row]);
    }
  }

  private drawRaster(
    node: IrNode,
    id: string,
    parent: SVGElement,
    matrix: Matrix,
    viewport: string,
  ): void {
    const blobId = paramString(node, "blob");
    const blob = this.scene.blobs[blobId];
    if (!blob) {
      throw new IrError(`raster 引用了不存在的 blob ${blobId}`, id);
    }
    const interpolate = node.params["interpolate"] !== false;
    const data = toBase64(blob.data);
    const rect = node.bufs["rect"];
    for (let row = 0; row < rect.rows; row++) {
      const x0 = Math.min(rect.data[row * 4] as number, rect.data[row * 4 + 2] as number);
      const y0 = Math.min(rect.data[row * 4 + 1] as number, rect.data[row * 4 + 3] as number);
      const x1 = Math.max(rect.data[row * 4] as number, rect.data[row * 4 + 2] as number);
      const y1 = Math.max(rect.data[row * 4 + 1] as number, rect.data[row * 4 + 3] as number);
      const element = el("image", {
        x: num(x0),
        y: num(y0),
        width: num(x1 - x0),
        height: num(y1 - y0),
        preserveAspectRatio: "none",
        transform: `matrix(${matrix.map(num).join(" ")})`,
        "image-rendering": interpolate ? "auto" : "pixelated",
      });
      element.setAttribute("href", `data:${blob.mime};base64,${data}`);
      element.setAttributeNS(XLINK_NS, "xlink:href", `data:${blob.mime};base64,${data}`);
      const corners = [mapPoint(matrix, x0, y0), mapPoint(matrix, x1, y1)];
      const box = normaliseBox(corners[0][0], corners[0][1], corners[1][0], corners[1][1]);
      this.emit(node, id, parent, viewport, element, row, rect.rows, box);
    }
  }
}

function fillRule(node: IrNode): string {
  return node.params["rule"] === "evenodd" ? "evenodd" : "nonzero";
}

function normaliseBox(x0: number, y0: number, x1: number, y1: number): Box {
  return {
    x0: Math.min(x0, x1),
    y0: Math.min(y0, y1),
    x1: Math.max(x0, x1),
    y1: Math.max(y0, y1),
  };
}

function boxOfPathData(d: string): Box {
  const numbers = d.match(/-?\d*\.?\d+(?:e[-+]?\d+)?/gi) ?? [];
  let box: Box = { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity };
  for (let index = 0; index + 1 < numbers.length; index += 2) {
    const x = Number(numbers[index]);
    const y = Number(numbers[index + 1]);
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    box = {
      x0: Math.min(box.x0, x),
      y0: Math.min(box.y0, y),
      x1: Math.max(box.x1, x),
      y1: Math.max(box.y1, y),
    };
  }
  return box;
}

function baselineAttribute(baseline: string): string {
  switch (baseline) {
    case "top":
      return "text-before-edge";
    case "bottom":
      return "text-after-edge";
    case "alphabetic":
      return "alphabetic";
    default:
      return "central";
  }
}

/** IR 的 `font` 是已解析的单个字族 key，不是回退栈（ir.md §7）；浏览器端补系统栈。 */
function fontStack(font: string): string {
  if (!font) return DEFAULT_FONT_STACK;
  const family = font.includes(" ") ? `"${font}"` : font;
  return `${family}, "Noto Sans CJK SC", "DejaVu Sans", sans-serif`;
}

function toBase64(data: Uint8Array): string {
  let binary = "";
  const chunk = 0x8000;
  for (let offset = 0; offset < data.length; offset += chunk) {
    binary += String.fromCharCode(...data.subarray(offset, offset + chunk));
  }
  return btoa(binary);
}

/** 渲染一张 IR 场景，返回 `<svg>` 与可交互的叶子/视口索引。 */
export function renderScene(scene: IrScene): RenderResult {
  return new Renderer(scene).run();
}

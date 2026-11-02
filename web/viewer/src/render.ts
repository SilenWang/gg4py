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
 * 单位空间（半径 0.5）的字形。只用绝对 M / L / C / Z，坐标全部过矩阵，
 * 不用圆弧（`A` 的 rx/ry/flag 不是坐标，套矩阵会写出非法 `d`）。
 */
type GlyphOp = ["M" | "L" | "C" | "Z", number[]];

function circleOps(radius = 0.5): GlyphOp[] {
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

const SQUARE_OPS: GlyphOp[] = [
  ["M", [-0.5, -0.5]],
  ["L", [0.5, -0.5]],
  ["L", [0.5, 0.5]],
  ["L", [-0.5, 0.5]],
  ["Z", []],
];
const TRIANGLE_UP_OPS: GlyphOp[] = [
  ["M", [0, -0.5]],
  ["L", [0.5, 0.433]],
  ["L", [-0.5, 0.433]],
  ["Z", []],
];
const TRIANGLE_DOWN_OPS: GlyphOp[] = [
  ["M", [0, 0.5]],
  ["L", [0.5, -0.433]],
  ["L", [-0.5, -0.433]],
  ["Z", []],
];
const DIAMOND_OPS: GlyphOp[] = [
  ["M", [0, -0.5]],
  ["L", [0.5, 0]],
  ["L", [0, 0.5]],
  ["L", [-0.5, 0]],
  ["Z", []],
];
const PLUS_OPS: GlyphOp[] = [
  ["M", [0, -0.5]],
  ["L", [0, 0.5]],
  ["M", [-0.5, 0]],
  ["L", [0.5, 0]],
];
const CROSS_OPS: GlyphOp[] = [
  ["M", [-0.354, -0.354]],
  ["L", [0.354, 0.354]],
  ["M", [0.354, -0.354]],
  ["L", [-0.354, 0.354]],
];
const STAR_VERTS: Array<[number, number]> = [
  [0, -0.5],
  [0.118, -0.162],
  [0.476, -0.155],
  [0.19, 0.062],
  [0.294, 0.405],
  [0, 0.2],
  [-0.294, 0.405],
  [-0.19, 0.062],
  [-0.476, -0.155],
  [-0.118, -0.162],
];
const STAR_OPS: GlyphOp[] = [
  ["M", STAR_VERTS[0]],
  ...STAR_VERTS.slice(1).map((point): GlyphOp => ["L", point]),
  ["Z", []],
];

interface Glyph {
  ops: GlyphOp[];
  /** `col` = 用 gpar.col 填充（grid 的实心 pch），`gpar` = 用 gpar.fill 填充（pch 21..25）。 */
  fill: "none" | "col" | "gpar";
  stroke: boolean;
}

/**
 * grid `pch` → 单位空间字形。9..14 是“复合”字形（圈里加号等），这里落到最接近的
 * 简单形状；未知编号按 `pch = 1`（空心圆）处理。差异记在 `docs/notes/viewer.md`。
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
    case 9:
    case 12:
      return { ops: PLUS_OPS, fill: "none", stroke: true };
    case 4:
    case 13:
      return { ops: CROSS_OPS, fill: "none", stroke: true };
    case 5:
      return { ops: DIAMOND_OPS, fill: "none", stroke: true };
    case 6:
      return { ops: TRIANGLE_DOWN_OPS, fill: "none", stroke: true };
    case 7:
    case 14:
      return { ops: [...SQUARE_OPS, ...PLUS_OPS], fill: "none", stroke: true };
    case 8:
      return { ops: STAR_OPS, fill: "none", stroke: true };
    case 10:
      return { ops: [...circleOps(), ...PLUS_OPS], fill: "none", stroke: true };
    case 11:
      return { ops: [...TRIANGLE_UP_OPS, ...TRIANGLE_DOWN_OPS], fill: "none", stroke: true };
    case 15:
      return { ops: SQUARE_OPS, fill: "col", stroke: false };
    case 16:
    case 19:
    case 20:
      return { ops: pch === 20 ? circleOps(0.2) : circleOps(), fill: "col", stroke: false };
    case 17:
    case 24:
      return {
        ops: TRIANGLE_UP_OPS,
        fill: pch === 17 ? "col" : "gpar",
        stroke: pch !== 17,
      };
    case 18:
    case 23:
      return { ops: DIAMOND_OPS, fill: pch === 18 ? "col" : "gpar", stroke: pch !== 18 };
    case 21:
      return { ops: circleOps(), fill: "gpar", stroke: true };
    case 22:
      return { ops: SQUARE_OPS, fill: "gpar", stroke: true };
    case 25:
      return { ops: TRIANGLE_DOWN_OPS, fill: "gpar", stroke: true };
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
        const d = xsplinePath(node, matrix, node.params["shape"] as number, node.params["open"] as boolean);
        this.emit(
          node,
          id,
          parent,
          viewport,
          el("path", {
            d,
            ...styleAttributes(gpar, scale, { fill: node.params["open"] !== true }),
          }),
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
        const ends = node.bufs["ends"];
        const curvature = node.params["curvature"] as number;
        const inflect = node.params["inflect"] as boolean;
        const subpaths: SubPath[] = [];
        for (let row = 0; row < ends.rows; row++) {
          const p1 = mapPoint(matrix, ends.data[row * 4] as number, ends.data[row * 4 + 1] as number);
          const p2 = mapPoint(matrix, ends.data[row * 4 + 2] as number, ends.data[row * 4 + 3] as number);
          const dx = p2[0] - p1[0];
          const dy = p2[1] - p1[1];
          const length = Math.hypot(dx, dy) || 1;
          // 弦的法向（页面 y 向下）：grid.curve 的精确公式未实现，见 viewer.md 差异表。
          const nx = -dy / length;
          const ny = dx / length;
          const bulge = (curvature * length) / 2;
          const sign = inflect ? -1 : 1;
          const sub = pushSubPath(subpaths, p1);
          sub.segments.push([
            "C",
            [
              p1[0] + nx * bulge,
              p1[1] + ny * bulge,
              p2[0] + nx * bulge * sign,
              p2[1] + ny * bulge * sign,
              p2[0],
              p2[1],
            ],
          ]);
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
        // 一个 points 节点只出一个 `<path>`：每行一条 `M…Z` 子路径拼进同一个 `d`。
        // 这是 IR 的 bulk 口径（`docs/notes/ir.md`），10k 行也只占 1 个 DOM 元素；
        // hover 因此到节点粒度，行范围写在 `data-rows`（逐行命中见 viewer.md §9）。
        let d = "";
        let box: Box | null = null;
        for (let row = 0; row < rows; row++) {
          const x = bufValue(node, "points", row, 0);
          const y = bufValue(node, "points", row, 1);
          if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
          const glyphMatrix = compose(matrix, [size, 0, 0, size, x, y]);
          d += glyphPath(glyph.ops, glyphMatrix);
          const [px, py] = mapPoint(matrix, x, y);
          const half = Math.abs((size * scale) / 2);
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
        }
        if (box === null) return;
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

/** xspline：shape=0 等价于 Catmull-Rom（转成三次贝塞尔）；|shape|>0 向直线收拢。 */
function xsplinePath(node: IrNode, matrix: Matrix, shape: number, open: boolean): string {
  const points = node.bufs["points"];
  const ids = node.bufs["id"] ?? null;
  const tension = Math.max(0, 1 - Math.abs(shape));
  const subpaths: SubPath[] = [];
  let start = 0;
  for (let row = 1; row <= points.rows; row++) {
    const changed = row === points.rows || (ids !== null && ids.data[row] !== ids.data[start]);
    if (!changed) continue;
    const slice: Array<[number, number]> = [];
    for (let index = start; index < row; index++) {
      slice.push(
        mapPoint(matrix, points.data[index * 2] as number, points.data[index * 2 + 1] as number),
      );
    }
    if (slice.length >= 2) {
      const sub = pushSubPath(subpaths, slice[0]);
      const at = (index: number): [number, number] =>
        slice[Math.max(0, Math.min(slice.length - 1, index))];
      for (let index = 0; index + 1 < slice.length; index++) {
        const p0 = at(index - 1);
        const p1 = at(index);
        const p2 = at(index + 1);
        const p3 = at(index + 2);
        const c1: [number, number] = [
          p1[0] + ((p2[0] - p0[0]) / 6) * tension,
          p1[1] + ((p2[1] - p0[1]) / 6) * tension,
        ];
        const c2: [number, number] = [
          p2[0] - ((p3[0] - p1[0]) / 6) * tension,
          p2[1] - ((p3[1] - p1[1]) / 6) * tension,
        ];
        sub.segments.push(["C", [...c1, ...c2, ...p2]]);
      }
    }
    start = row;
  }
  return pathData(subpaths, !open);
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

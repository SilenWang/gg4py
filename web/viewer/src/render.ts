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
import { curvePoints, xsplinePoints } from "./curves.js";
import type { Point } from "./curves.js";
import { DEFAULT_FAMILY, FALLBACK_FAMILIES } from "./fonts.generated.js";

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
/** grid 的缺省 `lineheight = 1.2`，绘制行距 = 1.2 × 1.2 × size（`docs/notes/ir.md` §7）。 */
const LINE_SPACING = 1.44;
/**
 * `lty` 段长的折算（`docs/notes/scales.md` 的「lty 串的段长折算」）：
 * IR 里的段长是 `lwd` 的倍数 × **pt 口径**的 lwd（`lwd = 1/96 in × 0.75`），
 * 而 svglite 写 `stroke-dasharray` 时只把线宽折成 pt、段长仍按 1/96 in 的
 * 数值写，所以参考图里的段长比「物理 pt」大 4/3。两渲染器都按参考口径写，
 * 与 `ggskia` 的 `_paint` 同一份常量（M2-12）。
 */
const DASH_UNIT = 4 / 3;

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

/** 绕原点的旋转矩阵。`degrees` 按 SVG 的 y 向下坐标系（顺时针为正）。 */
export function rotateMatrix(degrees: number): Matrix {
  const radians = (degrees * Math.PI) / 180;
  const cos = Math.cos(radians);
  const sin = Math.sin(radians);
  return [cos, sin, -sin, cos, 0, 0];
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
      attrs["stroke-dasharray"] = gpar.lty
        .map((segment) => num(segment * scale * DASH_UNIT))
        .join(" ");
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

// R 的 `engine.c` 常量（与 `src/ggskia/pch.py` 同一份，别改成 0.5）：
// 符号半径是 `RADIUS × size`，不是 size/2——旧实现把直径画成了 size，大了 1/3。
const PCH_RADIUS = 0.375;
const PCH_SQRC = 0.886226925452758;
const PCH_DMDC = 1.2533141373155003;
const PCH_TRC0 = 1.5551203015562142;
const PCH_TRC1 = 1.3467736870885984;
const PCH_TRC2 = 0.7775601507781071;

function squareOps(half = PCH_RADIUS): GlyphOp[] {
  return [
    ["M", [-half, -half]],
    ["L", [half, -half]],
    ["L", [half, half]],
    ["L", [-half, half]],
    ["Z", []],
  ];
}

function triangleOps(down: boolean): GlyphOp[] {
  const radius = PCH_RADIUS;
  const r = PCH_TRC0 * radius;
  // pch 2 / 6 / 17 / 24 / 25：R `engine.c` case 2/6 的普通三角形，底边在
  // `TRC2 * radius`。`0.5 * (TRC2 + TRC0)` 是 pch 11 专用的贴合位置，别混用。
  const yc = PCH_TRC2 * radius;
  const xc = PCH_TRC1 * radius;
  return down
    ? [
        ["M", [0, r]],
        ["L", [xc, -yc]],
        ["L", [-xc, -yc]],
        ["Z", []],
      ]
    : [
        ["M", [0, -r]],
        ["L", [xc, yc]],
        ["L", [-xc, yc]],
        ["Z", []],
      ];
}

/** pch 11 的上下双三角：两个三角形在 `0.5 * (TRC2 + TRC0) * radius` 处贴合。 */
function blendedTriangleOps(down: boolean): GlyphOp[] {
  const radius = PCH_RADIUS;
  const r = PCH_TRC0 * radius;
  const yc = 0.5 * (PCH_TRC2 * radius + r);
  const xc = PCH_TRC1 * radius;
  return down
    ? [
        ["M", [0, r]],
        ["L", [xc, -yc]],
        ["L", [-xc, -yc]],
        ["Z", []],
      ]
    : [
        ["M", [0, -r]],
        ["L", [xc, yc]],
        ["L", [-xc, yc]],
        ["Z", []],
      ];
}

/** pch 14 的三角形：普通 ±`RADIUS`，不是 `TRC` 三角形（R `engine.c` case 14）。 */
function halfTriangleOps(): GlyphOp[] {
  const half = PCH_RADIUS;
  return [
    ["M", [0, -half]],
    ["L", [half, half]],
    ["L", [-half, half]],
    ["Z", []],
  ];
}

function diamondOps(d = Math.SQRT2 * PCH_RADIUS): GlyphOp[] {
  return [
    ["M", [0, -d]],
    ["L", [d, 0]],
    ["L", [0, d]],
    ["L", [-d, 0]],
    ["Z", []],
  ];
}

function plusOps(cross = Math.SQRT2 * PCH_RADIUS): GlyphOp[] {
  return [
    ["M", [0, -cross]],
    ["L", [0, cross]],
    ["M", [-cross, 0]],
    ["L", [cross, 0]],
  ];
}

function crossOps(half = PCH_RADIUS): GlyphOp[] {
  return [
    ["M", [-half, -half]],
    ["L", [half, half]],
    ["M", [half, -half]],
    ["L", [-half, half]],
  ];
}

interface Glyph {
  ops: GlyphOp[];
  /** `col` = 用 gpar.col 填充（grid 的实心 pch），`gpar` = 用 gpar.fill 填充（pch 21..25）。 */
  fill: "none" | "col" | "gpar";
  stroke: boolean;
}

/**
 * grid `pch` → `size` 单位的字形（坐标直接乘 `size`，不再走半径 0.5 的单位空间）。
 * 几何与 `ggskia.pch.symbol()` 对齐；字符型 pch 由 IR 写方决定，查看器只认 0..25。
 */
function glyphFor(pch: number): Glyph {
  switch (pch) {
    case 0:
      return { ops: squareOps(), fill: "none", stroke: true };
    case 1:
      return { ops: circleOps(PCH_RADIUS), fill: "none", stroke: true };
    case 2:
      return { ops: triangleOps(false), fill: "none", stroke: true };
    case 3:
      return { ops: plusOps(), fill: "none", stroke: true };
    case 4:
      return { ops: crossOps(), fill: "none", stroke: true };
    case 5:
      return { ops: diamondOps(), fill: "none", stroke: true };
    case 6:
      return { ops: triangleOps(true), fill: "none", stroke: true };
    case 7:
      return { ops: [...squareOps(), ...crossOps()], fill: "none", stroke: true };
    case 8:
      return { ops: [...crossOps(), ...plusOps()], fill: "none", stroke: true };
    case 9:
      return { ops: [...diamondOps(), ...plusOps()], fill: "none", stroke: true };
    case 10:
      return { ops: [...circleOps(PCH_RADIUS), ...plusOps(PCH_RADIUS)], fill: "none", stroke: true };
    case 11:
      return {
        ops: [...blendedTriangleOps(false), ...blendedTriangleOps(true)],
        fill: "none",
        stroke: true,
      };
    case 12:
      return { ops: [...squareOps(), ...plusOps(PCH_RADIUS)], fill: "none", stroke: true };
    case 13:
      return { ops: [...circleOps(PCH_RADIUS), ...crossOps()], fill: "none", stroke: true };
    case 14:
      return { ops: [...halfTriangleOps(), ...squareOps()], fill: "none", stroke: true };
    case 15:
      return { ops: squareOps(), fill: "col", stroke: false };
    case 16:
      return { ops: circleOps(PCH_RADIUS), fill: "col", stroke: false };
    case 20:
      return { ops: circleOps(0.25), fill: "col", stroke: true };
    case 19:
      return { ops: circleOps(PCH_RADIUS), fill: "col", stroke: true };
    case 17:
      return { ops: triangleOps(false), fill: "col", stroke: false };
    case 24:
      return { ops: triangleOps(false), fill: "gpar", stroke: true };
    case 18:
      return { ops: diamondOps(PCH_RADIUS), fill: "col", stroke: false };
    case 23:
      return { ops: diamondOps(PCH_RADIUS * PCH_DMDC), fill: "gpar", stroke: true };
    case 21:
      return { ops: circleOps(PCH_RADIUS), fill: "gpar", stroke: true };
    case 22:
      return { ops: squareOps(PCH_RADIUS * PCH_SQRC), fill: "gpar", stroke: true };
    case 25:
      return { ops: triangleOps(true), fill: "gpar", stroke: true };
    default:
      return { ops: circleOps(PCH_RADIUS), fill: "none", stroke: true };
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
        const d = xsplinePath(node, matrix, this.scene.size);
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
        const subpaths = curveSubPaths(node, matrix, this.scene.size);
        const d = pathData(subpaths, false);
        this.emit(
          node,
          id,
          parent,
          viewport,
          el("path", { d, ...styleAttributes(gpar, scale, { fill: node.params["open"] !== true }) }),
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
          const half = Math.abs(size * scale * PCH_RADIUS);
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
    const spec = fontSpec(font);
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
        "font-family": spec.family,
        "font-weight": spec.weight,
        "font-style": spec.style,
        "font-size": num(size),
        "text-anchor": anchor === "left" ? "start" : anchor === "right" ? "end" : "middle",
        "dominant-baseline": baselineAttribute(baseline),
        // 浏览器只认 CSS 的近似基线；diff 侧按 IR 的原始 baseline 用与
        // `ggskia._place_text` 相同的 cap height 口径落基线（见 svgtext.py）。
        "data-baseline": baseline,
        fill: fill ?? "none",
        "fill-opacity": num(colourOpacity(gpar.col, gpar.alpha)),
      });
      if (lines.length === 1) {
        element.textContent = lines[0];
      } else {
        // 多行：grid 缺省 lineheight = 1.2（绘制行距 1.44 × size，ir.md §7）。
        const dy = size * LINE_SPACING;
        const offset =
          baseline === "top" || baseline === "alphabetic"
            ? 0
            : baseline === "bottom"
              ? -(lines.length - 1) * dy
              : (-(lines.length - 1) * dy) / 2;
        lines.forEach((line, index) => {
          const tspan = el("tspan", { x: 0, y: num(offset + index * dy) });
          tspan.textContent = line;
          element.append(tspan);
        });
      }
      // 文本的包围盒按 IR 给的最终宽度估：宽度是跨端对账的字段（ir.md §7）。
      // 旋转（`angle != 0`）必须进包围盒：轴对齐的旧算法在 rot=90 时把一段
      // 竖排文字算成一条水平细条，hover / 裁剪 / 视口统计全偏。
      const left = anchor === "right" ? -width : anchor === "center" ? -width / 2 : 0;
      const top = baseline === "top" ? 0 : baseline === "bottom" ? -size : -size / 2;
      const height = (lines.length - 1) * size * LINE_SPACING + size;
      const placement = angle
        ? compose(anchorMatrix, rotateMatrix(-angle))
        : anchorMatrix;
      const corners = [
        [left, top],
        [left + width, top],
        [left + width, top + height],
        [left, top + height],
      ].map(([x, y]) => mapPoint(placement, x, y));
      const box = corners.reduce(
        (acc, [x, y]) => ({
          x0: Math.min(acc.x0, x),
          y0: Math.min(acc.y0, y),
          x1: Math.max(acc.x1, x),
          y1: Math.max(acc.y1, y),
        }),
        { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity },
      );
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
/** 按 `id` 把 points 缓冲切成若干组，组内保留原始点序（IR 的 bulk 口径）。 */
function pointGroups(node: IrNode, matrix: Matrix): Point[][] {
  const points = node.bufs["points"];
  const ids = node.bufs["id"] ?? null;
  const groups: Point[][] = [];
  let current: Point[] = [];
  let start = 0;
  for (let row = 1; row <= points.rows; row++) {
    const changed = row === points.rows || (ids !== null && ids.data[row] !== ids.data[start]);
    if (!changed) continue;
    current = [];
    for (let index = start; index < row; index++) {
      current.push(
        mapPoint(matrix, points.data[index * 2] as number, points.data[index * 2 + 1] as number),
      );
    }
    if (current.length >= 2) groups.push(current);
    start = row;
  }
  return groups;
}

function sampledPath(sampled: Point[]): SubPath | null {
  if (sampled.length < 2) return null;
  const sub = pushSubPath([], sampled[0]);
  for (let index = 1; index < sampled.length; index++) {
    sub.segments.push(["L", [sampled[index][0], sampled[index][1]]]);
  }
  return sub;
}

/** xspline：与 `ggskia.curves.xspline_points` 同一套 R 公式（不是 Catmull-Rom 近似）。 */
function xsplinePath(node: IrNode, matrix: Matrix, page: [number, number]): string {
  const groups = pointGroups(node, matrix);
  const open = node.params["open"] !== false;
  const shape = node.params["shape"] as number;
  const subpaths: SubPath[] = [];
  for (const group of groups) {
    const sampled = xsplinePoints(group, shape, open, true, page);
    const sub = sampledPath(sampled);
    if (sub !== null) subpaths.push(sub);
  }
  return pathData(subpaths, !open);
}

/** grid.curve：先翻到 R 坐标求控制点/采样，再翻回页面坐标（SIL-636）。 */
function curveSubPaths(node: IrNode, matrix: Matrix, page: [number, number]): SubPath[] {
  const ends = node.bufs["ends"];
  const open = node.params["open"] !== false;
  const height = page[1];
  const subpaths: SubPath[] = [];
  for (let row = 0; row < ends.rows; row++) {
    const x1 = ends.data[row * 4] as number;
    const y1 = ends.data[row * 4 + 1] as number;
    const x2 = ends.data[row * 4 + 2] as number;
    const y2 = ends.data[row * 4 + 3] as number;
    if (![x1, y1, x2, y2].every(Number.isFinite)) continue;
    let sampled: Point[];
    try {
      sampled = curvePoints(x1, height - y1, x2, height - y2, {
        curvature: node.params["curvature"] as number,
        angle: node.params["angle"] as number,
        ncp: node.params["ncp"] as number,
        shape: node.params["shape"] as number,
        square: node.params["square"] as boolean,
        inflect: node.params["inflect"] as boolean,
        open,
        page,
      });
    } catch {
      sampled = [
        [x1, y1],
        [x2, y2],
      ];
    }
    const mapped = sampled.map(([x, y]) => mapPoint(matrix, x, height - y));
    const sub = sampledPath(mapped);
    if (sub !== null) subpaths.push(sub);
  }
  return subpaths;
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

/**
 * IR 的 `font` 是已解析的单个字族 key（`Noto Sans CJK SC`、`Noto Sans CJK SC:bold`、
 * `…:italic`、`…:bold-italic`），不是回退栈（ir.md §7）。浏览器端补系统栈，并把
 * 后缀翻成 `font-weight` / `font-style`；只把 key 当 family 会把粗斜体画成常规字面。
 *
 * 回退栈来自 `fonts.generated.ts`（由 `tools/viewer/emit_fonts.py` 从 rules.json
 * 生成），因此只有受管字族、**没有 `sans-serif`**：浏览器不会悄悄落到宿主字体上。
 * 字体文件由 `fonts.css` 的 `@font-face` 从 `web/viewer/fonts/` 加载。
 */
function fontSpec(font: string): { family: string; weight: string; style: string } {
  const [rawFamily, ...suffixes] = font.split(":");
  const suffix = suffixes.join(":").trim().toLowerCase();
  const family = rawFamily.trim() || DEFAULT_FAMILY;
  const stack = [family, ...FALLBACK_FAMILIES.filter((name) => name !== family)];
  return {
    family: stack.map(quoteFamily).join(", "),
    weight: suffix.includes("bold") ? "bold" : "normal",
    style: suffix.includes("italic") ? "italic" : "normal",
  };
}

function quoteFamily(name: string): string {
  return /^[A-Za-z][\w-]*$/.test(name) ? name : `"${name}"`;
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

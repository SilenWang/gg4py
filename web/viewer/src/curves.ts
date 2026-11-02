/**
 * 曲线求值：`xspline` / `grid::curve`（`docs/notes/ir.md` §4）。
 *
 * IR 把曲线留成语义参数（`shape` / `curvature` / `angle` / `ncp` / `square` /
 * `inflect`），由设备求值成折线。查看器与桌面设备必须用同一套公式，否则同一份
 * IR 在两边画出不同形状——这里逐函数移植 `src/ggskia/curves.py`（它本身是 R
 * `src/main/xspline.c` 与 `grid:::calcCurveGrob` 的移植），不做贝塞尔近似。
 *
 * 坐标系：`xsplinePoints()` 是纯几何；`curvePoints()` 的 `angle` 定义在 R 的
 * y 向上坐标系里，调用方要先把控制点翻成 R 坐标、求值后再翻回来
 * （`ggskia/skia.py::_draw_curve` 的口径）。
 */

export type Point = [number, number];

/** R 的 xspline 在 1200 ppi 的整数网格上算步长（xfig 的口径）。 */
const PT_TO_XFIG = 1200.0 / 72.0;
/** 每段至少 5 个采样点。 */
const MAX_STEP = 0.2;
const LOW_PRECISION = 1.0;

function fBlend(numerator: number, denominator: number): number {
  const p = 2 * denominator * denominator;
  const u = numerator / denominator;
  const u2 = u * u;
  return u * u2 * (10 - p + (2 * p - 15) * u + (6 - p) * u2);
}

function gBlend(u: number, q: number): number {
  return u * (q + u * (2 * q + u * (8 - 12 * q + u * (14 * q - 11 + u * (4 - 5 * q)))));
}

function hBlend(u: number, q: number): number {
  const u2 = u * u;
  return u * (q + u * (2 * q + u2 * (-2 * q - u * q)));
}

function blend(s1: number, s2: number, k: number, t: number): [number, number, number, number] {
  let a0: number;
  let a2: number;
  let a1: number;
  let a3: number;
  if (s1 < 0) {
    const q = -s1;
    a0 = hBlend(-t, q);
    a2 = gBlend(t, q);
  } else {
    let tk = k + 1 + s1;
    a0 = t + k + 1 < tk ? fBlend(t + k + 1 - tk, k - tk) : 0;
    tk = k + 1 - s1;
    a2 = fBlend(t + k + 1 - tk, k + 2 - tk);
  }
  if (s2 < 0) {
    const q = -s2;
    a1 = gBlend(1 - t, q);
    a3 = hBlend(t - 1, q);
  } else {
    let tk = k + 2 + s2;
    a1 = fBlend(t + k + 1 - tk, k + 1 - tk);
    tk = k + 2 - s2;
    a3 = t + k + 1 > tk ? fBlend(t + k + 1 - tk, k + 3 - tk) : 0;
  }
  return [a0, a1, a2, a3];
}

function pointAt(window: Point[], s1: number, s2: number, k: number, t: number): Point {
  const [a0, a1, a2, a3] = blend(s1, s2, k, t);
  const total = a0 + a1 + a2 + a3;
  if (total === 0 || !Number.isFinite(total)) return window[1];
  return [
    (a0 * window[0][0] + a1 * window[1][0] + a2 * window[2][0] + a3 * window[3][0]) / total,
    (a0 * window[0][1] + a1 * window[1][1] + a2 * window[2][1] + a3 * window[3][1]) / total,
  ];
}

/** `step_computing()`：按段长与弯曲程度决定参数步长。 */
function stepFor(
  window: Point[],
  s1: number,
  s2: number,
  k: number,
  precision: number,
  diagonal: number,
): number {
  if (s1 === 0 && s2 === 0) return 1.0;
  const start = s1 > 0 ? pointAt(window, s1, s2, k, 0.0) : window[1];
  const end = s2 > 0 ? pointAt(window, s1, s2, k, 1.0) : window[2];
  const mid = pointAt(window, s1, s2, k, 0.5);

  const xv1 = start[0] - mid[0];
  const yv1 = start[1] - mid[1];
  const xv2 = end[0] - mid[0];
  const yv2 = end[1] - mid[1];
  const scal = xv1 * xv2 + yv1 * yv2;
  const sides = Math.sqrt((xv1 * xv1 + yv1 * yv1) * (xv2 * xv2 + yv2 * yv2));
  const angleCos = sides === 0 ? 0 : scal / sides;

  let distance = Math.hypot(end[0] - start[0], end[1] - start[1]);
  if (!Number.isFinite(distance)) return 1.0;
  // 控制点可能被甩到页面外很多；R 用页面对角线兜住步数上限。
  distance = Math.min(distance, diagonal);
  const steps = Math.sqrt(distance) / 2 + Math.trunc((1 + angleCos) * 10);
  let step = steps === 0 ? 1.0 : precision / steps;
  if (!Number.isFinite(step) || step > MAX_STEP || step === 0) step = MAX_STEP;
  return step;
}

/** `add_point()`：相邻完全相同的点只留一个。 */
class Collector {
  readonly points: Point[] = [];

  add(x: number, y: number): void {
    const last = this.points[this.points.length - 1];
    if (last !== undefined && last[0] === x && last[1] === y) return;
    this.points.push([x, y]);
  }
}

function segment(
  out: Collector,
  window: Point[],
  s1: number,
  s2: number,
  k: number,
  precision: number,
  diagonal: number,
): void {
  const step = stepFor(window, s1, s2, k, precision, diagonal);
  let t = 0.0;
  while (t < 1) {
    const point = pointAt(window, s1, s2, k, t);
    out.add(point[0], point[1]);
    t += step;
  }
}

export interface XsplineOptions {
  open?: boolean;
  repEnds?: boolean;
  /** 页面尺寸（pt）；步长公式与 R 的页面尺寸同口径。 */
  page?: Point;
  precision?: number;
}

/** 一组控制点 → 采样后的折线（pt，与输入同一坐标系）。`shapes` 逐点时长度必须与控制点一致。 */
export function xsplinePoints(
  points: Point[],
  shapes: number | number[],
  options: XsplineOptions = {},
): Point[] {
  const open = options.open ?? true;
  const repEnds = options.repEnds ?? true;
  const page = options.page ?? [612.0, 792.0];
  const precision = options.precision ?? LOW_PRECISION;
  const count = points.length;
  let shapeList: number[] =
    typeof shapes === "number" ? new Array<number>(count).fill(shapes) : [...shapes];
  if (open && repEnds) {
    // 开放样条把两端钳成直线：首末控制点的 shape 不参与求值。
    shapeList = [0.0, ...shapeList.slice(1, count - 1), 0.0];
  }

  const windowPt: Point[] = points.map(([x, y]) => [x * PT_TO_XFIG, y * PT_TO_XFIG]);
  const diagonal = Math.hypot(page[0], page[1]) * PT_TO_XFIG;
  const out = new Collector();

  if (!open) {
    let window: Point[] = [windowPt[count - 1], windowPt[0], windowPt[1], windowPt[2]];
    for (let k = 0; k < count; k++) {
      segment(out, window, shapeList[k % count], shapeList[(k + 1) % count], k, precision, diagonal);
      window = [
        windowPt[k % count],
        windowPt[(k + 1) % count],
        windowPt[(k + 2) % count],
        windowPt[(k + 3) % count],
      ];
    }
  } else if (repEnds) {
    let window: Point[] = [
      windowPt[0],
      windowPt[0],
      windowPt[1],
      count === 2 ? windowPt[1] : windowPt[2],
    ];
    let k = 0;
    for (;;) {
      segment(out, window, shapeList[k], shapeList[k + 1], k, precision, diagonal);
      if (k + 3 >= count) break;
      window = [windowPt[k], windowPt[k + 1], windowPt[k + 2], windowPt[k + 3]];
      k += 1;
    }
    window = [
      count === 2 ? windowPt[count - 2] : windowPt[count - 3],
      windowPt[count - 2],
      windowPt[count - 1],
      windowPt[count - 1],
    ];
    segment(out, window, shapeList[count - 2], shapeList[count - 1], k, precision, diagonal);
    out.add(window[3][0], window[3][1]);
  } else {
    let window: Point[] = [windowPt[0], windowPt[1], windowPt[2], windowPt[3]];
    for (let k = 0; k < count - 3; k++) {
      window = [windowPt[k], windowPt[k + 1], windowPt[k + 2], windowPt[k + 3]];
      segment(out, window, shapeList[k], shapeList[k + 1], k, precision, diagonal);
    }
    const last = pointAt(window, shapeList[count - 3], shapeList[count - 2], count - 4, 1.0);
    out.add(last[0], last[1]);
  }
  return out.points.map(([x, y]): Point => [x / PT_TO_XFIG, y / PT_TO_XFIG]);
}

// ---------------------------------------------------------------------------
// grid::curveGrob
// ---------------------------------------------------------------------------

function slope(dx: number, dy: number): number {
  if (dx === 0) return dy >= 0 ? Number.POSITIVE_INFINITY : Number.NEGATIVE_INFINITY;
  return dy / dx;
}

function sign(value: number): number {
  if (value > 0) return 1;
  if (value < 0) return -1;
  return 0;
}

/** R 的除法：除零给 ±Inf、0/0 给 NaN。 */
function div(a: number, b: number): number {
  if (b === 0) return a === 0 ? Number.NaN : Math.sign(a) * Number.POSITIVE_INFINITY;
  return a / b;
}

/** `atan(a / b)`，含 `b == 0` 的 R 语义。 */
function atanDiv(a: number, b: number): number {
  if (b === 0) return a === 0 ? Number.NaN : Math.sign(a) * (Math.PI / 2);
  return Math.atan(a / b);
}

function calcOrigin(x1: number, y1: number, x2: number, y2: number, origin: number): Point {
  const xm = (x1 + x2) / 2;
  const ym = (y1 + y2) / 2;
  const g = slope(x2 - x1, y2 - y1);
  let tmpox: number;
  let tmpoy: number;
  if (!Number.isFinite(g)) {
    tmpox = xm;
    tmpoy = ym + (origin * (y2 - y1)) / 2;
  } else if (g === 0) {
    tmpox = xm + (origin * (x2 - x1)) / 2;
    tmpoy = ym;
  } else {
    tmpox = xm + (origin * (x2 - x1)) / 2;
    tmpoy = ym + (origin * (y2 - y1)) / 2;
  }
  const sintheta = -1.0;
  return [xm - (tmpoy - ym) * sintheta, ym + (tmpox - xm) * sintheta];
}

function calcControlPoints(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  curvature: number,
  angle: number,
  ncp: number,
): Point[] {
  const xm = (x1 + x2) / 2;
  const ym = (y1 + y2) / 2;
  const dx = x2 - x1;
  const dy = y2 - y1;
  const theta = (angle / 180.0) * Math.PI;
  const sina = Math.sin(theta);
  const cosa = Math.cos(theta);
  const cornerx = xm + (x1 - xm) * cosa - (y1 - ym) * sina;
  const cornery = ym + (y1 - ym) * cosa + (x1 - xm) * sina;
  const beta = -atanDiv(cornery - y1, cornerx - x1);
  const sinb = Math.sin(beta);
  const cosb = Math.cos(beta);
  let newx2 = x1 + dx * cosb - dy * sinb;
  const newy2 = y1 + dy * cosb + dx * sinb;
  const scalex = div(newy2 - y1, newx2 - x1);
  const newx1 = x1 * scalex;
  newx2 = newx2 * scalex;
  const ratio = 2 * Math.sin(Math.atan(curvature)) ** 2;
  const origin = curvature - curvature / ratio;
  const direction = curvature > 0 ? 1 : -1;
  const [ox, oy] = calcOrigin(newx1, y1, newx2, newy2, origin);
  const maxtheta = Math.PI + sign(origin * direction) * 2 * Math.atan(Math.abs(origin));
  const points: Point[] = [];
  const sinnb = Math.sin(-beta);
  const cosnb = Math.cos(-beta);
  for (let index = 1; index <= ncp; index++) {
    const angleI = (direction * maxtheta * index) / (ncp + 1);
    const costheta = Math.cos(angleI);
    const sintheta = Math.sin(angleI);
    let cpx = ox + (newx1 - ox) * costheta - (y1 - oy) * sintheta;
    let cpy = oy + (y1 - oy) * costheta + (newx1 - ox) * sintheta;
    cpx = div(cpx, scalex);
    points.push([
      x1 + (cpx - x1) * cosnb - (cpy - y1) * sinnb,
      y1 + (cpy - y1) * cosnb + (cpx - x1) * sinnb,
    ]);
  }
  return points;
}

function calcSquareControlPoints(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  curvature: number,
  angle: number,
  ncp: number,
): { points: Point[]; end: boolean } {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const g = slope(dx, dy);
  let end = g > 1 || (g < 0 && g > -1);
  if (curvature < 0) end = !end;
  let startx: number;
  let starty: number;
  let endx: number;
  let endy: number;
  if (end) {
    startx = x1;
    starty = y1;
    endx = Math.abs(g) > 1 ? x1 + dx : x1 + sign(g) * dy;
    endy = Math.abs(g) > 1 ? y1 + sign(g) * dx : y1 + dy;
  } else {
    startx = Math.abs(g) > 1 ? x2 - dx : x2 - sign(g) * dy;
    starty = Math.abs(g) > 1 ? y2 - sign(g) * dx : y2 - dy;
    endx = x2;
    endy = y2;
  }
  const inner = calcControlPoints(startx, starty, endx, endy, curvature, angle, ncp);
  // `interleave()`：e 为真时控制点在前、端点在最后，否则起点在前。
  return end ? { points: [...inner, [endx, endy]], end } : { points: [[startx, starty], ...inner], end };
}

function interleaveShapes(ncp: number, value: number, square: number, end: boolean): number[] {
  const filler = new Array<number>(ncp).fill(value);
  return end ? [...filler, square] : [square, ...filler];
}

export interface CurveOptions {
  curvature?: number;
  angle?: number;
  ncp?: number;
  shape?: number;
  square?: boolean;
  squareShape?: number;
  inflect?: boolean;
  open?: boolean;
  page?: Point;
}

/** 一条 `grid.curve` → 折线（pt，仍在 R 的 y 向上坐标系里）。 */
export function curvePoints(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  options: CurveOptions = {},
): Point[] {
  const curvature = options.curvature ?? 1.0;
  const angle = options.angle ?? 90.0;
  const ncp = options.ncp ?? 1;
  const shape = options.shape ?? 0.5;
  const square = options.square ?? true;
  const squareShape = options.squareShape ?? 1.0;
  const inflect = options.inflect ?? false;
  const open = options.open ?? true;
  const page = options.page ?? [612.0, 792.0];

  if (x1 === x2 && y1 === y2) return [[x1, y1]];
  if (curvature === 0 || angle < 1 || angle > 179) return [[x1, y1], [x2, y2]];
  if (square && (x1 === x2 || y1 === y2)) return [[x1, y1], [x2, y2]];

  let control: Point[];
  let shapes: number[];
  if (inflect) {
    const xm = (x1 + x2) / 2;
    const ym = (y1 + y2) / 2;
    let shape1: number[] = new Array<number>(ncp).fill(shape);
    let shape2: number[] = new Array<number>(ncp).fill(shape);
    let first: Point[];
    let second: Point[];
    if (square) {
      const a = calcSquareControlPoints(x1, y1, xm, ym, curvature, angle, ncp);
      const b = calcSquareControlPoints(xm, ym, x2, y2, -curvature, angle, ncp);
      first = a.points;
      second = b.points;
      shape1 = interleaveShapes(ncp, shape, squareShape, a.end);
      shape2 = interleaveShapes(ncp, shape, squareShape, b.end);
    } else {
      first = calcControlPoints(x1, y1, xm, ym, curvature, angle, ncp);
      second = calcControlPoints(xm, ym, x2, y2, -curvature, angle, ncp);
    }
    control = [[x1, y1], ...first, [xm, ym], ...second, [x2, y2]];
    shapes = [0.0, ...shape1, 0.0, ...shape2, 0.0];
  } else if (square) {
    const result = calcSquareControlPoints(x1, y1, x2, y2, curvature, angle, ncp);
    shapes = [0.0, ...interleaveShapes(ncp, shape, squareShape, result.end), 0.0];
    control = [[x1, y1], ...result.points, [x2, y2]];
  } else {
    const inner = calcControlPoints(x1, y1, x2, y2, curvature, angle, ncp);
    shapes = [0.0, ...new Array<number>(ncp).fill(shape), 0.0];
    control = [[x1, y1], ...inner, [x2, y2]];
  }

  return xsplinePoints(control, shapes, { open, page });
}

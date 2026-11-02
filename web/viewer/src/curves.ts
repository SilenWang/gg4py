/**
 * `xspline` / `curve` 的浏览器端求值。
 *
 * 逐个函数移植自 `src/ggskia/curves.py`（那又是 R 4.5.3 的
 * `src/main/xspline.c` 与 `grid:::calcCurveGrob`）。IR 只存语义参数
 * （shape / curvature / angle / ncp / square / inflect），求值必须与桌面设备
 * 同一套公式，否则 `geom-curve-basic` 会沿弦线镜像、xspline 的弯曲程度也
 * 对不上（见 `docs/notes/viewer.md` §6）。
 *
 * 坐标口径：`curvePoints()` 期望 **R 坐标（y 向上）**；调用方先把页面 y 翻成
 * `height - y`，求值后再翻回来（与 `ggskia.skia._draw_curve` 一致）。
 */

export type Point = [number, number];

/** R 的 xspline 在 1200 ppi 的整数网格上算步长。 */
const PT_TO_XFIG = 1200 / 72;
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
  let a1: number;
  let a3: number;
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
  const x =
    (a0 * window[0][0] + a1 * window[1][0] + a2 * window[2][0] + a3 * window[3][0]) / total;
  const y =
    (a0 * window[0][1] + a1 * window[1][1] + a2 * window[2][1] + a3 * window[3][1]) / total;
  return [x, y];
}

function stepSize(
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
  distance = Math.min(distance, diagonal);
  const steps = Math.sqrt(distance) / 2 + Math.trunc((1 + angleCos) * 10);
  let step = steps === 0 ? 1.0 : precision / steps;
  if (!Number.isFinite(step) || step > MAX_STEP || step === 0) step = MAX_STEP;
  return step;
}

function segment(
  out: Point[],
  window: Point[],
  s1: number,
  s2: number,
  k: number,
  precision: number,
  diagonal: number,
): void {
  const step = stepSize(window, s1, s2, k, precision, diagonal);
  let t = 0.0;
  const add = (point: Point): void => {
    const last = out[out.length - 1];
    if (last !== undefined && last[0] === point[0] && last[1] === point[1]) return;
    out.push(point);
  };
  while (t < 1) {
    add(pointAt(window, s1, s2, k, t));
    t += step;
  }
}

/** 一组控制点 → 采样后的折线（与 `ggskia.curves.xspline_points` 同一口径）。 */
export function xsplinePoints(
  points: Point[],
  shapes: number | number[],
  open = true,
  repEnds = true,
  page: [number, number] = [612, 792],
  precision = LOW_PRECISION,
): Point[] {
  const count = points.length;
  const shapeList = Array.isArray(shapes)
    ? shapes.map((value) => Number(value))
    : Array.from({ length: count }, () => Number(shapes));
  if (shapeList.length !== count) {
    throw new Error(`xspline 的 shape 个数 ${shapeList.length} 与控制点 ${count} 不符`);
  }
  if (!open && count < 3) throw new Error("闭合 xspline 至少需要 3 个控制点");
  if (open && count < (repEnds ? 2 : 4)) throw new Error("开放 xspline 的控制点太少");
  if (open && repEnds) {
    shapeList[0] = 0;
    shapeList[count - 1] = 0;
  }

  const windowPt: Point[] = points.map(([x, y]) => [x * PT_TO_XFIG, y * PT_TO_XFIG]);
  const diagonal = Math.hypot(page[0], page[1]) * PT_TO_XFIG;
  const out: Point[] = [];

  if (!open) {
    let window: Point[] = [windowPt[count - 1], windowPt[0], windowPt[1], windowPt[2]];
    for (let k = 0; k < count; k++) {
      segment(
        out,
        window,
        shapeList[k % count],
        shapeList[(k + 1) % count],
        k,
        precision,
        diagonal,
      );
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
    out.push(window[3]);
  } else {
    for (let k = 0; k < count - 3; k++) {
      const window = [windowPt[k], windowPt[k + 1], windowPt[k + 2], windowPt[k + 3]];
      segment(out, window, shapeList[k], shapeList[k + 1], k, precision, diagonal);
    }
    out.push(pointAt(windowPt.slice(count - 4), shapeList[count - 3], shapeList[count - 2], count - 4, 1.0));
  }

  return out.map(([x, y]) => [x / PT_TO_XFIG, y / PT_TO_XFIG]);
}

function slope(dx: number, dy: number): number {
  if (dx === 0) return dy >= 0 ? Infinity : -Infinity;
  return dy / dx;
}

function sign(value: number): number {
  if (value > 0) return 1;
  if (value < 0) return -1;
  return 0;
}

function divide(a: number, b: number): number {
  if (b === 0) return a === 0 ? NaN : Math.sign(a) * Infinity;
  return a / b;
}

function atanDiv(a: number, b: number): number {
  if (b === 0) return a === 0 ? NaN : Math.sign(a) * (Math.PI / 2);
  return Math.atan(a / b);
}

function calcOrigin(x1: number, y1: number, x2: number, y2: number, origin: number): Point {
  const xm = (x1 + x2) / 2;
  const ym = (y1 + y2) / 2;
  const m = slope(x2 - x1, y2 - y1);
  let tmpx: number;
  let tmpy: number;
  if (!Number.isFinite(m)) {
    tmpx = xm;
    tmpy = ym + (origin * (y2 - y1)) / 2;
  } else if (m === 0) {
    tmpx = xm + (origin * (x2 - x1)) / 2;
    tmpy = ym;
  } else {
    tmpx = xm + (origin * (x2 - x1)) / 2;
    tmpy = ym + (origin * (y2 - y1)) / 2;
  }
  const sintheta = -1.0;
  return [xm - (tmpy - ym) * sintheta, ym + (tmpx - xm) * sintheta];
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
  const theta = (angle / 180) * Math.PI;
  const sina = Math.sin(theta);
  const cosa = Math.cos(theta);
  const cornerx = xm + (x1 - xm) * cosa - (y1 - ym) * sina;
  const cornery = ym + (y1 - ym) * cosa + (x1 - xm) * sina;
  const beta = -atanDiv(cornery - y1, cornerx - x1);
  const sinb = Math.sin(beta);
  const cosb = Math.cos(beta);
  const newx2 = x1 + dx * cosb - dy * sinb;
  const newy2 = y1 + dy * cosb + dx * sinb;
  const scalex = divide(newy2 - y1, newx2 - x1);
  const newx1 = x1 * scalex;
  const scaledx2 = newx2 * scalex;
  const ratio = 2 * Math.sin(Math.atan(curvature)) ** 2;
  const origin = curvature - curvature / ratio;
  const direction = curvature > 0 ? 1.0 : -1.0;
  const [ox, oy] = calcOrigin(newx1, y1, scaledx2, newy2, origin);
  const maxtheta = Math.PI + sign(origin * direction) * 2 * Math.atan(Math.abs(origin));
  const points: Point[] = [];
  const sinnb = Math.sin(-beta);
  const cosnb = Math.cos(-beta);
  for (let index = 1; index <= ncp; index++) {
    const angleI = (direction * maxtheta * index) / (ncp + 1);
    const costheta = Math.cos(angleI);
    const sintheta = Math.sin(angleI);
    const cpx = ox + (newx1 - ox) * costheta - (y1 - oy) * sintheta;
    const cpy = oy + (y1 - oy) * costheta + (newx1 - ox) * sintheta;
    const scaledCpx = divide(cpx, scalex);
    points.push([
      x1 + (scaledCpx - x1) * cosnb - (cpy - y1) * sinnb,
      y1 + (cpy - y1) * cosnb + (scaledCpx - x1) * sinnb,
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
  const m = slope(dx, dy);
  let end = m > 1 || (m < 0 && m > -1);
  if (curvature < 0) end = !end;
  let startx: number;
  let starty: number;
  let endx: number;
  let endy: number;
  if (end) {
    startx = x1;
    starty = y1;
    endx = x1 + (Math.abs(m) > 1 ? dx : sign(m) * dy);
    endy = y1 + (Math.abs(m) > 1 ? sign(m) * dx : dy);
  } else {
    startx = x2 - (Math.abs(m) > 1 ? dx : sign(m) * dy);
    starty = y2 - (Math.abs(m) > 1 ? sign(m) * dx : dy);
    endx = x2;
    endy = y2;
  }
  const inner = calcControlPoints(startx, starty, endx, endy, curvature, angle, ncp);
  return { points: end ? [...inner, [endx, endy]] : [[startx, starty], ...inner], end };
}

function interleaveShapes(ncp: number, value: number, square: number, end: boolean): number[] {
  const filler = Array.from({ length: ncp }, () => value);
  return end ? [...filler, square] : [square, ...filler];
}

/** 一条 `grid.curve` → 折线（R 坐标；调用方负责 y 翻转与页面尺寸）。 */
export function curvePoints(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  options: {
    curvature?: number;
    angle?: number;
    ncp?: number;
    shape?: number;
    square?: boolean;
    squareShape?: number;
    inflect?: boolean;
    open?: boolean;
    page?: [number, number];
  } = {},
): Point[] {
  const curvature = options.curvature ?? 1.0;
  const angle = options.angle ?? 90.0;
  const ncp = options.ncp ?? 1;
  const shape = options.shape ?? 0.5;
  const square = options.square ?? true;
  const squareShape = options.squareShape ?? 1.0;
  const inflect = options.inflect ?? false;
  const open = options.open ?? true;
  const page = options.page ?? [612, 792];

  if (x1 === x2 && y1 === y2) throw new Error("curve 的两端不能重合");
  if (curvature === 0 || angle < 1 || angle > 179) {
    return [
      [x1, y1],
      [x2, y2],
    ];
  }
  if (square && (x1 === x2 || y1 === y2)) {
    return [
      [x1, y1],
      [x2, y2],
    ];
  }

  let control: Point[];
  let shapes: number[];
  if (inflect) {
    const xm = (x1 + x2) / 2;
    const ym = (y1 + y2) / 2;
    let shape1 = Array.from({ length: ncp }, () => shape);
    let shape2 = Array.from({ length: ncp }, () => shape);
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
    shapes = [0, ...shape1, 0, ...shape2, 0];
  } else if (square) {
    const inner = calcSquareControlPoints(x1, y1, x2, y2, curvature, angle, ncp);
    control = [[x1, y1], ...inner.points, [x2, y2]];
    shapes = [0, ...interleaveShapes(ncp, shape, squareShape, inner.end), 0];
  } else {
    control = [[x1, y1], ...calcControlPoints(x1, y1, x2, y2, curvature, angle, ncp), [x2, y2]];
    shapes = [0, ...Array.from({ length: ncp }, () => shape), 0];
  }
  return xsplinePoints(control, shapes, open, true, page);
}

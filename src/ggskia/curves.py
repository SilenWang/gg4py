"""曲线求值：`xspline` / `curve`（M0-8）。

IR 把曲线留成**语义参数**（`shape` / `curvature` / `angle` / `ncp` / `square` /
`inflect`），由设备按参考实现的公式求值成折线，而不是写方自己展平
（`docs/notes/ir.md` §4）。两边各算一次是故意的：上游快照的对齐点在曲线形状
本身，展平后的折线换一种采样密度就会漂。

- `xspline_points()` 是 R `src/main/xspline.c`（Xfig 3.2.4 的 X-spline，
  Blanc & Schlick, SIGGRAPH '95）的逐函数移植：`f`/`g`/`h` 混合函数、按曲率
  估步数、开/闭两套控制点窗口，一行都没换。
- `curve_points()` 是 `grid:::calcCurveGrob` / `calcControlPoints` /
  `calcSquareControlPoints` 的移植：grid 的 `curveGrob` 本质是把算出来的控制点
  交给 `xsplineGrob(shape = 0 …)`，终端点 shape 为 0（直线段），中间点用
  `shape` / `squareShape`。

对拍：`tools/refs/device_ref.R` 生成 `tests/fixtures/device_r_reference.json`，
`tests/test_device_r_parity.py` 逐点比对（采样密度也一致，因为步长公式用的是
同一份页面尺寸）。

坐标系：纯几何，y 朝上朝下都一样——整页翻到 y 向下时曲线跟着镜像，正是设备
要的形状。
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

__all__ = ["curve_points", "xspline_points"]

# R 的 xspline 在 1200 ppi 的整数网格上算步长（`xfig` 的口径）。
_UNITS_PER_INCH = 1200.0
_PT_PER_INCH = 72.0
_PT_TO_XFIG = _UNITS_PER_INCH / _PT_PER_INCH

#: 步长上限（`MAX_SPLINE_STEP`）：每段至少 5 个采样点。
MAX_STEP = 0.2
#: `GEXspline()` 传给 `compute_*_spline()` 的精度（`LOW_PRECISION`）。
LOW_PRECISION = 1.0


# ---------------------------------------------------------------------------
# X-spline（R: src/main/xspline.c）
# ---------------------------------------------------------------------------


def _f_blend(numerator: float, denominator: float) -> float:
    p = 2 * denominator * denominator
    u = numerator / denominator
    u2 = u * u
    return u * u2 * (10 - p + (2 * p - 15) * u + (6 - p) * u2)


def _g_blend(u: float, q: float) -> float:
    return u * (q + u * (2 * q + u * (8 - 12 * q + u * (14 * q - 11 + u * (4 - 5 * q)))))


def _h_blend(u: float, q: float) -> float:
    u2 = u * u
    return u * (q + u * (2 * q + u2 * (-2 * q - u * q)))


def _blend(s1: float, s2: float, k: int, t: float) -> tuple[float, float, float, float]:
    """`t` 处的四个控制点权重（对应 C 的 `A_blend[0..3]`）。

    C 里按 `s1` / `s2` 的正负分成四个分支两两组合；逐点按下标自己的符号选
    函数与之一一对应（负值走 `g`/`h`，非负走 `f`）。
    """
    if s1 < 0:
        q = -s1
        a0 = _h_blend(-t, q)
        a2 = _g_blend(t, q)
    else:
        tk = k + 1 + s1
        a0 = _f_blend(t + k + 1 - tk, k - tk) if t + k + 1 < tk else 0.0
        tk = k + 1 - s1
        a2 = _f_blend(t + k + 1 - tk, k + 2 - tk)
    if s2 < 0:
        q = -s2
        a1 = _g_blend(1 - t, q)
        a3 = _h_blend(t - 1, q)
    else:
        tk = k + 2 + s2
        a1 = _f_blend(t + k + 1 - tk, k + 1 - tk)
        tk = k + 2 - s2
        a3 = _f_blend(t + k + 1 - tk, k + 3 - tk) if t + k + 1 > tk else 0.0
    return a0, a1, a2, a3


def _point_at(
    window: Sequence[tuple[float, float]], s1: float, s2: float, k: int, t: float
) -> tuple[float, float]:
    a0, a1, a2, a3 = _blend(s1, s2, k, t)
    total = a0 + a1 + a2 + a3
    if total == 0.0 or not math.isfinite(total):
        return window[1]
    x = (a0 * window[0][0] + a1 * window[1][0] + a2 * window[2][0] + a3 * window[3][0]) / total
    y = (a0 * window[0][1] + a1 * window[1][1] + a2 * window[2][1] + a3 * window[3][1]) / total
    return x, y


def _step(
    window: Sequence[tuple[float, float]],
    s1: float,
    s2: float,
    k: int,
    precision: float,
    diagonal: float,
) -> float:
    """`step_computing()`：按段长与弯曲程度决定参数步长。"""
    if s1 == 0 and s2 == 0:
        return 1.0
    if s1 > 0:
        xstart, ystart = _point_at(window, s1, s2, k, 0.0)
    else:
        xstart, ystart = window[1]
    if s2 > 0:
        xend, yend = _point_at(window, s1, s2, k, 1.0)
    else:
        xend, yend = window[2]
    xmid, ymid = _point_at(window, s1, s2, k, 0.5)

    xv1, yv1 = xstart - xmid, ystart - ymid
    xv2, yv2 = xend - xmid, yend - ymid
    scal = xv1 * xv2 + yv1 * yv2
    sides = math.sqrt((xv1 * xv1 + yv1 * yv1) * (xv2 * xv2 + yv2 * yv2))
    angle_cos = 0.0 if sides == 0.0 else scal / sides

    distance = math.hypot(xend - xstart, yend - ystart)
    # 控制点可能被甩到页面外很多；R 用页面对角线兜住步数上限（Paul 2009-01-25）。
    if not math.isfinite(distance):
        return 1.0
    distance = min(distance, diagonal)
    steps = math.sqrt(distance) / 2 + int((1 + angle_cos) * 10)
    step = 1.0 if steps == 0 else precision / steps
    if not math.isfinite(step) or step > MAX_STEP or step == 0:
        step = MAX_STEP
    return step


class _Collector:
    """`add_point()`：相邻完全相同的点只留一个（R 的同一口径）。"""

    def __init__(self) -> None:
        self.points: list[tuple[float, float]] = []

    def add(self, x: float, y: float) -> None:
        if self.points and self.points[-1] == (x, y):
            return
        self.points.append((x, y))


def _segment(
    out: _Collector,
    window: Sequence[tuple[float, float]],
    s1: float,
    s2: float,
    k: int,
    precision: float,
    diagonal: float,
) -> None:
    step = _step(window, s1, s2, k, precision, diagonal)
    t = 0.0
    while t < 1:
        out.add(*_point_at(window, s1, s2, k, t))
        t += step


def xspline_points(
    points: Sequence[tuple[float, float]] | np.ndarray,
    shapes: float | Sequence[float],
    *,
    open: bool = True,
    rep_ends: bool = True,
    page: tuple[float, float] = (612.0, 792.0),
    precision: float = LOW_PRECISION,
) -> np.ndarray:
    """一组控制点 → 采样后的折线（pt，与输入同一坐标系）。

    `shapes` 是逐控制点的 shape（-1..1）：标量广播到每个点。`open=False` 时
    按闭合样条处理（第一个点的邻居是最后一个点）。
    """
    control = [(float(x), float(y)) for x, y in points]
    count = len(control)
    if isinstance(shapes, (int, float)):
        shape_list = [float(shapes)] * count
    else:
        shape_list = [float(value) for value in shapes]
        if len(shape_list) != count:
            raise ValueError(f"xspline 的 shape 个数 {len(shape_list)} 与控制点 {count} 不符")
    if not open and count < 3:
        raise ValueError("闭合 xspline 至少需要 3 个控制点")
    if open and count < (2 if rep_ends else 4):
        raise ValueError("开放 xspline 的控制点太少")
    if open and rep_ends:
        # R 4.5.3 的开放样条把两端钳成直线：首末控制点的 shape 不参与求值
        # （`tests/fixtures/device_r_reference.json` 的 open 用例逐点钉住；
        # closed 用例用的则是全部 shape）。照实测行为对齐，别按源码里的
        # 重复控制点去猜。
        shape_list = [0.0, *shape_list[1:-1], 0.0]

    # 步长公式在 R 里用 1200 ppi 的设备坐标；换算一次再算回去。
    window_pt = [(x * _PT_TO_XFIG, y * _PT_TO_XFIG) for x, y in control]
    diagonal = math.hypot(page[0], page[1]) * _PT_TO_XFIG
    out = _Collector()

    if not open:
        window = [window_pt[-1], window_pt[0], window_pt[1], window_pt[2]]
        for k in range(count):
            _segment(
                out,
                window,
                shape_list[k % count],
                shape_list[(k + 1) % count],
                k,
                precision,
                diagonal,
            )
            window = [
                window_pt[k % count],
                window_pt[(k + 1) % count],
                window_pt[(k + 2) % count],
                window_pt[(k + 3) % count],
            ]
    elif rep_ends:
        window = [
            window_pt[0],
            window_pt[0],
            window_pt[1],
            window_pt[1] if count == 2 else window_pt[2],
        ]
        k = 0
        while True:
            _segment(out, window, shape_list[k], shape_list[k + 1], k, precision, diagonal)
            if k + 3 >= count:
                break
            window = [window_pt[k], window_pt[k + 1], window_pt[k + 2], window_pt[k + 3]]
            k += 1
        window = [
            window_pt[count - 2] if count == 2 else window_pt[count - 3],
            window_pt[count - 2],
            window_pt[count - 1],
            window_pt[count - 1],
        ]
        _segment(out, window, shape_list[count - 2], shape_list[count - 1], k, precision, diagonal)
        out.add(*window[3])
    else:
        for k in range(0, count - 3):
            window = [window_pt[k], window_pt[k + 1], window_pt[k + 2], window_pt[k + 3]]
            _segment(out, window, shape_list[k], shape_list[k + 1], k, precision, diagonal)
        out.add(*_point_at(window, shape_list[count - 3], shape_list[count - 2], count - 4, 1.0))

    return np.asarray(out.points, dtype=np.float64) / _PT_TO_XFIG


# ---------------------------------------------------------------------------
# grid::curveGrob（R: src/library/grid/R/curve.R）
# ---------------------------------------------------------------------------


def _slope(dx: float, dy: float) -> float:
    if dx == 0.0:
        return math.inf if dy >= 0 else -math.inf
    return dy / dx


def _sign(value: float) -> float:
    if value > 0:
        return 1.0
    if value < 0:
        return -1.0
    return 0.0


def _div(a: float, b: float) -> float:
    """R 的除法：除零给 ±Inf、0/0 给 NaN（Python 会直接抛异常）。"""
    if b == 0.0:
        return math.nan if a == 0.0 else math.copysign(math.inf, a)
    return a / b


def _atan_div(a: float, b: float) -> float:
    """`atan(a / b)`，含 `b == 0` 的 R 语义（切线取 ±π/2）。"""
    if b == 0.0:
        return math.nan if a == 0.0 else math.copysign(math.pi / 2, a)
    return math.atan(a / b)


def _calc_origin(x1: float, y1: float, x2: float, y2: float, origin: float) -> tuple[float, float]:
    xm, ym = (x1 + x2) / 2, (y1 + y2) / 2
    slope = _slope(x2 - x1, y2 - y1)
    if not math.isfinite(slope):
        tmpox, tmpoy = xm, ym + origin * (y2 - y1) / 2
    elif slope == 0.0:
        tmpox, tmpoy = xm + origin * (x2 - x1) / 2, ym
    else:
        tmpox, tmpoy = xm + origin * (x2 - x1) / 2, ym + origin * (y2 - y1) / 2
    sintheta = -1.0
    return xm - (tmpoy - ym) * sintheta, ym + (tmpox - xm) * sintheta


def _calc_control_points(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    curvature: float,
    angle: float,
    ncp: int,
) -> list[tuple[float, float]]:
    xm, ym = (x1 + x2) / 2, (y1 + y2) / 2
    dx, dy = x2 - x1, y2 - y1
    theta = angle / 180.0 * math.pi
    sina, cosa = math.sin(theta), math.cos(theta)
    cornerx = xm + (x1 - xm) * cosa - (y1 - ym) * sina
    cornery = ym + (y1 - ym) * cosa + (x1 - xm) * sina
    beta = -_atan_div(cornery - y1, cornerx - x1)
    sinb, cosb = math.sin(beta), math.cos(beta)
    newx2 = x1 + dx * cosb - dy * sinb
    newy2 = y1 + dy * cosb + dx * sinb
    scalex = _div(newy2 - y1, newx2 - x1)
    newx1 = x1 * scalex
    newx2 = newx2 * scalex
    ratio = 2 * (math.sin(math.atan(curvature)) ** 2)
    origin = curvature - curvature / ratio
    direction = 1.0 if curvature > 0 else -1.0
    ox, oy = _calc_origin(newx1, y1, newx2, newy2, origin)
    maxtheta = math.pi + _sign(origin * direction) * 2 * math.atan(abs(origin))
    points: list[tuple[float, float]] = []
    sinnb, cosnb = math.sin(-beta), math.cos(-beta)
    for index in range(1, ncp + 1):
        angle_i = direction * maxtheta * index / (ncp + 1)
        costheta, sintheta = math.cos(angle_i), math.sin(angle_i)
        cpx = ox + (newx1 - ox) * costheta - (y1 - oy) * sintheta
        cpy = oy + (y1 - oy) * costheta + (newx1 - ox) * sintheta
        cpx = _div(cpx, scalex)
        points.append(
            (
                x1 + (cpx - x1) * cosnb - (cpy - y1) * sinnb,
                y1 + (cpy - y1) * cosnb + (cpx - x1) * sinnb,
            )
        )
    return points


def _calc_square_control_points(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    curvature: float,
    angle: float,
    ncp: int,
) -> tuple[list[tuple[float, float]], bool]:
    dx, dy = x2 - x1, y2 - y1
    slope = _slope(dx, dy)
    end = slope > 1 or (slope < 0 and slope > -1)
    if curvature < 0:
        end = not end
    if end:
        startx, starty = x1, y1
        endx = x1 + dx if abs(slope) > 1 else x1 + _sign(slope) * dy
        endy = y1 + _sign(slope) * dx if abs(slope) > 1 else y1 + dy
    else:
        startx = x2 - dx if abs(slope) > 1 else x2 - _sign(slope) * dy
        starty = y2 - _sign(slope) * dx if abs(slope) > 1 else y2 - dy
        endx, endy = x2, y2
    inner = _calc_control_points(startx, starty, endx, endy, curvature, angle, ncp)
    # `interleave()`：e 为真时控制点在前、端点在最后，否则起点在前。
    if end:
        return [*inner, (endx, endy)], end
    return [(startx, starty), *inner], end


def _interleave_shapes(ncp: int, value: float, square: float, end: bool) -> list[float]:
    filler = [value] * ncp
    return [*filler, square] if end else [square, *filler]


def curve_points(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    curvature: float = 1.0,
    angle: float = 90.0,
    ncp: int = 1,
    shape: float = 0.5,
    square: bool = True,
    square_shape: float = 1.0,
    inflect: bool = False,
    open: bool = True,
    page: tuple[float, float] = (612.0, 792.0),
) -> np.ndarray:
    """一条 `grid.curve` → 折线（pt）。"""
    if x1 == x2 and y1 == y2:
        raise ValueError("curve 的两端不能重合")
    if curvature == 0 or angle < 1 or angle > 179:
        return np.asarray([(x1, y1), (x2, y2)], dtype=np.float64)
    if square and (x1 == x2 or y1 == y2):
        return np.asarray([(x1, y1), (x2, y2)], dtype=np.float64)

    if inflect:
        xm, ym = (x1 + x2) / 2, (y1 + y2) / 2
        shape1 = [shape] * ncp
        shape2 = [shape] * ncp
        if square:
            first, end1 = _calc_square_control_points(x1, y1, xm, ym, curvature, angle, ncp)
            second, end2 = _calc_square_control_points(xm, ym, x2, y2, -curvature, angle, ncp)
            shape1 = _interleave_shapes(ncp, shape, square_shape, end1)
            shape2 = _interleave_shapes(ncp, shape, square_shape, end2)
        else:
            first = _calc_control_points(x1, y1, xm, ym, curvature, angle, ncp)
            second = _calc_control_points(xm, ym, x2, y2, -curvature, angle, ncp)
        control = [(x1, y1), *first, (xm, ym), *second, (x2, y2)]
        shapes = [0.0, *shape1, 0.0, *shape2, 0.0]
    else:
        if square:
            inner, end = _calc_square_control_points(x1, y1, x2, y2, curvature, angle, ncp)
            shapes = [0.0, *_interleave_shapes(ncp, shape, square_shape, end), 0.0]
        else:
            inner = _calc_control_points(x1, y1, x2, y2, curvature, angle, ncp)
            shapes = [0.0, *([shape] * ncp), 0.0]
        control = [(x1, y1), *inner, (x2, y2)]

    return xspline_points(control, shapes, open=open, rep_ends=True, page=page)

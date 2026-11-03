"""等值线 / 等值带：`contour_breaks()` 与 isoband 口径的 `isolines` / `isobands`。

上游 `stat_contour()` / `stat_contour_filled()` 的两段计算：

1. `contour_breaks(z_range, bins, binwidth, breaks)` 决定层级（`bins` / `binwidth`
   走 `scales::fullseq()`；都没给时走 R 的 `pretty(z_range, 10)`）；
2. `isoband::isolines()` / `isoband::isobands()` 在规则网格上做 marching squares。

本模块的层级推导逐行复刻 R（含 `pretty.c` 的 `R_pretty()` 移植），几何用
contourpy（M2 排期定的实现）。两者的顶点拓扑**不保证**与 isoband 相同
（鞍点单元、闭合环的拆分与方向都可能不同），所以对拍口径是「层级边界数值
一致 + 几何自洽」（见 `docs/notes/stat.md` §9）；不逐行比顶点。

`contourpy` 是 `ggcore` 唯一新增的第三方依赖，X1 白名单与 Pyodide 可用性
记录在 `docs/notes/gates.md`。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import contourpy
import numpy as np

from ggcore.build import BuildError

__all__ = [
    "contour_breaks",
    "contour_deduplicate",
    "estimate_contour_angle",
    "iso_band_labels",
    "isobands",
    "isolines",
    "pretty",
    "rescale_max",
    "rotate_xy",
    "zero_range",
]

_EPS = 1e-10
_DBL_EPS = float(np.finfo(np.float64).eps)
_DBL_MIN = float(np.finfo(np.float64).tiny)
_DBL_MAX = float(np.finfo(np.float64).max)


# ---------------------------------------------------------------------------
# R 的 pretty()
# ---------------------------------------------------------------------------


def pretty(lo: float, up: float, n: int = 5) -> np.ndarray:
    """`base::pretty(range(lo, up), n)`（移植 R 4.5 的 `src/appl/pretty.c`）。

    `min.n = n %/% 3`；`shrink.sml = 0.75`；`high.u.bias = 1.5`、
    `u5.bias = 0.5 + 1.5 * high.u.bias`、`f.min = 2^-20`（`pretty.default()` 的
    缺省）。结果与 R 逐项相等（`tests/test_stat_2d_r_parity.py` 用夹具钉住）。
    """
    if lo > up:
        lo, up = up, lo
    ndiv = int(n)
    min_n = int(n) // 3
    h = 1.5
    h5 = 0.5 + 1.5 * h
    f_min = 2.0**-20
    shrink_sml = 0.75

    lo_ = float(lo)
    up_ = float(up)
    dx = up_ - lo_
    if dx == 0 and up_ == 0:
        cell = 1.0
        small = True
    else:
        cell = max(abs(lo_), abs(up_))
        upper = 1.0 + (1.0 / (1.0 + h) if h5 >= 1.5 * h + 0.5 else 1.5 / (1.0 + h5))
        upper *= max(1, ndiv) * _DBL_EPS
        small = dx < cell * upper * 3.0

    if small:
        if cell > 10:
            cell = 9 + cell / 10
        cell *= shrink_sml
        if min_n > 1:
            cell /= min_n
    else:
        cell = dx
        if math.isfinite(dx):
            if ndiv > 1:
                cell /= ndiv
        elif ndiv < 2:
            raise BuildError("pretty(): 范围溢出（Inf），ndiv 需要 >= 2")
        else:
            cell = up_ / ndiv - lo_ / ndiv

    subsmall = f_min * _DBL_MIN
    if cell < subsmall:
        cell = subsmall
    elif cell > _DBL_MAX / 1.25:
        cell = _DBL_MAX / 1.25

    base = 10.0 ** math.floor(math.log10(cell))
    unit = base
    candidate = 2 * base
    if candidate - cell < h * (cell - unit):
        unit = candidate
        candidate = 5 * base
        if candidate - cell < h5 * (cell - unit):
            unit = candidate
            candidate = 10 * base
            if candidate - cell < h * (cell - unit):
                unit = candidate

    ns = math.floor(lo_ / unit + _EPS)
    nu = math.ceil(up_ / unit - _EPS)
    while ns * unit > lo_ + _EPS * unit:
        ns -= 1
    while not math.isfinite(ns * unit):
        ns += 1
    while nu * unit < up_ - _EPS * unit:
        nu += 1
    while not math.isfinite(nu * unit):
        nu -= 1

    k = int(0.5 + nu - ns)
    if k < min_n:
        k = min_n - k
        if lo_ == 0.0 and ns == 0 and up_ != 0:
            nu += k
        elif up_ == 0.0 and nu == 0 and lo_ != 0:
            ns -= k
        elif ns >= 0:
            nu += k // 2
            ns -= k // 2 + k % 2
        else:
            ns -= k // 2
            nu += k // 2 + k % 2

    return np.array([unit * (ns + index) for index in range(round(nu - ns) + 1)])


def zero_range(values: Sequence[float]) -> bool:
    """`zero_range()`：首尾相等（长度为 0 / 1 也算）。"""
    array = np.asarray(values, dtype=np.float64).ravel()
    if array.size <= 1:
        return True
    return bool(array[0] == array[-1])


def _r_seq(start: float, stop: float, by: float) -> np.ndarray:
    """R 的 `seq(from, to, by)`（`n = floor((to - from)/by + 1e-10)`）。"""
    if by == 0:
        raise BuildError("fullseq 的步长不能是 0")
    if (stop - start) / by < 0:
        return np.array([start], dtype=np.float64)
    count = math.floor((stop - start) / by + 1e-10)
    return start + np.arange(count + 1, dtype=np.float64) * by


def _round_any(value: float, accuracy: float, *, up: bool) -> float:
    scaled = value / accuracy
    return (math.ceil(scaled) if up else math.floor(scaled)) * accuracy


def fullseq(lo: float, up: float, size: float) -> np.ndarray:
    """`scales::fullseq()`（`pad = FALSE`）。"""
    low, high = (lo, up) if lo <= up else (up, lo)
    if zero_range([low, high]):
        return np.array([low - size / 2.0, high + size / 2.0])
    if size <= 0:
        return np.array([low, high])
    return _r_seq(
        _round_any(low, size, up=False),
        _round_any(high, size, up=True),
        size,
    )


def _signif(value: float, digits: int) -> float:
    """`signif(x, digits)`：按有效数字四舍六入五成双（R 的 round）。"""
    if not math.isfinite(value) or value == 0:
        return value
    exponent = math.floor(math.log10(abs(value)))
    return round(value, digits - 1 - exponent)


def contour_breaks(
    z_range: Sequence[float],
    *,
    bins: int | None = None,
    binwidth: float | None = None,
    breaks: Any = None,
) -> np.ndarray:
    """`contour_breaks()`：层级边界（与 R 逐值一致）。"""
    if breaks is not None:
        if callable(breaks):
            raise BuildError("stat_contour 的 breaks 只支持显式数值序列（函数归后续任务）")
        values = np.asarray(breaks, dtype=np.float64).ravel()
        if values.size == 0:
            raise BuildError("stat_contour 的 breaks 不能为空")
        return values
    low, high = float(z_range[0]), float(z_range[1])
    if bins is None and binwidth is None:
        return pretty(low, high, 10)
    if bins is not None:
        bins = int(bins)
        if bins < 1:
            raise BuildError(f"stat_contour 的 bins 至少是 1，收到 {bins!r}")
        accuracy = _signif(high - low, 1) / 10.0
        if accuracy == 0:
            accuracy = 1.0
        low = math.floor(low / accuracy) * accuracy
        high = math.ceil(high / accuracy) * accuracy
        if bins == 1:
            return np.array([low, high], dtype=np.float64)
        width = (high - low) / (bins - 1)
        values = fullseq(low, high, width)
        if values.size < bins + 1:
            width = (high - low) / bins
            values = fullseq(low, high, width)
        return values
    width = float(binwidth)
    if width <= 0 or not math.isfinite(width):
        raise BuildError(f"stat_contour 的 binwidth 必须是正有限数，收到 {binwidth!r}")
    return fullseq(low, high, width)


# ---------------------------------------------------------------------------
# 网格 / 旋转 / 去重
# ---------------------------------------------------------------------------


def _grid(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """`isoband_z_matrix()`：散点 → 规则网格（缺失单元是 NaN）。"""
    xs = np.unique(x[~np.isnan(x)])
    ys = np.unique(y[~np.isnan(y)])
    if xs.size < 2 or ys.size < 2:
        raise BuildError("stat_contour 至少需要 2×2 的网格（x / y 各至少 2 个不同值）")
    x_pos = np.searchsorted(xs, x)
    y_pos = np.searchsorted(ys, y)
    raster = np.full((ys.size, xs.size), np.nan, dtype=np.float64)
    raster[y_pos, x_pos] = z
    return xs, ys, raster


def _generator(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> Any:
    xs, ys, raster = _grid(x, y, z)
    masked = np.ma.masked_invalid(raster)
    # isoband 与 contourpy 的差异：`corner_mask=False` 让「四个角里有一个是
    # NA」的单元整块不算，与 isoband 的「缺失网格点不参与等值」一致。
    return contourpy.contour_generator(x=xs, y=ys, z=masked, name="serial", corner_mask=False)


def isolines(
    x: np.ndarray, y: np.ndarray, z: np.ndarray, levels: Sequence[float]
) -> list[list[np.ndarray]]:
    """`isoband::isolines()`：逐层级返回折线（每条 `(N, 2)` 数组）。"""
    generator = _generator(x, y, z)
    return [list(generator.lines(float(level))) for level in levels]


def isobands(
    x: np.ndarray, y: np.ndarray, z: np.ndarray, breaks: Sequence[float]
) -> list[list[list[np.ndarray]]]:
    """`isoband::isobands()`：逐区间返回多边形（每个多边形是若干闭合环）。

    contourpy 的 `fill_type = OuterOffset` 每个多边形给出「外环 + 洞」的环偏移，
    与 isoband 的 `id` 分组对应（洞与外环同属一个多边形）。
    """
    generator = _generator(x, y, z)
    bands: list[list[list[np.ndarray]]] = []
    values = np.asarray(breaks, dtype=np.float64)
    for index in range(values.size - 1):
        points, offsets = generator.filled(float(values[index]), float(values[index + 1]))
        polygons: list[list[np.ndarray]] = []
        for block, offset in zip(points, offsets, strict=True):
            rings = [
                np.asarray(block[int(offset[i]) : int(offset[i + 1])], dtype=np.float64)
                for i in range(len(offset) - 1)
            ]
            polygons.append(rings)
        bands.append(polygons)
    return bands


def iso_band_labels(breaks: Sequence[float], dig_lab: int = 3) -> list[str]:
    """`pretty_isoband_levels()`：`"(low, high]"` 标签（dig.lab 自动加宽）。"""
    values = np.asarray(breaks, dtype=np.float64)
    if values.size < 2:
        return []
    digits = int(dig_lab)
    texts = _format_vector(values, digits)
    while len(set(texts)) < values.size:
        digits += 1
        texts = _format_vector(values, digits)
    return [f"({texts[i]}, {texts[i + 1]}]" for i in range(values.size - 1)]


def _format_vector(values: np.ndarray, digits: int) -> list[str]:
    """R 的 `format(x, digits = digits, trim = TRUE)`（对整条向量取公共小数位）。

    R 的 `format` 先按有效数字给每个值找最短写法（末尾的 0 不算），再给整条向量
    补齐到最多的小数位：`c(0, 0.005)` → `"0.000", "0.005"`；`c(0, 1.6667)` →
    `"0.00", "1.67"`。`dig.lab` 的去重循环依赖这个口径。
    """
    numbers = [float(value) for value in np.asarray(values, dtype=np.float64).tolist()]
    texts: list[str] = []
    decimals: list[int] = []
    for number in numbers:
        if not math.isfinite(number):
            texts.append("NA")
            decimals.append(0)
            continue
        text = f"{number:.{digits}g}"
        if "e" in text or "E" in text:
            text = f"{number:.{max(0, digits - 1)}f}".rstrip("0").rstrip(".")
        fraction = text.split(".")[1] if "." in text else ""
        decimals.append(len(fraction))
        texts.append(text)
    width = max(decimals) if decimals else 0
    return [
        "NA" if not math.isfinite(number) else f"{float(text):.{width}f}"
        for number, text in zip(numbers, texts, strict=True)
    ]


def rescale_max(values: np.ndarray) -> np.ndarray:
    """`scales::rescale_max()`：`x / max(x)`。"""
    array = np.asarray(values, dtype=np.float64)
    if array.size == 0:
        return array
    maximum = float(np.max(array))
    if maximum == 0 or not math.isfinite(maximum):
        return np.full(array.shape, np.nan)
    return array / maximum


def contour_deduplicate(
    x: np.ndarray, y: np.ndarray, z: np.ndarray, groups: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
    """`contour_deduplicate()`：同一 `(x, y, group)` 保留**最后**一行。

    返回 `(x, y, z, groups, dropped)`；`dropped` 是删掉的行数（调用方负责发
    与 R 同文案的警告）。
    """
    keys: dict[tuple[float, float, Any], int] = {}
    for row in range(x.size):
        keys[(float(x[row]), float(y[row]), groups[row])] = row
    keep = np.array(sorted(keys.values()), dtype=np.int64)
    dropped = int(x.size - keep.size)
    return x[keep], y[keep], z[keep], groups[keep], dropped


def estimate_contour_angle(x: np.ndarray, y: np.ndarray) -> float:
    """`estimate_contour_angle()`：先看前 20 个点的差分方向，再退回凸包最长边。"""
    head = min(int(x.size), 20)
    if head < 2:
        return 0.0
    angles = np.arctan2(np.diff(y[:head]), np.diff(x[:head]))
    unique, counts = np.unique(angles, return_counts=True)
    index = int(np.argmax(counts))
    if float(counts[index]) / float(counts.sum()) < 0.5:
        hull = _convex_hull(x, y)
        if hull.size < 2:
            return 0.0
        hull = np.concatenate([hull, hull[:1]])
        dx = np.diff(x[hull])
        dy = np.diff(y[hull])
        largest = int(np.argmax(np.hypot(dx, dy)))
        angle = float(np.arctan2(dy[largest], dx[largest]))
    else:
        angle = float(unique[index])
    straight = np.abs(angle - np.array([-1.0, -0.5, 0.0, 0.5, 1.0]) * math.pi) < math.sqrt(_DBL_EPS)
    if bool(np.any(straight)):
        return 0.0
    return angle


def _convex_hull(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """凸包（Andrew monotone chain）；只用来取「最长边」的方向。"""
    points = sorted(set(zip(x.tolist(), y.tolist(), strict=True)))
    if len(points) < 3:
        return np.arange(len(points), dtype=np.int64)

    def cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for point in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    hull = lower[:-1] + upper[:-1]
    lookup = {point: index for index, point in enumerate(points)}
    return np.array([lookup[point] for point in hull], dtype=np.int64)


def rotate_xy(x: np.ndarray, y: np.ndarray, angle: float) -> tuple[np.ndarray, np.ndarray]:
    """`rotate_xy()`：绕原点旋转；`angle == 0` 时原样返回。"""
    if angle == 0:
        return x, y
    cosine = math.cos(angle)
    sine = math.sin(angle)
    rotated_x = cosine * x - sine * y
    rotated_y = sine * x + cosine * y
    return _zapsmall(rotated_x, 13), _zapsmall(rotated_y, 13)


def _zapsmall(values: np.ndarray, digits: int) -> np.ndarray:
    """`zapsmall(x, digits)`：绝对值小于 `10^-digits * max|x|` 的置 0。"""
    array = np.asarray(values, dtype=np.float64)
    if array.size == 0:
        return array
    threshold = 10.0 ** (-digits) * float(np.max(np.abs(array)))
    return np.where(np.abs(array) < threshold, 0.0, array)

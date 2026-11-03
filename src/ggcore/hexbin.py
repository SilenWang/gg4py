"""六边形分箱：`hexbin::hexbin()` 与 ggplot2 `hexBinSummarise()` 的 numpy 复刻。

`stat_bin_hex` / `stat_summary_hex` 的单元格编号、单元格中心与输出顺序由
hexbin 包的 Fortran `hbin.f` 决定（`docs/notes/stat.md` §9）。这份实现逐行对应
那段 Fortran：

- 坐标先按 `(x - xmin) * xbins / xr`、`(y - ymin) * xbins * shape / (yr * √3)`
  缩放到「单元格单位」，再按到最近两个候选中心的平方距离（y 方向乘 3）判定；
- 单元格编号 `L = i * 2 * jmax + j + 1`（1 起，从左到右、从下到上），压缩后
  按 L 升序输出；
- 中心仍由 `hcell2xy()` 从编号反算（不用逐点均值），所以与 hexbin 的
  `xcm/ycm` 只差浮点累加顺序。

不引 hexbin / matplotlib；`stat_bin_hex` 的 `binwidth` 缺省值来自
`hex_binwidth(bins, scales)`，见 `ggcore.stat2d`。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

from ggcore.build import BuildError

__all__ = ["hex_binwidth", "hex_bounds", "hexbin", "hexbin_summarise"]

_SQRT3 = math.sqrt(3.0)


def hex_binwidth(bins: int, x_range: Sequence[float], y_range: Sequence[float]) -> np.ndarray:
    """`hex_binwidth(bins, scales)`：`diff(scale$dimension()) / bins`（逐轴）。"""
    if int(bins) != bins or int(bins) < 1:
        raise BuildError(f"stat_bin_hex 的 bins 必须是正整数，收到 {bins!r}")
    return np.array(
        [
            (float(x_range[1]) - float(x_range[0])) / bins,
            (float(y_range[1]) - float(y_range[0])) / bins,
        ],
        dtype=np.float64,
    )


def _round_any(value: float, accuracy: float, *, up: bool) -> float:
    """`round_any(x, accuracy, floor|ceiling)`。"""
    scaled = value / accuracy
    return (math.ceil(scaled) if up else math.floor(scaled)) * accuracy


def hex_bounds(values: np.ndarray, binwidth: float) -> tuple[float, float]:
    """`hex_bounds()`：向下 / 向上取整到 binwidth 的倍数，再各留 1e-6 余量。"""
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[~np.isnan(finite)]
    if finite.size == 0:
        raise BuildError("六边形分箱需要非空的 x / y")
    return (
        _round_any(float(np.min(finite)), binwidth, up=False) - 1e-6,
        _round_any(float(np.max(finite)), binwidth, up=True) + 1e-6,
    )


def _fortran_int(value: np.ndarray) -> np.ndarray:
    """Fortran 的 `int()`：向零截断。"""
    return np.trunc(value)


def hexbin(
    x: np.ndarray,
    y: np.ndarray,
    *,
    binwidth: np.ndarray,
    xbnds: tuple[float, float],
    ybnds: tuple[float, float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """`hexbin::hexbin()` 的编号部分：返回 `(cell, xcm, ycm, cell_id)`。

    `cell` 是非空单元格编号（升序，1 起），`cell_id` 是逐观测的编号（与 `cell`
    同一编号空间），`xcm/ycm` 是 `hcell2xy()` 反算出来的中心。
    """
    x_values = np.asarray(x, dtype=np.float64)
    y_values = np.asarray(y, dtype=np.float64)
    if x_values.size != y_values.size:
        raise BuildError("六边形分箱的 x / y 长度必须一致")
    xbins = (xbnds[1] - xbnds[0]) / float(binwidth[0])
    ybins = (ybnds[1] - ybnds[0]) / float(binwidth[1])
    if not all(math.isfinite(v) and v > 0 for v in (xbins, ybins)):
        raise BuildError("六边形分箱的 binwidth 必须为正有限数")
    shape = ybins / xbins
    jmax = math.floor(xbins + 1.5001)
    c1 = 2 * math.floor((xbins * shape) / _SQRT3 + 1.5001)
    imax = int((jmax * c1 - 1) / jmax + 1) if jmax else 0
    if jmax < 1 or imax < 1:
        raise BuildError(f"六边形分箱的网格退化（xbins={xbins!r}, ybins={ybins!r}）")

    xmin, ymin = xbnds[0], ybnds[0]
    xr = xbnds[1] - xmin
    yr = ybnds[1] - ymin
    c1 = xbins / xr
    c2 = xbins * shape / (yr * _SQRT3)
    jinc = jmax
    lat = jinc + 1
    iinc = 2 * jinc

    sx = c1 * (x_values - xmin)
    sy = c2 * (y_values - ymin)
    j1 = _fortran_int(sx + 0.5)
    i1 = _fortran_int(sy + 0.5)
    distance = (sx - j1) ** 2 + 3.0 * (sy - i1) ** 2
    j2 = _fortran_int(sx)
    i2 = _fortran_int(sy)
    alternate = (sx - j2 - 0.5) ** 2 + 3.0 * (sy - i2 - 0.5) ** 2

    # Fortran 的 if / elseif / else：先看 dist1 < 0.25，再看 > 1/3，否则比两个候选。
    cells = np.where(
        distance < 0.25,
        i1 * iinc + j1 + 1,
        np.where(
            distance > 1.0 / 3.0,
            i2 * iinc + j2 + lat,
            np.where(distance <= alternate, i1 * iinc + j1 + 1, i2 * iinc + j2 + lat),
        ),
    ).astype(np.int64)

    unique = np.unique(cells)
    # hcell2xy()：编号 → 中心。
    index = unique - 1
    i = index // jmax
    j = index % jmax
    c3 = (xbnds[1] - xbnds[0]) / xbins
    c4 = ((ybnds[1] - ybnds[0]) * _SQRT3) / (2 * shape * xbins)
    centre_y = c4 * i + ybnds[0]
    centre_x = c3 * np.where(i % 2 == 0, j, j + 0.5) + xbnds[0]
    return unique, centre_x, centre_y, cells


def hexbin_summarise(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    *,
    binwidth: Any,
    fun: str | Callable[[np.ndarray], float] = "mean",
    fun_args: dict[str, Any] | None = None,
    drop: bool = True,
) -> list[tuple[str, np.ndarray]]:
    """`hexBinSummarise()`：返回 `x, y, value, width, height` 五列。

    输出顺序照 hexbin 的压缩顺序（单元格编号升序）；`drop = TRUE` 时删掉
    `fun` 返回 NA 的单元格（上游 `na.omit(out)`）。
    """
    widths = np.asarray(binwidth, dtype=np.float64)
    if widths.ndim == 0:
        widths = np.array([float(widths), float(widths)])
    if widths.size != 2 or np.any(~np.isfinite(widths)) or np.any(widths <= 0):
        raise BuildError(f"六边形分箱的 binwidth 必须是两个正有限数，收到 {binwidth!r}")
    xbnds = hex_bounds(x, float(widths[0]))
    ybnds = hex_bounds(y, float(widths[1]))
    cells, centre_x, centre_y, cell_id = hexbin(x, y, binwidth=widths, xbnds=xbnds, ybnds=ybnds)

    values = np.empty(cells.size, dtype=np.float64)
    position = {int(cell): index for index, cell in enumerate(cells.tolist())}
    grouped: dict[int, list[int]] = {}
    for row, cell in enumerate(cell_id.tolist()):
        grouped.setdefault(int(cell), []).append(row)
    summariser = _summariser(fun, fun_args or {})
    for index, cell in enumerate(cells.tolist()):
        rows = grouped.get(int(cell), [])
        block = np.asarray(z, dtype=np.float64)[rows]
        values[index] = summariser(block)
    del position

    keep = np.ones(cells.size, dtype=bool)
    if drop:
        keep = ~np.isnan(values)
    return [
        ("x", centre_x[keep]),
        ("y", centre_y[keep]),
        ("value", values[keep]),
        ("width", np.full(int(keep.sum()), float(widths[0]))),
        ("height", np.full(int(keep.sum()), float(widths[1]))),
    ]


def _summariser(
    fun: str | Callable[[np.ndarray], float], fun_args: dict[str, Any]
) -> Callable[[np.ndarray], float]:
    """把 `fun`（名字或 Python 可调用）统一成 `ndarray -> float`。"""
    if callable(fun):
        return lambda block: float(fun(block, **fun_args))
    name = str(fun)
    if name == "mean":
        return lambda block: (
            float(np.mean(block))
            if fun_args.get("trim") is None
            else float(_trimmed_mean(block, float(fun_args["trim"])))
        )
    if name == "sum":
        return lambda block: float(np.sum(block))
    if name == "median":
        return lambda block: float(np.median(block))
    if name == "min":
        return lambda block: float(np.min(block))
    if name == "max":
        return lambda block: float(np.max(block))
    raise BuildError(
        f"stat_summary_hex 的 fun = {fun!r} 尚未实现；"
        "可用：mean / sum / median / min / max（或传 Python 可调用对象）"
    )


def _trimmed_mean(values: np.ndarray, trim: float) -> float:
    """R `mean(x, trim = t)`：两端各去掉 `floor(n*t)` 个观测。"""
    finite = np.sort(values[~np.isnan(values)])
    if finite.size == 0:
        return float("nan")
    cut = math.floor(finite.size * trim)
    if cut == 0:
        return float(np.mean(finite))
    kept = finite[cut : finite.size - cut]
    return float(np.mean(kept)) if kept.size else float("nan")

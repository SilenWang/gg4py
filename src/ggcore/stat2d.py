"""`ggcore.stat2d` —— 2D 统计（M2-6）：bin_2d / bin_hex / summary_2d / summary_hex /
contour / contour_filled / density_2d / density_2d_filled。

口径照 ggplot2 4.0.3 的 `R/stat-*.R`（pin cc1444c1），逐列对拍见
`tests/test_stat_2d_r_parity.py`，说明见 `docs/notes/stat.md` §9。

与 `ggcore.stat` 的分工：

- 公共流程（`remove_missing()`、`Stat$compute_panel()` 的分组与恒定列）在
  `ggcore.stat`，这里只实现每族的 `compute_group()`；
- 数值内核在 `ggcore.kde2d` / `ggcore.hexbin` / `ggcore.contour`。`ggcore.contour`
  是**惰性导入**的：只有 contour 族与 `density_2d*` 的 contour 分支需要它（它按需
  加载 contourpy），所以 `bin_2d` / `bin_hex` / `summary_2d` / `summary_hex` 在缺
  contourpy 的运行时照样可用（SIL-758）。

两个容易踩的上游细节：

1. `stat_bin_2d` 的 `boundary` 缺省是 `list(x = 0, y = 0)`（4.0.3 的向后兼容），
   不是 `stat_bin()` 的 `width / 2`；
2. `stat_density_2d` 是**两段式**：先算密度网格，再把网格整张丢给
   `StatContour` / `StatContourFilled` 的 `compute_panel()`（链式调用不经过
   `map_statistic()`，所以密度族的 `order` 列不会出现）。
"""

from __future__ import annotations

import math
import warnings as _warnings
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np

from ggcore.build import BuildError, BuildWarning, _column_values
from ggcore.data import Column, ColumnTable
from ggcore.hexbin import hex_binwidth, hexbin_summarise
from ggcore.kde2d import kde2d, precompute_2d_bw
from ggcore.stat import (
    _EMPTY,
    _compute_bins,
    _compute_panel,
    _dimension,
    _float_column,
    _numeric,
)

__all__ = ["TWO_D_STATS", "compute_2d"]


def _contour_module() -> Any:
    """惰性导入 :mod:`ggcore.contour`（它按需加载 contourpy，SIL-758）。

    只有 `contour` / `contour_filled` 与 `density_2d*` 的 contour 分支需要
    contourpy；`bin_2d` / `bin_hex` / `summary_2d` / `summary_hex` 在浏览器里
    缺这个包时仍须可用，所以这些名字不能放模块顶层。
    """
    from ggcore import contour

    return contour


#: 本模块实现的 stat 名（与 `ggcore.stat._TWO_D_STATS` 同一份清单）。
TWO_D_STATS: tuple[str, ...] = (
    "bin_2d",
    "bin_hex",
    "summary_2d",
    "summary_hex",
    "contour",
    "contour_filled",
    "density_2d",
    "density_2d_filled",
)


def compute_2d(
    name: str,
    table: ColumnTable,
    params: Mapping[str, Any],
    *,
    scales: Any = None,
) -> ColumnTable:
    """2D 族的派发入口（`ggcore.stat.compute_stat()` 调用）。"""
    if name == "bin_2d":
        return _stat_bin_2d(table, params, scales=scales)
    if name == "bin_hex":
        return _stat_bin_hex(table, params, scales=scales)
    if name == "summary_2d":
        return _stat_summary_2d(table, params, scales=scales)
    if name == "summary_hex":
        return _stat_summary_hex(table, params, scales=scales)
    if name in ("contour", "contour_filled"):
        return _stat_contour(table, params, filled=name == "contour_filled")
    if name in ("density_2d", "density_2d_filled"):
        return _stat_density_2d(table, params, scales=scales, filled=name.endswith("_filled"))
    raise BuildError(f"stat {name!r} 不是 2D 统计")


# ---------------------------------------------------------------------------
# 列工具
# ---------------------------------------------------------------------------


def _int_column(values: Sequence[float] | np.ndarray) -> Column:
    array = np.asarray(values, dtype=np.float64)
    missing = np.isnan(array)
    if missing.any():
        return Column("int", np.where(missing, 0.0, array), na_mask=missing)
    return Column("int", array)


def _auto_numeric_column(values: Sequence[float] | np.ndarray) -> Column:
    """整数值 → `int` 列（R 的 `sum(integer)` 仍是 integer），否则 `float`。"""
    array = np.asarray(values, dtype=np.float64)
    finite = array[np.isfinite(array)]
    if finite.size and np.all(finite == np.round(finite)):
        return _int_column(array)
    return _float_column(array)


def _strid_column(values: Sequence[str], levels: Sequence[str] | None = None) -> Column:
    texts = [str(item) for item in values]
    return Column(
        "str",
        np.array(texts, dtype=object),
        levels=tuple(levels) if levels is not None else tuple(sorted(set(texts))),
    )


def _factor_codes(labels: Sequence[str]) -> tuple[np.ndarray, tuple[str, ...]]:
    """`factor(labels)` → (1 起的整数编码, levels)。

    R 的 `factor()` 水平按字典序；`iso_to_geom()` 的 `piece` 就是这个编码。
    """
    levels = tuple(sorted(set(labels)))
    mapping = {label: index + 1 for index, label in enumerate(levels)}
    return np.array([mapping[label] for label in labels], dtype=np.float64), levels


def _group_label(value: Any) -> str:
    """R 的 `paste()` 对数值组号的写法（`-1` 不写 `.0`）。"""
    if isinstance(value, (bool, np.bool_)):
        return "TRUE" if value else "FALSE"
    number = float(value)
    if math.isfinite(number) and number == int(number):
        return str(int(number))
    return str(value)


def _scalar(value: Any, name: str) -> Any:
    """`dual_param()` 之后的单轴取值：标量保持标量，序列原样。"""
    if value is None:
        return None
    if isinstance(value, (list, tuple, np.ndarray)):
        array = np.asarray(value)
        if array.ndim == 0:
            return array.item()
        if array.size == 1:
            return array.ravel()[0].item()
        return array
    return value


def _dual(value: Any, default: Any) -> dict[str, Any]:
    """`dual_param()`：标量 / 长度 2 的向量 / 命名 list → `{x, y}`。"""
    if value is None:
        return default
    if isinstance(value, Mapping):
        return {"x": value.get("x"), "y": value.get("y")}
    if isinstance(value, str):
        return {"x": value, "y": value}
    if isinstance(value, (list, tuple)) and len(value) == 2 and not isinstance(value, np.ndarray):
        # R 只对「有名字的 list」保留原样；无名字的长度 2 序列按 x / y 拆开。
        return {"x": value[0], "y": value[1]}
    array = np.asarray(value)
    if array.ndim == 0:
        return {"x": array.item(), "y": array.item()}
    flat = array.ravel()
    if flat.size == 2:
        return {"x": flat[0], "y": flat[1]}
    if flat.size == 1:
        return {"x": flat[0], "y": flat[0]}
    return {"x": array, "y": array}


def _setup_bin_params(params: Mapping[str, Any]) -> dict[str, Any]:
    """`StatSummary2d$setup_params()` + `fix_bin_params()`（bin_2d 也走这份）。"""
    values = dict(params)
    if isinstance(values.get("drop"), str):
        values["drop"] = values["drop"] != "none"
    if values.get("origin") is not None:
        # `fix_bin_params()`：origin 在 4.0.0 被 boundary 取代。
        values["boundary"] = values.pop("origin")
    if values.get("right") is not None:
        values["closed"] = "right" if values["right"] else "left"
        values.pop("right")
    if (
        values.get("breaks") is None
        and values.get("binwidth") is None
        and values.get("bins") is None
    ):
        values["bins"] = 30
    empty = {"x": None, "y": None}
    for key in ("origin", "binwidth", "breaks", "center", "boundary"):
        values[key] = _dual(values.get(key), empty)
    values["closed"] = _dual(values.get("closed"), {"x": "right", "y": "right"})
    # 两个 stat 的 `compute_group()` 形参缺省都是 `boundary = 0`（summary_2d 直接
    # 写在形参里，bin_2d 在 `boundary %||% if (is.null(center))` 里补），
    # `make_constructor()` 把它带进了 params。有 center 时不补（两者互斥）。
    if values["boundary"]["x"] is None and values["center"]["x"] is None:
        values["boundary"] = {"x": 0, "y": 0}
    return values


def _axis_bins(
    axis: str,
    values: np.ndarray,
    params: Mapping[str, Any],
    scales: Any,
    *,
    default_bins: int = 30,
):
    """单轴的 `compute_bins()`（`bins` 在 compute_group 里才 dual）。"""
    bins = _dual(params.get("bins"), {"x": default_bins, "y": default_bins})
    closed = params["closed"][axis]
    if closed not in ("right", "left"):
        raise BuildError(f"stat_bin_2d 的 closed 只能是 'right' / 'left'，收到 {closed!r}")
    return _compute_bins(
        breaks=_scalar(params["breaks"][axis], "breaks"),
        binwidth=_optional_number(_scalar(params["binwidth"][axis], "binwidth"), "binwidth"),
        bins=_optional_int(_scalar(bins[axis], "bins"), "bins"),
        center=_optional_number(_scalar(params["center"][axis], "center"), "center"),
        boundary=_optional_number(_scalar(params["boundary"][axis], "boundary"), "boundary"),
        closed=str(closed),
        x_range=_dimension(scales, axis, values),
    )


def _optional_number(value: Any, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)):
        raise BuildError(f"{name} 必须是数值，收到 {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise BuildError(f"{name} 必须是有限数，收到 {value!r}")
    return number


def _optional_int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number) or int(number) != number or number < 1:
        raise BuildError(f"{name} 必须是正整数，收到 {value!r}")
    return int(number)


def _resolve_fun(fun: Any, stat: str) -> Callable[[np.ndarray], float]:
    """上游 `as_function(fun)`：字符串名字 / Python 可调用对象。"""
    if callable(fun):
        return lambda block: float(fun(block))
    name = "mean" if fun is None else str(fun)
    table: dict[str, Callable[[np.ndarray], float]] = {
        "mean": lambda block: float(np.mean(block)) if block.size else float("nan"),
        "sum": lambda block: float(np.sum(block)) if block.size else 0.0,
        "median": lambda block: float(np.median(block)) if block.size else float("nan"),
        "min": lambda block: float(np.min(block)) if block.size else float("inf"),
        "max": lambda block: float(np.max(block)) if block.size else float("-inf"),
        "var": lambda block: float(np.var(block, ddof=1)) if block.size > 1 else float("nan"),
        "sd": lambda block: float(np.std(block, ddof=1)) if block.size > 1 else float("nan"),
    }
    try:
        return table[name]
    except KeyError:
        raise BuildError(
            f"{stat} 的 fun = {fun!r} 尚未实现；"
            f"可用：{', '.join(sorted(table))}（或传 Python 可调用对象）"
        ) from None


# ---------------------------------------------------------------------------
# summary_2d / bin_2d
# ---------------------------------------------------------------------------


def _summary_rows(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    *,
    xbins: Any,
    ybins: Any,
    fun: Callable[[np.ndarray], float],
    drop: bool,
) -> list[tuple[str, Column]] | None:
    """上游 `tapply_df()` + `bin_loc()`：`xbin, ybin, value, x, width, y, height`。"""
    x_index = xbins.cut(x)
    y_index = ybins.cut(y)
    valid = (x_index >= 0) & (y_index >= 0)
    if not valid.any():
        return None
    present_x = sorted({int(value) for value in x_index[valid].tolist()})
    present_y = sorted({int(value) for value in y_index[valid].tolist()})
    # `expand.grid()`：第一个因子（xbin）变化最快。
    rows: list[tuple[int, int, float]] = []
    for y_bin in present_y:
        for x_bin in present_x:
            selected = valid & (x_index == x_bin) & (y_index == y_bin)
            block = z[selected]
            if block.size == 0 and drop:
                continue
            rows.append((x_bin, y_bin, fun(block)))
    if not rows:
        return None
    x_bin_values = np.array([row[0] for row in rows], dtype=np.float64)
    y_bin_values = np.array([row[1] for row in rows], dtype=np.float64)
    values = np.array([row[2] for row in rows], dtype=np.float64)
    breaks_x = xbins.breaks
    breaks_y = ybins.breaks
    x_index = x_bin_values.astype(np.int64)
    y_index = y_bin_values.astype(np.int64)
    x_left = breaks_x[x_index]
    x_right = breaks_x[x_index + 1]
    y_left = breaks_y[y_index]
    y_right = breaks_y[y_index + 1]
    return [
        # R 的 `cut()` 是 1 起的因子编码；`_Bins.cut()` 给 0 起下标。
        ("xbin", _int_column(x_bin_values + 1.0)),
        ("ybin", _int_column(y_bin_values + 1.0)),
        ("value", _float_column(values)),
        ("x", _float_column((x_left + x_right) / 2.0)),
        ("width", _float_column(x_right - x_left)),
        ("y", _float_column((y_left + y_right) / 2.0)),
        ("height", _float_column(y_right - y_left)),
    ]


def _stat_summary_2d(table: ColumnTable, params: Mapping[str, Any], *, scales: Any) -> ColumnTable:
    """`stat_summary_2d`：矩形分箱 + `fun`（缺省 mean）。"""
    values = _setup_bin_params(params)
    fun = _resolve_fun(values.get("fun", "mean"), "stat_summary_2d")
    drop = bool(values.get("drop", True))
    x_values = _numeric(table.column("x"))
    y_values = _numeric(table.column("y"))
    xbins = _axis_bins("x", x_values, values, scales)
    ybins = _axis_bins("y", y_values, values, scales)

    def group_fn(sub: ColumnTable, rows: np.ndarray) -> list[tuple[str, Column]] | None:
        del rows
        return _summary_rows(
            _numeric(sub.column("x")),
            _numeric(sub.column("y")),
            _numeric(sub.column("z")),
            xbins=xbins,
            ybins=ybins,
            fun=fun,
            drop=drop,
        )

    return _compute_panel(table, group_fn, stat="summary_2d")


def _stat_bin_2d(table: ColumnTable, params: Mapping[str, Any], *, scales: Any) -> ColumnTable:
    """`stat_bin_2d`：`StatSummary2d(fun = sum)` + 四个归一化计数。"""
    values = _setup_bin_params(params)
    drop = bool(values.get("drop", True))
    x_values = _numeric(table.column("x"))
    y_values = _numeric(table.column("y"))
    weight = (
        np.asarray(_column_values(table.column("weight")), dtype=np.float64)
        if "weight" in table
        else np.ones(table.nrows, dtype=np.float64)
    )
    xbins = _axis_bins("x", x_values, values, scales)
    ybins = _axis_bins("y", y_values, values, scales)

    def group_fn(sub: ColumnTable, rows: np.ndarray) -> list[tuple[str, Column]] | None:
        z = (
            np.asarray(_column_values(sub.column("weight")), dtype=np.float64)
            if "weight" in sub
            else np.ones(sub.nrows, dtype=np.float64)
        )
        produced = _summary_rows(
            _numeric(sub.column("x")),
            _numeric(sub.column("y")),
            z,
            xbins=xbins,
            ybins=ybins,
            fun=lambda block: float(np.sum(block)) if block.size else 0.0,
            drop=drop,
        )
        if produced is None:
            return None
        count = np.asarray(_column_values(dict(produced)["value"]), dtype=np.float64)
        with np.errstate(invalid="ignore", divide="ignore"):
            maximum = float(np.nanmax(count)) if count.size else 0.0
            total = float(np.nansum(count))
            ncount = count / maximum if maximum else count * np.nan
            density = count / total if total else count * np.nan
            density_max = float(np.nanmax(density)) if density.size else 0.0
            ndensity = density / density_max if density_max else density * np.nan
        produced = [
            *produced,
            ("count", _float_column(count)),
            ("ncount", _float_column(ncount)),
            ("density", _float_column(density)),
            ("ndensity", _float_column(ndensity)),
        ]
        return produced

    del weight
    return _compute_panel(table, group_fn, stat="bin_2d")


# ---------------------------------------------------------------------------
# hex 族
# ---------------------------------------------------------------------------


def _hex_binwidth(params: Mapping[str, Any], scales: Any, table: ColumnTable) -> np.ndarray:
    binwidth = params.get("binwidth")
    if binwidth is not None:
        array = np.asarray(binwidth, dtype=np.float64).ravel()
        if array.size == 1:
            array = np.array([array[0], array[0]])
        return array
    bins = params.get("bins", 30)
    if isinstance(bins, (list, tuple, np.ndarray)):
        array = np.asarray(bins, dtype=np.float64).ravel()
        if array.size == 2 and array[0] == array[1]:
            bins = int(array[0])
        else:
            raise BuildError(f"stat_bin_hex 的 bins 只能是标量，收到 {bins!r}")
    return hex_binwidth(
        _optional_int(bins, "bins"),
        _dimension(scales, "x", _numeric(table.column("x"))),
        _dimension(scales, "y", _numeric(table.column("y"))),
    )


def _stat_bin_hex(table: ColumnTable, params: Mapping[str, Any], *, scales: Any) -> ColumnTable:
    """`stat_bin_hex`：六边形计数 + 四个归一化值。"""
    widths = _hex_binwidth(params, scales, table)
    drop = bool(params.get("drop", True))

    def group_fn(sub: ColumnTable, rows: np.ndarray) -> list[tuple[str, Column]] | None:
        del rows
        weight = (
            np.asarray(_column_values(sub.column("weight")), dtype=np.float64)
            if "weight" in sub
            else np.ones(sub.nrows, dtype=np.float64)
        )
        columns = dict(
            hexbin_summarise(
                _numeric(sub.column("x")),
                _numeric(sub.column("y")),
                weight,
                binwidth=widths,
                fun="sum",
                drop=drop,
            )
        )
        value = columns["value"]
        with np.errstate(invalid="ignore", divide="ignore"):
            total = float(np.sum(value))
            density = value / total if total else value * np.nan
            maximum = float(np.max(value)) if value.size else 0.0
            ncount = value / maximum if maximum else value * np.nan
            density_max = float(np.max(density)) if density.size else 0.0
            ndensity = density / density_max if density_max else density * np.nan
        return [
            ("x", _float_column(columns["x"])),
            ("y", _float_column(columns["y"])),
            ("width", _float_column(columns["width"])),
            ("height", _float_column(columns["height"])),
            ("density", _float_column(density)),
            ("ndensity", _float_column(ndensity)),
            ("count", _auto_numeric_column(value)),
            ("ncount", _float_column(ncount)),
        ]

    return _compute_panel(table, group_fn, stat="bin_hex")


def _stat_summary_hex(table: ColumnTable, params: Mapping[str, Any], *, scales: Any) -> ColumnTable:
    """`stat_summary_hex`：六边形分箱 + `fun`。"""
    widths = _hex_binwidth(params, scales, table)
    fun = _resolve_fun(params.get("fun", "mean"), "stat_summary_hex")
    fun_args = dict(params.get("fun.args") or params.get("fun_args") or {})
    drop = bool(params.get("drop", True))

    def group_fn(sub: ColumnTable, rows: np.ndarray) -> list[tuple[str, Column]] | None:
        del rows
        return [
            (name, _float_column(values))
            for name, values in hexbin_summarise(
                _numeric(sub.column("x")),
                _numeric(sub.column("y")),
                _numeric(sub.column("z")),
                binwidth=widths,
                fun=fun,
                fun_args=fun_args,
                drop=drop,
            )
        ]

    return _compute_panel(table, group_fn, stat="summary_hex")


# ---------------------------------------------------------------------------
# contour / contour_filled
# ---------------------------------------------------------------------------


def _stat_contour(table: ColumnTable, params: Mapping[str, Any], *, filled: bool) -> ColumnTable:
    """`stat_contour` / `stat_contour_filled`（上游 `StatContour[Filled]`）。"""
    contour = _contour_module()
    z_values = _numeric(table.column("z"))
    finite = z_values[np.isfinite(z_values)]
    if finite.size == 0:
        return _EMPTY
    z_range = (float(finite.min()), float(finite.max()))
    stat_name = "contour_filled" if filled else "contour"

    group_column = (
        np.asarray(_column_values(table.column("group")), dtype=np.float64)
        if "group" in table
        else np.full(table.nrows, -1.0)
    )
    x_values = _numeric(table.column("x"))
    y_values = _numeric(table.column("y"))
    kept_x, _kept_y, _kept_z, _kept_groups, dropped = contour.contour_deduplicate(
        x_values, y_values, z_values, group_column
    )
    if dropped:
        _warnings.warn(
            "Contour data has duplicated x, y coordinates. "
            f"{dropped} duplicated rows have been dropped.",
            BuildWarning,
            stacklevel=3,
        )

    columns = list(_items(table))
    if dropped:
        keep = _last_unique_rows(x_values, y_values, group_column)
        columns = [
            (name, Column(column.kind, column.values[keep], column.levels, column.na_mask[keep]))
            for name, column in columns
        ]
    working = ColumnTable(columns, nrows=kept_x.size)

    def group_fn(sub: ColumnTable, rows: np.ndarray) -> list[tuple[str, Column]] | None:
        del rows
        group_value = _group_label(_column_values(sub.column("group"))[0] if "group" in sub else -1)
        x = _numeric(sub.column("x"))
        y = _numeric(sub.column("y"))
        z = _numeric(sub.column("z"))
        rotation = contour.estimate_contour_angle(x, y)
        rotated_x, rotated_y = contour.rotate_xy(x, y, -rotation)
        breaks = contour.contour_breaks(
            z_range,
            bins=params.get("bins"),
            binwidth=params.get("binwidth"),
            breaks=params.get("breaks"),
        )
        if filled:
            produced = _filled_rows(rotated_x, rotated_y, z, breaks, group_value, rotation)
        else:
            produced = _line_rows(rotated_x, rotated_y, z, breaks, group_value, rotation)
        return produced

    result = _compute_panel(working, group_fn, stat=stat_name)
    if result.nrows == 0:
        _warnings.warn(
            f"stat_{stat_name}(): Zero contours were generated", BuildWarning, stacklevel=3
        )
    return result


def _last_unique_rows(x: np.ndarray, y: np.ndarray, groups: np.ndarray) -> np.ndarray:
    keys: dict[tuple[float, float, Any], int] = {}
    for row in range(x.size):
        keys[(float(x[row]), float(y[row]), groups[row])] = row
    return np.array(sorted(keys.values()), dtype=np.int64)


def _line_rows(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    breaks: np.ndarray,
    group_value: str,
    rotation: float,
) -> list[tuple[str, Column]] | None:
    """`iso_to_geom(..., geom = "path")`：`level, x, y, piece, group, nlevel`。"""
    contour = _contour_module()
    segments = contour.isolines(x, y, z, breaks.tolist())
    finite = z[np.isfinite(z)]
    zmin = float(finite.min()) if finite.size else float("nan")
    levels: list[float] = []
    xs: list[float] = []
    ys: list[float] = []
    labels: list[str] = []
    for level_index, level in enumerate(breaks.tolist(), start=1):
        # 等值线正好落在数据**最小值**上时退化成一个点，isoband 不给线；最大值那一档
        # isoband 会给一段退化线（R 的 `contour_default` 里 level = 6.5 就是两个
        # 重合点），所以只跳最小值。间隔编号（group 的 `-00N-`）仍按 breaks 下标走。
        if level == zmin:
            continue
        for piece_index, points in enumerate(segments[level_index - 1], start=1):
            array = np.asarray(points, dtype=np.float64)
            if array.size == 0:
                continue
            levels.extend([float(level)] * array.shape[0])
            xs.extend(array[:, 0].tolist())
            ys.extend(array[:, 1].tolist())
            labels.extend([f"{group_value}-{level_index:03d}-{piece_index:03d}"] * array.shape[0])
    if not levels:
        return None
    level_values = np.asarray(levels, dtype=np.float64)
    piece, levels_of_group = _factor_codes(labels)
    x_values, y_values = contour.rotate_xy(
        np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64), rotation
    )
    return [
        ("level", _float_column(level_values)),
        ("x", _float_column(x_values)),
        ("y", _float_column(y_values)),
        ("piece", _int_column(piece)),
        ("group", _strid_column(labels, levels_of_group)),
        ("nlevel", _float_column(contour.rescale_max(level_values))),
    ]


def _filled_rows(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    breaks: np.ndarray,
    group_value: str,
    rotation: float,
) -> list[tuple[str, Column]] | None:
    """`iso_to_geom(..., geom = "polygon")` 的填充版。"""
    contour = _contour_module()
    labels = contour.iso_band_labels(breaks.tolist())
    bands = contour.isobands(x, y, z, breaks.tolist())
    level_text: list[str] = []
    xs: list[float] = []
    ys: list[float] = []
    groups: list[str] = []
    subgroups: list[float] = []
    lows: list[float] = []
    highs: list[float] = []
    for band_index, polygons in enumerate(bands, start=1):
        for polygon_index, rings in enumerate(polygons, start=1):
            for ring in rings:
                array = np.asarray(ring, dtype=np.float64)
                if array.size == 0:
                    continue
                level_text.extend([labels[band_index - 1]] * array.shape[0])
                xs.extend(array[:, 0].tolist())
                ys.extend(array[:, 1].tolist())
                groups.extend([f"{group_value}-{band_index:03d}"] * array.shape[0])
                subgroups.extend([float(polygon_index)] * array.shape[0])
                lows.extend([float(breaks[band_index - 1])] * array.shape[0])
                highs.extend([float(breaks[band_index])] * array.shape[0])
    if not level_text:
        return None
    piece, group_levels = _factor_codes(groups)
    x_values, y_values = contour.rotate_xy(
        np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64), rotation
    )
    low_values = np.asarray(lows, dtype=np.float64)
    high_values = np.asarray(highs, dtype=np.float64)
    return [
        ("level", _strid_column(level_text, labels)),
        ("x", _float_column(x_values)),
        ("y", _float_column(y_values)),
        ("piece", _int_column(piece)),
        ("group", _strid_column(groups, group_levels)),
        ("subgroup", _int_column(np.asarray(subgroups, dtype=np.float64))),
        ("level_low", _float_column(low_values)),
        ("level_high", _float_column(high_values)),
        ("level_mid", _float_column(0.5 * (low_values + high_values))),
        ("nlevel", _float_column(contour.rescale_max(high_values))),
    ]


# ---------------------------------------------------------------------------
# density_2d / density_2d_filled
# ---------------------------------------------------------------------------


def _stat_density_2d(
    table: ColumnTable, params: Mapping[str, Any], *, scales: Any, filled: bool
) -> ColumnTable:
    """`stat_density_2d[ _filled]`：MASS::kde2d 网格 → 可选 contour 链。"""
    contour_var = params.get("contour_var") or "density"
    if contour_var not in ("density", "ndensity", "count"):
        raise BuildError(
            "stat_density_2d 的 contour_var 只能是 density / ndensity / count，"
            f"收到 {contour_var!r}"
        )
    contour = params.get("contour")
    contour = True if contour is None else bool(contour)
    n = _optional_int(params.get("n", 100), "n")
    h = params.get("h")
    adjust = params.get("adjust", 1.0)

    def group_fn(sub: ColumnTable, rows: np.ndarray) -> list[tuple[str, Column]] | None:
        del rows
        x = _numeric(sub.column("x"))
        y = _numeric(sub.column("y"))
        bandwidth = precompute_2d_bw(x, y, h=h, adjust=adjust)
        lims = [
            *_dimension(scales, "x", x),
            *_dimension(scales, "y", y),
        ]
        grid_x, grid_y, density = kde2d(x, y, bandwidth, n=n, lims=lims)
        # `as.vector(dens$z)`（列优先）+ `expand.grid(x = gx, y = gy)`：x 变化最快。
        flat = np.asarray(density).T.ravel()
        count = x.size * flat
        with np.errstate(invalid="ignore", divide="ignore"):
            maximum = float(np.max(flat)) if flat.size else 0.0
            ndensity = flat / maximum if maximum else flat * np.nan
        groups = np.full(
            flat.size, float(_column_values(sub.column("group"))[0]) if "group" in sub else -1.0
        )
        return [
            ("x", _float_column(np.tile(grid_x, grid_y.size))),
            ("y", _float_column(np.repeat(grid_y, grid_x.size))),
            ("density", _float_column(flat)),
            ("group", _int_column(groups)),
            ("ndensity", _float_column(ndensity)),
            ("count", _float_column(count)),
            ("n", _int_column(np.full(flat.size, float(x.size)))),
            ("level", _float_column(np.ones(flat.size))),
            ("piece", _float_column(np.ones(flat.size))),
        ]

    grid = _compute_panel(table, group_fn, stat="density_2d_filled" if filled else "density_2d")
    if grid.nrows == 0 or not contour:
        return grid

    z_values = np.asarray(_column_values(grid.column(contour_var)), dtype=np.float64)
    finite = z_values[np.isfinite(z_values)]
    if finite.size == 0:
        return _EMPTY
    z_range = (float(finite.min()), float(finite.max()))
    subset = {
        key: params.get(key)
        for key in ("bins", "binwidth", "breaks")
        if params.get(key) is not None
    }
    return _contour_panel_density(grid, subset, z_range, filled=filled, contour_var=contour_var)


def _contour_panel_density(
    grid: ColumnTable,
    params: Mapping[str, Any],
    z_range: tuple[float, float],
    *,
    filled: bool,
    contour_var: str,
) -> ColumnTable:
    """把密度网格整张送进 contour 的 `compute_panel()`（上游的链式调用）。"""
    stat_name = "contour_filled" if filled else "contour"
    contour = _contour_module()
    columns = [
        (name, column)
        for name, column in _items(grid)
        if name not in ("density", "ndensity", "count")
    ]
    # `data$z <- data[[contour_var]]`：内部的 z 列不参与输出，只给 contour 用。
    columns.append(("z", grid.column(contour_var)))
    working = ColumnTable(columns, nrows=grid.nrows)

    def group_fn(sub: ColumnTable, rows: np.ndarray) -> list[tuple[str, Column]] | None:
        del rows
        group_value = _group_label(_column_values(sub.column("group"))[0])
        x = _numeric(sub.column("x"))
        y = _numeric(sub.column("y"))
        z = _numeric(sub.column("z"))
        rotation = contour.estimate_contour_angle(x, y)
        rotated_x, rotated_y = contour.rotate_xy(x, y, -rotation)
        breaks = contour.contour_breaks(
            z_range,
            bins=params.get("bins"),
            binwidth=params.get("binwidth"),
            breaks=params.get("breaks"),
        )
        if filled:
            return _filled_rows(rotated_x, rotated_y, z, breaks, group_value, rotation)
        return _line_rows(rotated_x, rotated_y, z, breaks, group_value, rotation)

    return _compute_panel(
        working,
        group_fn,
        stat=stat_name,
        dropped=frozenset({"density", "ndensity", "count", "z"}),
    )


def _items(table: ColumnTable) -> list[tuple[str, Column]]:
    return [(name, table.column(name)) for name in table.names]

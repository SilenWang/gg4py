"""`ggcore.stat` —— 统计变换（M1-8）：`bin` / `count` / `boxplot` / `smooth` / `align`。

流水线第 2 阶段（:func:`ggcore.build.compute_stat`）把这里的结果交给
`map_statistic()`。口径照 ggplot2 4.0.3 的 `Stat*$compute_group()` /
`Stat$compute_panel()`，逐列对拍见 `tests/test_stat_r_parity.py`，说明见
`docs/notes/stat.md`。

```
compute_stat(layer, aesthetics, scales=…, raw=…)   # 派发（identity 原样通过）
```

几个贯穿全模块的口径：

- **分组**：`Stat$compute_panel()` 按 `group` 拆组，每组跑 `compute_group()`；
  组内**恒定**的其余列各取一行跟着输出，**变化的列丢弃**（`dropped_aes` 里的
  不告警，其余发 :class:`BuildWarning`）。
- **缺失**：`Stat$compute_layer()` 先按 `required_aes + non_missing_aes` 删掉
  NA / 非有限行（`na.rm = FALSE` 时发 R 同文案的 "Removed N rows …" 警告）。
  与 `build` 的「`$data` 保留 NA 行」不冲突：保留的是 geom 阶段的数据，stat
  本来就会吃掉自己的输入。
- **横向**：`flipped_aes` 由 :func:`_has_flipped_aes`（上游同名函数）判定；
  统计在翻转后的 `x` 上算，输出再翻回来（`switch_orientation()` 的 x↔y 表）。
- **`after_stat()`** 不在这里求值：stat 只负责把变量列（`count` / `density` /
  `prop` …）算出来，`ggcore.build.map_statistic()` 用 M1-2 的 AST 白名单求值。

边界：只 import 标准库 + numpy + ggcore；不碰 IR、标度、坐标、位置。
"""

from __future__ import annotations

import math
import warnings as _warnings
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np

from ggcore.build import BuildError, BuildWarning, _column_values, _items
from ggcore.data import Column, ColumnTable
from ggcore.loess import INTERPOLATE_CELL, loess_fit, loess_interpolate

__all__ = [
    "IMPLEMENTED_STATS",
    "compute_stat",
    "loess_fit",
    "t_quantile",
]

#: 本模块实现的 stat（`identity` 在 build 里原样通过，也列在这里便于报错文案）。
#: 2D 族（M2-6）的实现在 :mod:`ggcore.stat2d`，这里只登记名字与公共口径。
_TWO_D_STATS: tuple[str, ...] = (
    "bin_2d",
    "bin_hex",
    "summary_2d",
    "summary_hex",
    "contour",
    "contour_filled",
    "density_2d",
    "density_2d_filled",
)

IMPLEMENTED_STATS: tuple[str, ...] = (
    "identity",
    "bin",
    "count",
    "boxplot",
    "smooth",
    "align",
    *_TWO_D_STATS,
)

_EMPTY = ColumnTable()

#: 上游 `Stat$compute_layer()` 的 `required_aes`（`x|y` = 二选一）。
_REQUIRED: Mapping[str, tuple[str, ...]] = {
    "bin": ("x", "y"),
    "count": ("x", "y"),
    "boxplot": ("x", "y"),
    "smooth": ("x", "y"),
    "align": ("x", "y"),
    "bin_2d": ("x", "y"),
    "bin_hex": ("x", "y"),
    "summary_2d": ("x", "y", "z"),
    "summary_hex": ("x", "y", "z"),
    "contour": ("x", "y", "z"),
    "contour_filled": ("x", "y", "z"),
    "density_2d": ("x", "y"),
    "density_2d_filled": ("x", "y"),
}
#: `Stat*$non_missing_aes`（`remove_missing()` 也看这些列）。
_NON_MISSING: Mapping[str, tuple[str, ...]] = {
    "bin": (),
    "count": (),
    "boxplot": ("weight",),
    "smooth": (),
    "align": (),
    "bin_2d": (),
    "bin_hex": (),
    "summary_2d": (),
    "summary_hex": (),
    "contour": (),
    "contour_filled": (),
    "density_2d": (),
    "density_2d_filled": (),
}
#: `Stat*$dropped_aes`：组内变化时丢弃但不告警的列。
_DROPPED_AES: Mapping[str, frozenset[str]] = {
    "bin": frozenset({"weight"}),
    "count": frozenset({"weight"}),
    "boxplot": frozenset({"x", "y", "weight"}),
    "smooth": frozenset({"weight"}),
    "align": frozenset(),
    "bin_2d": frozenset({"weight"}),
    "bin_hex": frozenset({"weight"}),
    "summary_2d": frozenset({"z"}),
    "summary_hex": frozenset({"z"}),
    "contour": frozenset({"z", "weight"}),
    "contour_filled": frozenset({"z", "weight"}),
    # `stat_density_2d` 把整张密度网格再送进 contour：原始网格列在链式第二步
    # 被丢弃是预期行为（上游在 compute_layer 里追加到 `dropped_aes`）。
    "density_2d": frozenset({"density", "ndensity", "count"}),
    "density_2d_filled": frozenset({"density", "ndensity", "count"}),
}

#: 上游 `switch_orientation()` 的 x↔y 对照（`ggplot_global$x_aes` / `y_aes`）。
_X_AES: tuple[str, ...] = (
    "x",
    "xmin",
    "xmax",
    "xend",
    "xintercept",
    "xmin_final",
    "xmax_final",
    "xlower",
    "xmiddle",
    "xupper",
    "x0",
)
_Y_AES: tuple[str, ...] = (
    "y",
    "ymin",
    "ymax",
    "yend",
    "yintercept",
    "ymin_final",
    "ymax_final",
    "lower",
    "middle",
    "upper",
    "y0",
)
_FLIP_NAMES: Mapping[str, str] = {
    **{x_name: y_name for x_name, y_name in zip(_X_AES, _Y_AES, strict=True)},
    **{y_name: x_name for x_name, y_name in zip(_X_AES, _Y_AES, strict=True)},
}


# ---------------------------------------------------------------------------
# 派发
# ---------------------------------------------------------------------------


def _custom_stat(stat: Any) -> Callable[..., ColumnTable] | None:
    """子类覆写了 `compute_panel()` 时返回它；内置的 `Stat` 走下方分派。"""
    from ggcore.layer import Stat

    method = getattr(type(stat), "compute_panel", None)
    if method is None or method is Stat.compute_panel:
        return None
    return stat.compute_panel


def compute_stat(
    layer: Any,
    aesthetics: Any,
    *,
    scales: Any = None,
    raw: ColumnTable | None = None,
) -> ColumnTable:
    """第 2 阶段：按 `layer.stat.name` 算统计量。

    `scales` 是这一面板的 :class:`ggcore.scales.ScaleSet`（`bin` 的断点与
    `smooth(fullrange = TRUE)` 要用它训练出来的范围）；`raw` 是位置标度映射
    **之前**的美学表，用来复现 R 的 `is_mapped_discrete()`（横向判定）。
    两者都可以不给：直接调用时按数据本身的形态退化。
    """
    name = layer.stat.name
    if name == "identity":
        return aesthetics.table
    custom = _custom_stat(layer.stat)
    if custom is not None:
        return custom(aesthetics.table, scales=scales)
    if name not in IMPLEMENTED_STATS:
        raise BuildError(
            f"stat {name!r} 尚未实现；已实现：{', '.join(IMPLEMENTED_STATS)}"
            "（stat 的缺省值来自 geom 契约，`geom_*(stat=…)` 可覆盖）"
        )

    table = aesthetics.table
    if table.nrows == 0:
        return _EMPTY
    params = _stat_params(layer)
    flipped = _flipped_for(name, table, params, raw)

    required = tuple(name_ for name_ in _REQUIRED[name] if name_ in table)
    if not required:
        raise BuildError(
            f"stat_{name} 需要 {' 或 '.join(_REQUIRED[name])} 美学（数据阶段没有映射它）"
        )
    table = _remove_missing(table, params, required + _NON_MISSING[name], stat=name)
    if table.nrows == 0:
        return _EMPTY

    if name == "count":
        return _stat_count(table, params, flipped=flipped)
    if name == "bin":
        return _stat_bin(table, params, scales=scales, flipped=flipped, raw=raw)
    if name == "boxplot":
        return _stat_boxplot(table, params, flipped=flipped)
    if name == "smooth":
        return _stat_smooth(table, params, scales=scales, flipped=flipped)
    if name == "align":
        return _stat_align(table, params, flipped=flipped)
    if name in _TWO_D_STATS:
        from ggcore.stat2d import compute_2d

        return compute_2d(name, table, params, scales=scales)
    raise AssertionError(name)  # pragma: no cover - IMPLEMENTED_STATS 已经拦住了


def _stat_params(layer: Any) -> dict[str, Any]:
    """stat 能看到的参数表：层参数（`geom_histogram(bins=…)`）+ `stat_*()` 的参数。

    R 的 layer 只有一个 `params` 字典，stat 与 geom 各取自己认识的键
    （`params[intersect(names(params), self$parameters())]`），所以这里合并两份；
    `stat_*()` 显式给的优先。
    """
    return {**dict(layer.params), **dict(layer.stat.params)}


# ---------------------------------------------------------------------------
# 列工具
# ---------------------------------------------------------------------------


def _float_column(values: Sequence[float] | np.ndarray) -> Column:
    array = np.asarray(values, dtype=np.float64)
    missing = np.isnan(array)
    if missing.any():
        return Column("float", np.where(missing, 0.0, array), na_mask=missing)
    return Column("float", array)


def _bool_column(values: Sequence[bool] | np.ndarray) -> Column:
    return Column("bool", np.asarray(values, dtype=bool))


def _str_column(values: Sequence[str]) -> Column:
    return Column("str", np.array([str(item) for item in values], dtype=object))


def _numeric(column: Column) -> np.ndarray:
    """数值列 → float64（NA → NaN）；离散列报错（stat 的连续口径）。"""
    if column.kind in ("str", "categorical"):
        raise BuildError(f'stat 需要数值列，收到 {column.kind} 列（离散位置请用 stat = "count"）')
    return np.asarray(_column_values(column), dtype=np.float64)


def _take(column: Column, rows: np.ndarray) -> Column:
    """按行号取子集，保留 kind / levels / na_mask。"""
    return Column(
        column.kind,
        column.values[rows],
        levels=column.levels,
        na_mask=column.na_mask[rows],
    )


def _slice(table: ColumnTable, rows: np.ndarray) -> ColumnTable:
    return ColumnTable([(name, _take(column, rows)) for name, column in _items(table)])


def _constant_column(column: Column, index: int, nrows: int) -> Column:
    """组内恒定的列 → `nrows` 行重复（上游 `old[rep(1, nrow(new)), ]`）。"""
    return Column(
        column.kind,
        np.full(nrows, column.values[index]),
        levels=column.levels,
        na_mask=np.full(nrows, bool(column.na_mask[index])),
    )


def _value_key(value: Any) -> Any:
    if value is None:
        return ("<na>",)
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return ("<nan>",)
    return value


def _unique_count(values: np.ndarray) -> int:
    """上游 `vec_unique_count()`：NA 也算一个取值。"""
    return len({_value_key(item) for item in values.tolist()})


def _group_rows(table: ColumnTable) -> list[np.ndarray]:
    """按 `group` 拆行（升序，和 R 的 `split()` 一致）；没有 group 列时整表一组。"""
    if "group" not in table:
        return [np.arange(table.nrows)]
    groups = np.asarray(table.column("group").values)
    return [np.flatnonzero(groups == value) for value in np.unique(groups)]


def _remove_missing(
    table: ColumnTable,
    params: Mapping[str, Any],
    variables: Sequence[str],
    *,
    stat: str,
    finite: bool = True,
) -> ColumnTable:
    """上游 `remove_missing()`：删掉这些列缺失（或非有限）的行，`na.rm=FALSE` 时告警。"""
    missing = np.zeros(table.nrows, dtype=bool)
    for name in variables:
        if name not in table:
            continue
        column = table.column(name)
        missing |= np.asarray(column.na_mask, dtype=bool)
        if finite and column.kind in ("float", "int", "datetime", "timedelta"):
            missing |= ~np.isfinite(np.asarray(column.values, dtype=np.float64))
    if not missing.any():
        return table
    if not bool(params.get("na.rm", False)):
        count = int(missing.sum())
        noun = "row" if count == 1 else "rows"
        _warnings.warn(
            f"Removed {count} {noun} containing non-finite outside the scale range "
            f"(`stat_{stat}()`).",
            BuildWarning,
            stacklevel=4,
        )
    return _slice(table, np.flatnonzero(~missing))


def _flip_table(table: ColumnTable) -> ColumnTable:
    """`flip_data()`：按 x↔y 表重命名列（列序不变）。"""
    return ColumnTable(
        [(_FLIP_NAMES.get(name, name), column) for name, column in _items(table)],
        nrows=table.nrows,
    )


def _is_mapped_discrete(column: Column | None) -> bool:
    return column is not None and column.kind in ("str", "categorical", "bool")


def _has_flipped_aes(
    table: ColumnTable,
    params: Mapping[str, Any],
    raw: ColumnTable | None = None,
    *,
    main_is_orthogonal: bool | None = None,
    group_has_equal: bool = False,
    ambiguous: bool = False,
    main_is_continuous: bool = False,
    default: bool = False,
) -> bool:
    """上游 `has_flipped_aes()` 的 1 维版本（`range_is_orthogonal` 用不到）。"""
    if "flipped_aes" in table:
        for value in _column_values(table.column("flipped_aes")).tolist():
            if not _is_na(value):
                return bool(value)
    orientation = params.get("orientation")
    if not _is_na(orientation):
        return orientation == "y"

    x = table.column("x") if "x" in table else None
    y = table.column("y") if "y" in table else None
    if main_is_orthogonal is not None and (x is None) != (y is None):
        return (y is None) == main_is_orthogonal
    if ambiguous:
        return False

    def discrete(name: str, column: Column | None) -> bool:
        if raw is not None and name in raw:
            return _is_mapped_discrete(raw.column(name))
        return _is_mapped_discrete(column)

    x_discrete = discrete("x", x)
    y_discrete = discrete("y", y)
    if x_discrete != y_discrete:
        return y_discrete != main_is_continuous

    if group_has_equal:
        groups = (
            np.asarray(table.column("group").values) if "group" in table else np.zeros(table.nrows)
        )
        for name, column in (("x", x), ("y", y)):
            if column is None:
                continue
            values = _column_values(column)
            counts = [_unique_count(values[groups == gid]) for gid in np.unique(groups)]
            if counts and all(count == 1 for count in counts):
                return name == "y"
    return bool(default)


def _is_na(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def _flipped_for(
    name: str, table: ColumnTable, params: Mapping[str, Any], raw: ColumnTable | None
) -> bool:
    """各 stat 调用 `setup_params()` 时传给 `has_flipped_aes()` 的那组开关。"""
    if name in _TWO_D_STATS:
        # 2D 族没有横向概念（上游也不调 has_flipped_aes()）。
        return False
    if name in ("bin", "count"):
        return _has_flipped_aes(table, params, raw, main_is_orthogonal=False)
    if name == "boxplot":
        assert name  # 参数只用于阅读
        return _has_flipped_aes(table, params, raw, main_is_orthogonal=True, group_has_equal=True)
    # smooth / align：ambiguous = TRUE，没有 orientation 时永远竖向。
    return _has_flipped_aes(table, params, raw, ambiguous=True)


# ---------------------------------------------------------------------------
# Stat$compute_panel()：分组 → 组函数 → 组内恒定的其余列
# ---------------------------------------------------------------------------


def _compute_panel(
    table: ColumnTable,
    group_fn: Callable[[ColumnTable, np.ndarray], Sequence[tuple[str, Column]] | None],
    *,
    stat: str,
    dropped: frozenset[str] | None = None,
) -> ColumnTable:
    """上游 `Stat$compute_panel()`：逐组跑 `group_fn`，拼回一张表。

    `group_fn(sub, rows)` 返回列（名字 + `Column`），或 `None` / 空序列表示这一
    组没有输出。组内恒定的旧列按原顺序追加在末尾，变化的列丢弃。
    """
    frames: list[list[tuple[str, Column]]] = []
    dropped: list[str] = []
    for rows in _group_rows(table):
        produced = group_fn(_slice(table, rows), rows)
        if not produced:
            continue
        new = list(produced)
        nrows = new[0][1].size
        names = {name for name, _ in new}
        for column_name, column in _items(table):
            if column_name in names:
                continue
            values = _column_values(column)[rows]
            if _unique_count(values) > 1:
                dropped.append(column_name)
                continue
            new.append((column_name, _constant_column(column, int(rows[0]), nrows)))
        frames.append(new)

    dropped_names = tuple(dict.fromkeys(dropped))
    silent = _DROPPED_AES.get(stat, frozenset()) if dropped is None else frozenset(dropped)
    noisy = [name for name in dropped_names if name not in silent]
    if noisy:
        _warnings.warn(
            f"stat_{stat} 丢弃了组内变化的美学：{'，'.join(noisy)}"
            "（上游同样会在统计变换时丢弃；需要保留请显式 aes(group = …)）",
            BuildWarning,
            stacklevel=4,
        )
    if not frames:
        return _EMPTY
    names = [name for name, _ in frames[0]]
    columns: list[tuple[str, Column]] = []
    for position, name in enumerate(names):
        columns.append((name, _concat_columns([frame[position][1] for frame in frames])))
    return ColumnTable(columns)


def _concat_columns(parts: Sequence[Column]) -> Column:
    kind = parts[0].kind
    for column in parts[1:]:
        if column.kind != kind:
            raise BuildError(f"stat 拼接时列类型不一致：{kind} / {column.kind}")
    return Column(
        kind,
        np.concatenate([np.asarray(column.values) for column in parts]),
        levels=parts[0].levels,
        na_mask=np.concatenate([np.asarray(column.na_mask) for column in parts]),
    )


# ---------------------------------------------------------------------------
# stat_count
# ---------------------------------------------------------------------------


def _stat_count(table: ColumnTable, params: Mapping[str, Any], *, flipped: bool) -> ColumnTable:
    """`stat_count`：每个分组内按 x（横向按 y）汇总计数（上游 `StatCount$compute_group`）。"""
    del params
    work = _flip_table(table) if flipped else table
    if "x" not in work:
        raise BuildError("stat_count 需要 x 列（数据阶段没有映射它？）")
    if "group" not in work:
        raise BuildError("stat_count 需要 group 列（数据阶段没有分组信息？）")
    x_column = work.column("x")
    x_values = _column_values(x_column)
    weight = (
        np.asarray(_column_values(work.column("weight")), dtype=np.float64)
        if "weight" in work
        else np.ones(work.nrows, dtype=np.float64)
    )
    weight = np.where(np.isnan(weight), 0.0, weight)
    groups = np.asarray(work.column("group").values).astype(np.int64)

    frames: list[dict[str, list[Any]]] = []
    dropped: list[str] = []
    for group_id in np.unique(groups):
        rows = np.flatnonzero(groups == group_id)
        order = rows[_level_order(x_values[rows], x_column)]
        picked = order[_unique_positions(x_values[order])]
        group_rows = x_values[rows]
        counts = np.array(
            [float(weight[rows][group_rows == x_values[row]].sum()) for row in picked],
            dtype=np.float64,
        )
        total_count = float(np.abs(counts).sum())
        prop = counts / total_count if total_count else counts
        frame: dict[str, list[Any]] = {
            "count": counts.tolist(),
            "prop": prop.tolist(),
            "x_rows": picked.tolist(),
        }
        # 上游 `Stat$compute_panel` 把组内恒定的其它列各取一行带上；变化的列丢弃。
        for name, column in _items(work):
            if name == "x":
                continue
            values = _column_values(column)[rows]
            unique = {repr(item) for item in values.tolist()}
            if len(unique) <= 1:
                frame[name] = [values[0] if values.size else None] * int(picked.size)
            elif name not in ("group", "PANEL"):
                dropped.append(name)
        frames.append(frame)

    dropped_names = tuple(dict.fromkeys(dropped))
    if dropped_names:
        _warnings.warn(
            "stat_count 丢弃了组内变化的美学："
            + "，".join(dropped_names)
            + "（上游同样会在统计变换时丢弃）",
            BuildWarning,
            stacklevel=4,
        )

    total = sum(len(frame["count"]) for frame in frames)
    result: list[tuple[str, Column]] = [
        ("count", Column("float", np.concatenate([np.asarray(f["count"]) for f in frames]))),
        ("prop", Column("float", np.concatenate([np.asarray(f["prop"]) for f in frames]))),
    ]
    if total:
        picked_all = np.concatenate([np.asarray(f["x_rows"], dtype=np.int64) for f in frames])
        result.append(("x", _take(x_column, picked_all)))
    else:
        result.append(("x", _take(x_column, np.zeros(0, dtype=np.int64))))
    result.append(("flipped_aes", _bool_column(np.full(total, flipped))))
    for name, column in _items(work):
        if name == "x" or name not in frames[0]:
            continue
        # 常量列取每个组的代表行（组内值相同，取哪一行都一样）。
        source_rows = np.concatenate(
            [
                np.full(len(f["count"]), f["x_rows"][0] if f["x_rows"] else 0, dtype=np.int64)
                for f in frames
            ]
        )
        result.append((name, _take(column, source_rows)))
    return _flip_table(ColumnTable(result)) if flipped else ColumnTable(result)


def _level_order(values: np.ndarray, column: Column) -> np.ndarray:
    """离散列按 levels 顺序排行的行号；数值列按值排序。"""
    if column.is_discrete and column.levels:
        rank = {level: position for position, level in enumerate(column.levels)}
        keys = np.array([rank.get(item, len(rank)) for item in values.tolist()], dtype=np.int64)
    else:
        keys = np.asarray(values)
    return np.argsort(keys, kind="stable")


def _unique_positions(values: np.ndarray) -> np.ndarray:
    """有序数组里每个不同值第一次出现的位置。"""
    if values.size == 0:
        return np.zeros(0, dtype=np.int64)
    changed = np.ones(values.size, dtype=bool)
    changed[1:] = values[1:] != values[:-1]
    return np.flatnonzero(changed)


# ---------------------------------------------------------------------------
# stat_bin
# ---------------------------------------------------------------------------


class _Bins:
    """上游 `ggplot2_bins` 对象：breaks + 模糊端点 + 哪一侧闭合。"""

    __slots__ = ("breaks", "fuzzy", "right_closed")

    def __init__(self, breaks: np.ndarray, *, closed: str) -> None:
        if closed not in ("right", "left"):
            raise BuildError(f"closed 只能是 'right' 或 'left'，收到 {closed!r}")
        breaks = np.sort(np.asarray(breaks, dtype=np.float64))
        finite = breaks[np.isfinite(breaks)]
        diff = np.diff(finite)
        fuzz = float(np.median(diff)) * 1e-8 if diff.size else float("nan")
        if not math.isfinite(fuzz):
            fuzz = float(np.finfo(np.float64).eps) * 1000.0
        if closed == "right":
            fuzzes = np.concatenate([[-fuzz], np.full(breaks.size - 1, fuzz)])
        else:
            fuzzes = np.concatenate([np.full(breaks.size - 1, -fuzz), [fuzz]])
        self.breaks = breaks
        self.fuzzy = breaks + fuzzes
        self.right_closed = closed == "right"

    def cut(self, values: np.ndarray) -> np.ndarray:
        """上游 `bin_cut()`：`cut(x, fuzzy, right = right_closed, include.lowest = TRUE)`。

        返回 0 起的 bin 下标，断点之外是 -1。
        """
        edges = self.fuzzy
        if self.right_closed:
            index = np.searchsorted(edges, values, side="left") - 1
        else:
            index = np.searchsorted(edges, values, side="right") - 1
        out = np.full(values.shape, -1, dtype=np.int64)
        inside = np.isfinite(values) & (index >= 0) & (index <= edges.size - 2)
        out[inside] = index[inside]
        lowest = np.isfinite(values) & (values == edges[0])
        highest = np.isfinite(values) & (values == edges[-1])
        if self.right_closed:
            out[lowest] = 0
        else:
            out[highest] = edges.size - 2
        return out


def _r_mod(value: float, modulus: float) -> float:
    """R 的 `%%`（结果与除数同号，不做 numpy 的 fmod 截断）。"""
    return value - math.floor(value / modulus) * modulus


def _r_seq(start: float, stop: float, by: float) -> np.ndarray:
    """R 的 `seq(from, to, by)`：`n = floor((to - from)/by + 1e-10)`。"""
    if by == 0:
        raise BuildError("binwidth 不能是 0")
    if (stop - start) / by < 0:
        raise BuildError(f"bin 断点方向不对：seq({start}, {stop}, {by})")
    n = math.floor((stop - start) / by + 1e-10)
    return start + np.arange(n + 1, dtype=np.float64) * by


def _zero_range(values: np.ndarray) -> bool:
    return bool(values.size == 0) or bool(values[0] == values[-1])


def _bin_breaks_width(
    x_range: np.ndarray,
    width: float,
    *,
    center: float | None,
    boundary: float | None,
    closed: str,
) -> _Bins:
    """上游 `bin_breaks_width()`。"""
    if boundary is None:
        boundary = width / 2.0 if center is None else center - width / 2.0
    shift = math.floor((x_range[0] - boundary) / width)
    origin = boundary + shift * width
    max_x = x_range[1] + (1.0 - 1e-8) * width
    if (max_x - origin) / width > 1e6:
        raise BuildError("histogram 的箱数超过 1,000,000：binwidth 太小了")
    breaks = _r_seq(origin, max_x, width)
    if breaks.size == 1:
        breaks = np.array([breaks[0], breaks[0] + width])
    return _Bins(breaks, closed=closed)


def _bin_breaks_bins(
    x_range: np.ndarray,
    bins: int,
    *,
    center: float | None,
    boundary: float | None,
    closed: str,
) -> _Bins:
    """上游 `bin_breaks_bins()`：`bins` 个箱的宽度推导（含 R 的浮点口径）。"""
    if _zero_range(x_range):
        width = 0.1
    elif bins == 1:
        width = float(x_range[1] - x_range[0])
        boundary = float(x_range[0])
        center = None
    else:
        width = float(x_range[1] - x_range[0]) / (bins - 1)
        if center is None and boundary is None:
            boundary = float(x_range[0] - width / 2.0)
        if boundary is not None and any(
            _r_mod(float(value), width) == _r_mod(float(boundary), width) for value in x_range
        ):
            width = float(x_range[1] - x_range[0]) / bins
    return _bin_breaks_width(x_range, width, center=center, boundary=boundary, closed=closed)


def _compute_bins(
    *,
    breaks: Any = None,
    binwidth: float | None,
    bins: int | None,
    center: float | None,
    boundary: float | None,
    closed: str,
    x_range: np.ndarray,
) -> _Bins:
    """上游 `compute_bins()`（`breaks` 只支持显式数值序列）。"""
    if breaks is not None:
        requested = np.asarray(breaks, dtype=np.float64)
        if requested.ndim != 1 or requested.size < 2:
            raise BuildError("stat_bin(breaks=…) 需要至少两个断点")
        return _Bins(requested, closed=closed)
    if boundary is not None and center is not None:
        raise BuildError("stat_bin 的 boundary 与 center 只能给一个（上游同样报错）")
    if binwidth is not None:
        number = float(binwidth)
        if not math.isfinite(number) or number < 0:
            raise BuildError(f"binwidth 必须是非负有限数，收到 {binwidth!r}")
        return _bin_breaks_width(x_range, number, center=center, boundary=boundary, closed=closed)
    if bins is None:
        bins = 30
    if int(bins) != bins or int(bins) < 1:
        raise BuildError(f"bins 必须是正整数，收到 {bins!r}")
    return _bin_breaks_bins(x_range, int(bins), center=center, boundary=boundary, closed=closed)


def _bin_out(count: np.ndarray, x: np.ndarray, width: np.ndarray) -> list[tuple[str, Column]]:
    """上游 `bin_out()`：count / x / xmin / xmax / width / density / ncount / ndensity。"""
    xmin = x - width / 2.0
    xmax = x + width / 2.0
    with np.errstate(invalid="ignore", divide="ignore"):
        total = float(np.sum(np.abs(count)))
        density = (count / width) / total if total else count / width * np.nan
        maximum = float(np.max(np.abs(count))) if count.size else 0.0
        ncount = count / maximum if maximum else count * np.nan
        dmax = float(np.max(np.abs(density))) if density.size else 0.0
        ndensity = density / dmax if dmax else density * np.nan
    return [
        ("count", _float_column(count)),
        ("x", _float_column(x)),
        ("xmin", _float_column(xmin)),
        ("xmax", _float_column(xmax)),
        ("width", _float_column(width)),
        ("density", _float_column(density)),
        ("ncount", _float_column(ncount)),
        ("ndensity", _float_column(ndensity)),
    ]


def _stat_bin(
    table: ColumnTable,
    params: Mapping[str, Any],
    *,
    scales: Any,
    flipped: bool,
    raw: ColumnTable | None,
) -> ColumnTable:
    """`stat_bin`：断点 → 每箱计数 → `bin_out()`（上游 `StatBin`）。"""
    present = [name for name in ("x", "y") if name in table]
    if len(present) == 2:
        raise BuildError("stat_bin 只能有 x 或 y 之一（上游同样报错）")
    axis = "y" if flipped else "x"
    source = raw.column(axis) if (raw is not None and axis in raw) else table.column(axis)
    if _is_mapped_discrete(source) or source.kind in ("str", "categorical"):
        raise BuildError(
            f'stat_bin 需要连续的 {axis} 美学；离散请用 stat = "count"（上游同样报错）'
        )

    closed = str(params.get("closed", "right"))
    pad = bool(params.get("pad", False))
    drop = _resolve_drop(params.get("drop", "none"))
    work = _flip_table(table) if flipped else table
    values = _numeric(work.column("x"))
    weight = (
        np.asarray(_column_values(work.column("weight")), dtype=np.float64)
        if "weight" in work
        else np.ones(work.nrows, dtype=np.float64)
    )
    weight = np.where(np.isnan(weight), 0.0, weight)
    breaks_obj = _compute_bins(
        breaks=params.get("breaks"),
        binwidth=params.get("binwidth"),
        bins=params.get("bins"),
        center=_optional_float(params.get("center"), "center"),
        boundary=_optional_float(params.get("boundary"), "boundary"),
        closed=closed,
        # 上游 `StatBin$compute_group()`：`compute_bins(data[[x]], scales[[x]])`，
        # `x <- flipped_names(flipped_aes)$x` —— 横向 histogram 的断点取自 y 轴。
        x_range=_dimension(scales, "y" if flipped else "x", values),
    )
    widths = np.diff(breaks_obj.breaks)
    centres = (breaks_obj.breaks[:-1] + breaks_obj.breaks[1:]) / 2.0

    def group_fn(sub: ColumnTable, rows: np.ndarray) -> list[tuple[str, Column]]:
        count = _bin_counts(values[rows], weight[rows], breaks_obj)
        bin_x = centres
        bin_width = widths
        if pad:
            count = np.concatenate([[0.0], count, [0.0]])
            first, last = bin_width[0], bin_width[-1]
            bin_width = np.concatenate([[first], bin_width, [last]])
            bin_x = np.concatenate([[bin_x[0] - first], bin_x, [bin_x[-1] + last]])
        if not np.all(np.isfinite(breaks_obj.breaks)):
            count = np.concatenate([count, [float(np.sum(~np.isfinite(breaks_obj.breaks)))]])
            bin_width = np.concatenate([bin_width, [np.nan]])
            bin_x = np.concatenate([bin_x, [np.nan]])
        keep = _drop_mask(count, drop)
        columns = _bin_out(count[keep], bin_x[keep], bin_width[keep])
        columns.append(("flipped_aes", _bool_column(np.full(int(keep.sum()), flipped))))
        return columns

    result = _compute_panel(work, group_fn, stat="bin")
    if result.nrows == 0:
        return _EMPTY
    return _flip_table(result) if flipped else result


def _optional_float(value: Any, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise BuildError(f"stat_bin 的 {name} 必须是数值，收到 {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise BuildError(f"stat_bin 的 {name} 必须是有限数，收到 {value!r}")
    return number


def _resolve_drop(value: Any) -> str:
    if value is None or value is False or value == "none":
        return "none"
    if value is True or value == "all":
        return "all"
    if value == "extremes":
        return "extremes"
    raise BuildError(
        f"stat_bin 的 drop 只能是 none / all / extremes / TRUE / FALSE，收到 {value!r}"
    )


def _drop_mask(count: np.ndarray, drop: str) -> np.ndarray:
    if drop == "all":
        return count != 0
    if drop == "extremes":
        nonzero = np.flatnonzero(count != 0)
        keep = np.zeros(count.shape, dtype=bool)
        if nonzero.size:
            keep[int(nonzero[0]) : int(nonzero[-1]) + 1] = True
        return keep
    return np.ones(count.shape, dtype=bool)


def _bin_counts(values: np.ndarray, weights: np.ndarray, bins: _Bins) -> np.ndarray:
    """上游 `bin_vector()` 的计数部分（`tapply(weight, cut(x, bins), sum)`）。"""
    index = bins.cut(values)
    count = np.zeros(max(int(bins.breaks.size) - 1, 0), dtype=np.float64)
    valid = index >= 0
    np.add.at(count, index[valid], weights[valid])
    return count


def _dimension(scales: Any, aesthetic: str, values: np.ndarray) -> np.ndarray:
    """`scale$dimension()`：这一面板训练出来的范围（没有标度时退回数据范围）。"""
    if scales is not None:
        try:
            limits = scales.limits(aesthetic)
        except Exception:
            limits = None
        if limits is not None:
            low, high = float(limits[0]), float(limits[1])
            if math.isfinite(low) and math.isfinite(high):
                return np.array([low, high], dtype=np.float64)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return np.array([0.0, 1.0], dtype=np.float64)
    return np.array([float(finite.min()), float(finite.max())], dtype=np.float64)


# ---------------------------------------------------------------------------
# stat_boxplot
# ---------------------------------------------------------------------------


def _stat_boxplot(table: ColumnTable, params: Mapping[str, Any], *, flipped: bool) -> ColumnTable:
    """`stat_boxplot`：五数（type 7）+ 须线 + 离群点（上游 `StatBoxplot`）。"""
    coef = float(params.get("coef", 1.5))
    if not math.isfinite(coef) or coef < 0:
        raise BuildError(f"stat_boxplot 的 coef 必须是非负有限数，收到 {params.get('coef')!r}")
    quantile_type = params.get("quantile.type", 7)
    if int(quantile_type) != 7:
        raise BuildError(
            f"stat_boxplot 只实现 R 的 quantile type 7（默认值），收到 {quantile_type!r}"
        )
    width_param = params.get("width")
    if width_param is not None:
        width_param = float(width_param)
    varwidth = bool(params.get("varwidth", False))
    del varwidth  # 只影响 geom 的 xmin/xmax，`setup_data()` 读 relvarwidth
    work = _flip_table(table) if flipped else table

    def group_fn(sub: ColumnTable, rows: np.ndarray) -> list[tuple[str, Column]] | None:
        del rows
        if "weight" in sub:
            raise BuildError(
                "stat_boxplot 的加权分位（R 的 quantreg::rq）尚未实现；"
                "请勿映射 weight，或等后续任务（见 docs/notes/stat.md §8）"
            )
        y = _numeric(sub.column("y"))
        x_column = sub.column("x")
        quantiles = np.quantile(y, [0.0, 0.25, 0.5, 0.75, 1.0], method="linear")
        iqr = float(quantiles[3] - quantiles[1])
        lower_fence = float(quantiles[1] - coef * iqr)
        upper_fence = float(quantiles[3] + coef * iqr)
        outliers = (y < lower_fence) | (y > upper_fence)
        if bool(outliers.any()):
            inside = np.concatenate([quantiles[1:4], y[~outliers]])
            quantiles[0] = float(np.min(inside))
            quantiles[4] = float(np.max(inside))
        # width：映射的 width 列 > 组内 x 变化时的 0.9×极差 > setup_params 的缺省。
        if "width" in sub:
            width = float(_numeric(sub.column("width"))[0])
        else:
            positions = _numeric(x_column)
            finite = positions[np.isfinite(positions)]
            if np.unique(finite).size > 1:
                width = float(finite.max() - finite.min()) * 0.9
            else:
                width = width_param if width_param is not None else _resolution(positions) * 0.75
        if x_column.kind in ("str", "categorical"):
            centre_column = _str_column([str(_column_values(x_column)[0])])
        else:
            positions = _numeric(x_column)
            finite = positions[np.isfinite(positions)]
            centre_column = _float_column(
                [float((finite.min() + finite.max()) / 2.0) if finite.size else float("nan")]
            )
        n = int(np.count_nonzero(~np.isnan(y)))
        notch = 1.58 * iqr / math.sqrt(n) if n > 0 else math.nan
        return [
            ("ymin", _float_column([quantiles[0]])),
            ("lower", _float_column([quantiles[1]])),
            ("middle", _float_column([quantiles[2]])),
            ("upper", _float_column([quantiles[3]])),
            ("ymax", _float_column([quantiles[4]])),
            ("outliers", _str_column([_format_outliers(y[outliers])])),
            ("notchupper", _float_column([float(quantiles[2]) + notch])),
            ("notchlower", _float_column([float(quantiles[2]) - notch])),
            ("x", centre_column),
            ("width", _float_column([width])),
            ("relvarwidth", _float_column([math.sqrt(n)])),
            ("flipped_aes", _bool_column([flipped])),
        ]

    result = _compute_panel(work, group_fn, stat="boxplot")
    if result.nrows == 0:
        return _EMPTY
    return _flip_table(result) if flipped else result


def _resolution(values: np.ndarray) -> float:
    """上游 `resolution(x, discrete = TRUE)`（位置已经映射成 1..n）。"""
    finite = values[np.isfinite(values)]
    if finite.size <= 1:
        return 1.0
    unique = np.unique(finite)
    if unique.size <= 1:
        return 1.0
    diffs = np.diff(unique)
    tolerance = float(np.sqrt(np.finfo(np.float64).eps))
    if np.all(diffs < tolerance):
        return 1.0
    return float(np.min(diffs[diffs > tolerance]))


def _format_outliers(values: np.ndarray) -> str:
    """离群点列表 → R 风格文本（`ColumnTable` 没有 list kind，见 docs/notes/stat.md）。"""
    numbers = [float(value) for value in values.tolist() if math.isfinite(float(value))]
    if not numbers:
        return "c()"
    return "c(" + ", ".join(_format_number(value) for value in numbers) + ")"


def _format_number(value: float) -> str:
    text = repr(float(value))
    return text[:-2] if text.endswith(".0") else text


# ---------------------------------------------------------------------------
# stat_smooth（loess / lm）
# ---------------------------------------------------------------------------

#: R `loess.control()` 的缺省值（gg4py 只实现其中两种组合，见 `_loess_control`）。
_LOESS_CONTROL_DEFAULTS: Mapping[str, Any] = {
    "surface": "interpolate",
    "statistics": "approximate",
    "trace.hat": "exact",
    "cell": INTERPOLATE_CELL,
}

#: 两种「面 + 统计量」组合，其余组合 R 有、gg4py 尚未实现。
_LOESS_IMPLEMENTED: Mapping[str, tuple[str, str]] = {
    "interpolate": ("approximate", "exact"),
    "direct": ("exact", "exact"),
}


def _loess_control(params: Mapping[str, Any]) -> dict[str, Any]:
    """解析 `method.args`（R 的 `loess(...)` 参数）里的 loess control。

    R 的写法是 `method.args = list(control = loess.control(surface = "direct",
    statistics = "exact", trace.hat = "exact"))`；gg4py 用同名字典表达
    （`loess.control()` 在 Python 里没有对应对象）。

    - 缺省 = R 缺省：`surface = "interpolate"`、`statistics = "approximate"`、
      `trace.hat = "exact"`、`cell = 0.2`；
    - `surface = "direct"` 走 `ggcore.loess.loess_fit()`（逐点局域回归），要求
      `statistics = "exact"`、`trace.hat = "exact"`（既有实现的口径）；
    - `surface = "interpolate"` 走 k-d 树 + Hermite 插值，只实现 R 缺省的
      `statistics = "approximate"`（`trace.hat = "exact"`）。
    """
    raw_args = params.get("method_args")
    if raw_args is None:
        raw_args = {}
    if not isinstance(raw_args, Mapping):
        raise BuildError(
            "stat_smooth 的 method_args 必须是映射"
            f"（对应 R 的 method.args = list(...)），收到 {raw_args!r}"
        )
    allowed = {"control", "degree", "span"}
    unknown = sorted(str(key) for key in raw_args if key not in allowed)
    if unknown:
        raise BuildError(
            f"stat_smooth 的 method_args 只支持 control / degree / span，收到 {', '.join(unknown)}"
        )
    control = dict(_LOESS_CONTROL_DEFAULTS)
    raw_control = raw_args.get("control")
    if raw_control is not None:
        if not isinstance(raw_control, Mapping):
            raise BuildError(
                'stat_smooth 的 method_args["control"] 必须是映射'
                "（R 的 loess.control(...)），"
                f"收到 {raw_control!r}"
            )
        unknown = sorted(
            str(key)
            for key in raw_control
            if key not in _LOESS_CONTROL_DEFAULTS and key not in ("iterations", "iterTrace")
        )
        if unknown:
            raise BuildError(
                "loess control 只支持 surface / statistics / trace.hat / cell，"
                f"收到 {', '.join(unknown)}"
            )
        iterations = raw_control.get("iterations", 1)
        if int(iterations) != 1:
            raise BuildError(
                f"loess 的稳健迭代（iterations = {iterations!r}）尚未实现；"
                "只支持 family = 'gaussian'（iterations = 1）"
            )
        if raw_control.get("iterTrace"):
            raise BuildError("loess 的 iterTrace 尚未实现（只支持 iterations = 1）")
        for key in ("surface", "statistics", "trace.hat"):
            if key in raw_control:
                control[key] = str(raw_control[key])
        if "cell" in raw_control:
            control["cell"] = float(raw_control["cell"])
    surface = control["surface"]
    if surface not in _LOESS_IMPLEMENTED:
        raise BuildError(f"loess 的 surface 只能是 'interpolate' / 'direct'，收到 {surface!r}")
    wanted = (control["statistics"], control["trace.hat"])
    if wanted != _LOESS_IMPLEMENTED[surface]:
        expected = _LOESS_IMPLEMENTED[surface]
        raise BuildError(
            f"gg4py 的 loess surface = {surface!r} 只实现 statistics = "
            f"{expected[0]!r}、trace.hat = {expected[1]!r}（上游该面还有其它组合，"
            f"尚未实现）；收到 statistics = {wanted[0]!r}、trace.hat = {wanted[1]!r}"
        )
    cell = float(control["cell"])
    if not (0 < cell <= 1):
        raise BuildError(f"loess 的 cell 必须在 (0, 1] 内，收到 {cell!r}")
    control["cell"] = cell
    if "degree" in raw_args:
        # R 只有 `method.args` 能传 loess 的 `degree`（geom_smooth 没有该参数）。
        control["degree"] = raw_args["degree"]
    return control


def _loess_prediction(
    x: np.ndarray,
    y: np.ndarray,
    weight: np.ndarray,
    xseq: np.ndarray,
    *,
    span: float,
    degree: int,
    level: float,
    se: bool,
    control: Mapping[str, Any],
) -> list[tuple[str, Column]]:
    """`method = "loess"` 的预测列（x / y / ymin / ymax / se）。

    `surface = "interpolate"`（R 默认）在数据范围外给 NA（R 的
    `predLoess()` 只对 `inside` 的点求值）；`surface = "direct"` 可外推。
    """
    if control["surface"] == "interpolate":
        result = loess_interpolate(
            x,
            y,
            weight,
            span=span,
            degree=degree,
            newx=xseq,
            cell=float(control["cell"]),
            se=se,
        )
        fit = result["fit"]
        ses = result["se"]
        df = result["df"]
    else:
        fit, kernel = loess_fit(x, y, weight, span=span, degree=degree, newx=xseq)
        if se:
            scale, df = _loess_scale(x, y, weight, span=span, degree=degree)
            with np.errstate(divide="ignore", invalid="ignore"):
                ses = scale * np.sqrt(np.sum(kernel**2 / weight, axis=1))
        else:
            ses, df = None, float("nan")
    prediction: list[tuple[str, Column]] = [
        ("x", _float_column(xseq)),
        ("y", _float_column(fit)),
    ]
    if se:
        assert ses is not None
        half = t_quantile(level / 2.0 + 0.5, df) * ses
        prediction.extend(
            [
                ("ymin", _float_column(fit - half)),
                ("ymax", _float_column(fit + half)),
                ("se", _float_column(ses)),
            ]
        )
    return prediction


def _stat_smooth(
    table: ColumnTable,
    params: Mapping[str, Any],
    *,
    scales: Any,
    flipped: bool,
) -> ColumnTable:
    """`stat_smooth`：loess（局域二次加权回归）/ lm，可选置信带。"""
    method = params.get("method")
    if method is None or method == "auto":
        method = "loess"
    if method in ("gam", "glm"):
        raise BuildError(
            f"stat_smooth 的 method = {method!r} 尚未实现（gam / glm 归后续任务）；"
            "已实现 loess 与 lm"
        )
    if method not in ("loess", "lm"):
        raise BuildError(f"stat_smooth 的 method 只能是 'loess' / 'lm' / 'auto'，收到 {method!r}")
    formula = params.get("formula")
    if formula is not None and str(formula).replace(" ", "") != "y~x":
        raise BuildError(
            f"stat_smooth 只支持 formula = y ~ x，收到 {formula!r}（其他公式归后续任务）"
        )
    se = bool(params.get("se", True))
    n = int(params.get("n", 80))
    if n < 2:
        raise BuildError(f"stat_smooth 的 n 至少是 2，收到 {n!r}")
    span = float(params.get("span", 0.75))
    if not (0 < span <= 1):
        raise BuildError(f"stat_smooth 的 span 必须在 (0, 1] 内，收到 {span!r}")
    control = _loess_control(params)
    # 上游 `StatSmooth$setup_params()`：`method.args$span` 恒被 stat 的 span 覆盖，
    # `degree` 则只能从 `method.args` 传（loess 的形参，geom_smooth 没有 degree）。
    degree = int(control.pop("degree", params.get("degree", 2)))
    if degree not in (0, 1, 2):
        raise BuildError(f"stat_smooth 的 degree 只能是 0 / 1 / 2，收到 {degree!r}")
    level = float(params.get("level", 0.95))
    if not (0 < level < 1):
        raise BuildError(f"stat_smooth 的 level 必须在 (0, 1) 内，收到 {level!r}")
    fullrange = bool(params.get("fullrange", False))
    xseq_param = params.get("xseq")
    work = _flip_table(table) if flipped else table

    def group_fn(sub: ColumnTable, rows: np.ndarray) -> list[tuple[str, Column]] | None:
        del rows
        x = _numeric(sub.column("x"))
        y = _numeric(sub.column("y"))
        weight = (
            np.asarray(_column_values(sub.column("weight")), dtype=np.float64)
            if "weight" in sub
            else np.ones(x.shape, dtype=np.float64)
        )
        weight = np.where(np.isnan(weight), 0.0, weight)
        if np.unique(x).size < 2:
            return None
        if xseq_param is not None:
            xseq = np.asarray(xseq_param, dtype=np.float64)
        elif fullrange:
            # 上游 `StatSmooth$compute_group()`：`scales$x$dimension()` —— 取的
            # 是**x 标度**，横向（flipped）时也不换成 y 轴（R 4.0.3 如此，见
            # `tests/test_stat_r_parity.py` 的 `smooth_horizontal_fullrange`）。
            low, high = _dimension(scales, "x", x)
            xseq = np.linspace(low, high, n)
        else:
            xseq = np.linspace(float(np.min(x)), float(np.max(x)), n)
        if method == "loess":
            prediction = _loess_prediction(
                x,
                y,
                weight,
                xseq,
                span=span,
                degree=degree,
                level=level,
                se=se,
                control=control,
            )
        else:
            prediction = _lm_prediction(x, y, weight, xseq, se=se, level=level)
        prediction.append(("flipped_aes", _bool_column(np.full(xseq.size, flipped))))
        return prediction

    result = _compute_panel(work, group_fn, stat="smooth")
    if result.nrows == 0:
        return _EMPTY
    return _flip_table(result) if flipped else result


def _lm_prediction(
    x: np.ndarray,
    y: np.ndarray,
    weight: np.ndarray,
    xseq: np.ndarray,
    *,
    se: bool,
    level: float,
) -> list[tuple[str, Column]]:
    """`method = "lm"`：加权最小二乘 + `predict.lm(interval = "confidence")` 口径。"""
    design = np.column_stack([np.ones(x.size), x])
    xtwx = design.T @ (design * weight[:, None])
    try:
        xtwx_inv = np.linalg.inv(xtwx)
    except np.linalg.LinAlgError as exc:
        raise BuildError(f"stat_smooth(method='lm') 的设计矩阵奇异：{exc}") from exc
    beta = xtwx_inv @ (design.T @ (y * weight))
    fitted = design @ beta
    residuals = y - fitted
    df = int(x.size - np.linalg.matrix_rank(design))
    new_design = np.column_stack([np.ones(xseq.size), xseq])
    values = new_design @ beta
    prediction: list[tuple[str, Column]] = [
        ("x", _float_column(xseq)),
        ("y", _float_column(values)),
    ]
    if se:
        sigma2 = float(np.sum(weight * residuals**2) / df) if df > 0 else float("nan")
        variance = np.einsum("ij,jk,ik->i", new_design, xtwx_inv, new_design) * sigma2
        ses = np.sqrt(np.maximum(variance, 0.0))
        half = t_quantile(level / 2.0 + 0.5, df) * ses
        prediction.extend(
            [
                ("ymin", _float_column(values - half)),
                ("ymax", _float_column(values + half)),
                ("se", _float_column(ses)),
            ]
        )
    return prediction


def _loess_scale(
    x: np.ndarray, y: np.ndarray, weight: np.ndarray, *, span: float, degree: int
) -> tuple[float, float]:
    """loess 的残差尺度 `s` 与自由度 `df`（上游 `simpleLoess()` 的 delta1 / delta2）。

    `delta1 = ‖I - L‖²_F`、`delta2 = ‖(I - L)(I - L)′‖²_F`（loessf.f 的
    `lowesc()`），`s = sqrt(Σ w·r² / delta1)`、`df = delta1² / delta2`，
    与 `predict.loess(se = TRUE)` 的 `se.fit = s·sqrt(Σ L²/w)` 配套。
    """
    fitted, kernel = loess_fit(x, y, weight, span=span, degree=degree, newx=x)
    residual = y - fitted
    hat_residual = np.eye(x.size) - kernel
    gram = hat_residual @ hat_residual.T
    delta1 = float(np.trace(gram))
    delta2 = float(np.trace(gram @ gram))
    if delta1 <= 0:
        return float("inf"), float("nan")
    scale = math.sqrt(float(np.sum(weight * residual**2)) / delta1)
    df = delta1 * delta1 / delta2 if delta2 > 0 else float("nan")
    return scale, df


# `loess_fit()`（direct）与 `loess_interpolate()`（R 默认的 interpolate）都在
# `ggcore.loess`；这里保留同名导出，`ggcore.stat.loess_fit` 是既有调用点。


# ---------------------------------------------------------------------------
# stat_align
# ---------------------------------------------------------------------------


def _stat_align(table: ColumnTable, params: Mapping[str, Any], *, flipped: bool) -> ColumnTable:
    """`stat_align`：组间 x 取并集、`approxfun()` 线性补齐（上游 `StatAlign`）。"""
    del params
    groups = np.asarray(table.column("group").values)
    if _unique_count(groups) <= 1:
        return table
    work = _flip_table(table) if flipped else table
    x = _numeric(work.column("x"))
    y = _numeric(work.column("y"))
    groups = np.asarray(work.column("group").values)

    unique_loc = np.unique(np.concatenate([x, _align_crossings(x, y, groups)]))
    if unique_loc.size == 0:
        return _EMPTY
    adjust = float(unique_loc[-1] - unique_loc[0]) * 0.001
    gaps = np.diff(unique_loc)
    if gaps.size:
        adjust = min(adjust, float(gaps.min()) / 3.0)
    else:
        adjust = 0.0
    unique_loc = np.unique(np.concatenate([unique_loc - adjust, unique_loc, unique_loc + adjust]))

    def group_fn(sub: ColumnTable, rows: np.ndarray) -> list[tuple[str, Column]] | None:
        del rows
        return _align_group(sub, unique_loc, adjust, flipped)

    result = _compute_panel(work, group_fn, stat="align")
    if result.nrows == 0:
        return _EMPTY
    return _flip_table(result) if flipped else result


def _align_crossings(x: np.ndarray, y: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """上游 `StatAlign$compute_panel()`：堆叠面积里各组 y 符号切换处的零点 x。"""
    runs: list[tuple[Any, bool]] = []
    run_times: list[int] = []
    for group, negative in zip(groups.tolist(), (y < 0).tolist(), strict=True):
        key = (group, bool(negative))
        if runs and key == runs[-1]:
            run_times[-1] += 1
        else:
            runs.append(key)
            run_times.append(1)
    group_keys: list[Any] = []
    group_times: list[int] = []
    for group in groups.tolist():
        if group_keys and group == group_keys[-1]:
            group_times[-1] += 1
        else:
            group_keys.append(group)
            group_times.append(1)
    ends = set(np.cumsum(group_times).tolist())
    cumulative = np.cumsum(run_times)
    pivots = [int(value) - 1 for value in cumulative.tolist() if int(value) not in ends]
    crossings: list[float] = []
    for pivot in pivots:
        if pivot + 1 >= x.size:
            continue
        delta = y[pivot + 1] - y[pivot]
        if delta == 0:
            continue
        crossings.append(float(-y[pivot] * (x[pivot + 1] - x[pivot]) / delta + x[pivot]))
    return np.asarray(crossings, dtype=np.float64)


def _align_group(
    sub: ColumnTable, unique_loc: np.ndarray, adjust: float, flipped: bool
) -> list[tuple[str, Column]] | None:
    """上游 `StatAlign$compute_group()`：一个组的 x 并集上线性插值，两端补 0。"""
    x_column = sub.column("x")
    x = _numeric(x_column)
    y = _numeric(sub.column("y"))
    if np.unique(x).size <= 1:
        return None
    if np.unique(x).size != x.size:
        # 同一个 x 有多行：只留首尾两行，给第一行的 x 让开 `adjust`（上游 dapply）。
        positions: dict[float, list[int]] = {}
        for index, value in enumerate(x.tolist()):
            positions.setdefault(float(value), []).append(index)
        rows: list[int] = []
        for value in sorted(positions):
            indices = positions[value]
            rows.append(indices[0])
            if len(indices) > 1:
                rows.append(indices[-1])
        keep = np.asarray(rows, dtype=np.int64)
        sub = _slice(sub, keep)
        x = np.array(x[keep], dtype=np.float64, copy=True)
        y = y[keep]
        # 只有「同一个 x 有多行」的那一段才把首行的 x 让开 `adjust`（上游 dapply）。
        starts = np.flatnonzero(np.concatenate(([True], x[1:] != x[:-1])))
        ends = np.concatenate((starts[1:], [x.size]))
        duplicated = (ends - starts) > 1
        x[starts[duplicated]] -= adjust
    else:
        order = np.argsort(x, kind="stable")
        if not np.array_equal(order, np.arange(x.size)):
            sub = _slice(sub, order)
            x = x[order]
            y = y[order]

    y_value = _approx(x, y, unique_loc)
    keep = ~np.isnan(y_value)
    x_value = unique_loc[keep]
    y_value = y_value[keep]
    if x_value.size == 0:
        return None
    x_value = np.concatenate(
        [[float(x_value.min()) - adjust], x_value, [float(x_value.max()) + adjust]]
    )
    y_value = np.concatenate([[0.0], y_value, [0.0]])
    padding = np.zeros(x_value.size, dtype=bool)
    padding[0] = padding[-1] = True

    columns: list[tuple[str, Column]] = [
        ("x", _float_column(x_value)),
        ("y", _float_column(y_value)),
    ]
    for name in sub.names:
        if name in ("x", "y"):
            continue
        columns.append((name, _constant_column(sub.column(name), 0, x_value.size)))
    columns.append(("align_padding", _bool_column(padding)))
    columns.append(("flipped_aes", _bool_column(np.full(x_value.size, flipped))))
    return columns


def _approx(x: np.ndarray, y: np.ndarray, newx: np.ndarray) -> np.ndarray:
    """上游 `approxfun(x, y)`（rule = 1，线性插值；区间外 NA）。"""
    order = np.argsort(x, kind="stable")
    sorted_x = x[order]
    sorted_y = y[order]
    out = np.full(newx.shape, np.nan, dtype=np.float64)
    if sorted_x.size == 0:
        return out
    inside = (newx >= sorted_x[0]) & (newx <= sorted_x[-1])
    out[inside] = np.interp(newx[inside], sorted_x, sorted_y)
    return out


# ---------------------------------------------------------------------------
# Student t 分位数（`qt()`）：loess / lm 的置信带要用，不引入 scipy
# ---------------------------------------------------------------------------


def _betacf(a: float, b: float, x: float) -> float:
    """正则化不完全 Beta 的连分式（Numerical Recipes betacf）。"""
    max_iterations = 500
    eps = 3e-16
    tiny = 1e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, max_iterations + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """正则化不完全 Beta 函数 `I_x(a, b)`。"""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_beta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(log_beta + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def t_quantile(p: float, df: float) -> float:
    """Student t 的 `qt(p, df)`（双侧面积反解不完全 Beta）。"""
    if df is None or not math.isfinite(df) or df <= 0:
        return float("nan")
    if not (0.0 < p < 1.0):
        raise BuildError(f"t 分位数的概率必须在 (0, 1) 内，收到 {p!r}")
    if p == 0.5:
        return 0.0
    target = 2.0 * (1.0 - p)
    low, high = 0.0, 1.0
    for _ in range(200):
        mid = 0.5 * (low + high)
        if _betai(0.5 * df, 0.5, mid) > target:
            high = mid
        else:
            low = mid
    x = 0.5 * (low + high)
    return float(math.sqrt(df * (1.0 - x) / x))

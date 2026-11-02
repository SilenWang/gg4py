"""`ggcore.build` —— 图层流水线：`ggplot` + `Layer` → 「已算好的每层数据」。

六个阶段，每个阶段的中间列都能单独取出（测试与 R 对拍用）：

```
compute_aesthetics → compute_stat → map_statistic → compute_position → map_scales → finish
```

    build = build_plot(ggplot(mpg, aes(x="displ", y="hwy")) + geom_point())
    layer = build.layers[0]
    layer.aesthetics.names      # ("x", "y", "PANEL", "group")
    layer.data.names            # R `ggplot_build()$data[[1]]` 的列名与列序
    layer.scaled.column("x").values  # 第 5 阶段输出的 x（identity 下不变）

本模块只做「数据」：不产出 gtable、不画图、不碰 IR（M1-7 才把这里的结果送进 IR）。
口径全文见 `docs/notes/build.md`，要点：

- **数据优先级**：`layer.data` > `plot.data`；`inherit_aes=False` 时只用层自己的
  mapping，否则层 mapping 在前、plot mapping 补缺（上游 `computed_mapping` 的
  合并顺序，列序也按它走）。
- **缺省 aes** 从 `Geom.default_aes` 补，追加顺序 = spec 的键顺序（上游
  `use_defaults()` 的口径）；`required_aes` 缺失报 :class:`MissingAesError`，
  消息里列出缺哪一组。
- **缺失值**：按参与计算的 aes 逐列计数后整行删除；`na_rm=False` 时发
  :class:`BuildWarning`，不静默。
- **分组**：用 M1-2 的 `compute_groups()`（0 起），这里转成 ggplot2 内置数据的
  1 起编号；`group` 显式映射优先。
- **scale 接口先行**：映射全部经 :class:`ScaleSet`。本任务给 identity 实现
  （唯一的非恒等行为是「离散位置美学 → 1..n」，这是 ggplot2 默认离散位置标度
  做的事；真正的调色板 / 连续标度是 M1-4）。流水线里不写死任何线性映射。
- **空层**：0 行不报错，后续阶段给空表，`PlotBuild.empty_layers` 留记录。

边界：`src/ggcore` 只 import 标准库 + numpy + ggcore，所以数据必须是
:class:`ggcore.data.ColumnTable`；DataFrame-like 请先在包外转好
（`ggio.frame.to_column_table(df)`），本模块不 import pandas / Arrow。
"""

from __future__ import annotations

import ast
import warnings as _warnings
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import numpy as np

from ggcore.aes import Aes, AesSpec, as_aes
from ggcore.data import Column, ColumnTable
from ggcore.eval import NO_GROUP, compute_groups, eval_aes, eval_after_stat, parse_aes
from ggcore.layer import Layer
from ggcore.registry import required_aes_groups

if TYPE_CHECKING:  # 只用于类型标注，避免 build ↔ plot 的运行时环
    from ggcore.plot import ggplot

__all__ = [
    "STAGES",
    "Aesthetics",
    "BuildError",
    "BuildWarning",
    "LayerBuild",
    "MissingAesError",
    "PlotBuild",
    "ScaleSet",
    "build_layer",
    "build_plot",
    "compute_aesthetics",
    "compute_position",
    "compute_stat",
    "finish",
    "map_scales",
    "map_statistic",
]

#: 六个阶段的名字，顺序即流水线顺序（`LayerBuild.stages` 用同一套键）。
STAGES: tuple[str, ...] = (
    "compute_aesthetics",
    "compute_stat",
    "map_statistic",
    "compute_position",
    "map_scales",
    "finish",
)

#: 位置美学：只有它们会被离散位置标度编码成 1..n。
POSITION_AESTHETICS = frozenset({"x", "y", "xmin", "xmax", "ymin", "ymax", "xend", "yend"})

#: 0 行图层在 ggplot2 里走「空 data frame」路径：这里只留轨迹，不再算后续阶段。
_EMPTY = ColumnTable()

#: stat 自己补的缺省映射（上游 `Stat$default_aes`）：aesthetic → stat 输出列。
#: `stat_count` 的 `x = after_stat(count)` 不在此列：图层的 x 已经映射过了。
_STAT_DEFAULT_AES: Mapping[str, tuple[tuple[str, str], ...]] = MappingProxyType(
    {"count": (("y", "count"),)}
)

#: `geom_*` 里需要在 finish 阶段派生坐标列的几何（上游 `setup_data()`）。
_BAR_GEOMS = frozenset({"bar", "col", "histogram"})


class BuildError(ValueError):
    """流水线无法继续（未知 stat / position、数据形态不对等）。"""


class MissingAesError(BuildError):
    """`Geom.required_aes` 里有组在数据 / 参数里都没有。"""


class BuildWarning(UserWarning):
    """流水线里的非致命提示（目前只有「删除了含缺失值的行」）。"""


# ---------------------------------------------------------------------------
# 列工具
# ---------------------------------------------------------------------------


def _column_values(column: Column) -> np.ndarray:
    """列 → 计算用 ndarray：数值缺失写 NaN，离散缺失写 None（只读副本）。"""
    if column.kind in ("float", "int", "datetime", "timedelta"):
        values = np.array(column.values, copy=True)
        if column.na_mask.any():
            values[column.na_mask] = np.nan
        return values
    if column.kind == "bool":
        if not column.na_mask.any():
            return np.array(column.values, copy=True)
        values = column.values.astype(np.float64)
        values[column.na_mask] = np.nan
        return values
    if column.kind == "categorical":
        values = np.empty(column.size, dtype=object)
        if column.levels:
            values[:] = np.asarray(column.levels, dtype=object)[column.values]
        else:
            values[:] = None
        if column.na_mask.any():
            values[column.na_mask] = None
        return values
    values = np.asarray(column.values.tolist(), dtype=object)
    if column.na_mask.any():
        values[column.na_mask] = None
    return values


def _is_missing_array(values: np.ndarray) -> np.ndarray:
    """逐元素缺失判定（None / NaN）。"""
    if values.dtype.kind == "f":
        return np.isnan(values)
    if values.dtype.kind == "O":
        return np.array(
            [
                item is None or (isinstance(item, (float, np.floating)) and bool(np.isnan(item)))
                for item in values.tolist()
            ],
            dtype=bool,
        )
    return np.zeros(values.shape[0], dtype=bool)


def _column_from_values(values: Any) -> Column:
    """ndarray / 序列 → Column（带 kind 与 na_mask）。"""
    array = np.asarray(values)
    if array.ndim != 1:
        raise BuildError(f"aes 求值结果必须是 1 维数组，得到 {array.ndim} 维")
    kind = array.dtype.kind
    if kind == "b":
        return Column("bool", array)
    if kind in ("i", "u"):
        return Column("int", array)
    if kind == "f":
        missing = np.isnan(array)
        if missing.any():
            return Column("float", np.where(missing, 0.0, array), na_mask=missing)
        return Column("float", array)
    if kind in ("U", "S"):
        return Column("str", array)
    if kind == "O":
        items = array.tolist()
        if all(item is None or isinstance(item, str) for item in items):
            missing = np.array([item is None for item in items], dtype=bool)
            data = np.array(["" if item is None else item for item in items], dtype=object)
            return Column("str", data, na_mask=missing)
        missing = _is_missing_array(array)
        data = np.array(
            [0.0 if flag else float(item) for item, flag in zip(items, missing, strict=True)],
            dtype=np.float64,
        )
        return Column("float", data, na_mask=missing)
    raise BuildError(f"不支持的 aes 结果类型 {array.dtype}")


def _gather_column(column: Column, indices: np.ndarray) -> Column:
    """按行号取子集，保留 kind / levels / na_mask。"""
    return Column(
        column.kind,
        column.values[indices],
        levels=column.levels,
        na_mask=column.na_mask[indices],
    )


def _items(table: ColumnTable) -> Iterator[tuple[str, Column]]:
    return zip(table.names, table.columns(), strict=True)


def _length(table: ColumnTable) -> int:
    return table.nrows


def _bare_column_name(spec: AesSpec) -> str | None:
    """表达式就是「一列」时返回列名（保留源列的 kind / categorical levels）。"""
    if spec.tree is None or spec.constant:
        return None
    body = spec.tree.body
    if isinstance(body, ast.Name):
        return body.id
    if (
        isinstance(body, ast.Call)
        and isinstance(body.func, ast.Name)
        and body.func.id == "col"
        and len(body.args) == 1
        and isinstance(body.args[0], ast.Constant)
        and isinstance(body.args[0].value, str)
    ):
        return body.args[0].value
    return None


# ---------------------------------------------------------------------------
# ScaleSet（scale 接口先行；M1-4 用真实现替换）
# ---------------------------------------------------------------------------


class ScaleSet:
    """一组按 aesthetic 索引的标度；本任务是 identity 实现。

    `train(values, aesthetic)` 记录离散位置美学的水平顺序，`map(values,
    aesthetic)` 把离散位置编码成 1..n（ggplot2 默认离散位置标度的行为），其它
    美学原样返回。**流水线只调用这两个方法**，没有任何写死的线性映射，所以
    M1-4 换实现时 do not touch 流水线——`tests/test_build.py` 用自定义子类证明
    这一点。
    """

    def __init__(self) -> None:
        self._levels: dict[str, tuple[str, ...]] = {}

    @property
    def trained(self) -> Mapping[str, tuple[str, ...]]:
        """已训练的离散水平（只读视图）。"""
        return MappingProxyType(dict(self._levels))

    def levels(self, aesthetic: str) -> tuple[str, ...]:
        """某个美学已训练的水平；没有训练过就是空元组。"""
        return self._levels.get(aesthetic, ())

    def train(self, values: Any, aesthetic: str) -> None:
        """训练一列：只关心位置美学上的离散值。"""
        if aesthetic not in POSITION_AESTHETICS:
            return
        levels = _discrete_levels(values)
        if levels is None:
            return
        known = self._levels.get(aesthetic, ())
        merged = list(known)
        for level in levels:
            if level not in merged:
                merged.append(level)
        self._levels[aesthetic] = tuple(merged)

    def map(self, values: Any, aesthetic: str) -> Any:
        """映射一列：离散位置 → 1..n（缺失保持缺失），其它原样返回。"""
        if aesthetic not in POSITION_AESTHETICS:
            return values
        levels = _discrete_levels(values)
        if levels is None:
            return values
        ordered = self._levels.get(aesthetic) or levels
        number = {level: index + 1 for index, level in enumerate(ordered)}
        source = values if isinstance(values, Column) else None
        array = _column_values(values) if source is not None else np.asarray(values)
        missing = _is_missing_array(array)
        codes = np.zeros(array.shape[0], dtype=np.float64)
        for i, item in enumerate(array.tolist()):
            if missing[i]:
                continue
            codes[i] = number.get(item, np.nan)
        if source is not None:
            return Column("float", np.where(missing, 0.0, codes), na_mask=missing)
        codes[missing] = np.nan
        return codes


def _discrete_levels(values: Any) -> tuple[str, ...] | None:
    """离散值域（按值域顺序）；不是离散列返回 None。"""
    if isinstance(values, Column):
        if not values.is_discrete:
            return None
        if values.levels:
            return values.levels
        array = _column_values(values)
    else:
        array = np.asarray(values)
        if array.dtype.kind not in ("U", "S", "O"):
            return None
        if array.dtype.kind == "O" and not all(
            item is None or isinstance(item, str) for item in array.tolist()
        ):
            return None
    missing = _is_missing_array(array)
    present = {item for item, flag in zip(array.tolist(), missing, strict=True) if not flag}
    return tuple(sorted(present))


# ---------------------------------------------------------------------------
# 阶段 1：compute_aesthetics
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Aesthetics:
    """阶段 1 的产物：数据美学表 + 被推迟的 after_stat 映射。

    `dropped` 是「列名 → 该列缺失行数」，`notes` 是已经发出去的提示文本；
    `empty` 表示（删完缺失行之后）0 行——后续阶段走空表路径。
    """

    table: ColumnTable
    deferred: tuple[tuple[str, AesSpec], ...]
    dropped: Mapping[str, int]
    notes: tuple[str, ...]
    empty: bool


def _resolve_data(plot: ggplot, layer: Layer) -> ColumnTable:
    """`layer.data` > `plot.data`；只认列式表（pandas / Arrow 在包外转换）。"""
    data = layer.data if layer.data is not None else plot.data
    if isinstance(data, ColumnTable):
        return data
    if data is None:
        return ColumnTable()
    raise BuildError(
        f"图层数据必须是 ggcore.data.ColumnTable，收到 {type(data).__module__}."
        f"{type(data).__qualname__}；DataFrame-like 请先用 "
        "ggio.frame.to_column_table(...) 转换（ggcore 不 import pandas / Arrow）"
    )


def _resolve_mapping(plot: ggplot, layer: Layer) -> Aes:
    """层 mapping 在前，plot mapping 补缺；`inherit_aes=False` 只用层 mapping。"""
    merged: dict[str, Any] = dict(layer.mapping)
    if layer.inherit_aes:
        for name, value in plot.mapping.items():
            merged.setdefault(name, value)
    return as_aes(merged)


def compute_aesthetics(plot: ggplot, layer: Layer, index: int = 0) -> Aesthetics:
    """阶段 1：合并 mapping、求值数据美学、补 PANEL / group、删缺失行。

    返回的 `table` 列序 = 层/plot mapping 顺序（discard after_stat）→ `PANEL` →
    `group`（显式 group 留在 mapping 原位，与上游 `add_group()` 一致）。
    """
    table = _resolve_data(plot, layer)
    mapping = _resolve_mapping(plot, layer)
    nrows = table.nrows

    columns: list[tuple[str, Column]] = []
    deferred: list[tuple[str, AesSpec]] = []
    for name, expression in mapping.items():
        spec = parse_aes(expression)
        if spec.after_stat:
            deferred.append((name, spec))
            continue
        bare = _bare_column_name(spec)
        if bare is not None and bare in table:
            columns.append((name, table.column(bare)))
        else:
            columns.append((name, _column_from_values(eval_aes(spec, table, nrows=nrows))))

    # 分组：M1-2 给 0 起的 id，ggplot2 的内置数据是 1 起；NA 行保持 NO_GROUP。
    ids = compute_groups(mapping, table)
    group = Column("int", np.where(ids >= 0, ids + 1, NO_GROUP).astype(np.int64))
    group_position = next((i for i, (name, _) in enumerate(columns) if name == "group"), None)
    if group_position is None:
        columns.append(("PANEL", Column("str", np.full(nrows, "1", dtype=str))))
        columns.append(("group", group))
    else:
        columns[group_position] = ("group", group)
        columns.append(("PANEL", Column("str", np.full(nrows, "1", dtype=str))))

    # 缺失值：逐列计数，再整行删除（参与计算的列 = 除 PANEL / group 外全部）。
    counts: dict[str, int] = {}
    for name, column in columns:
        if name in ("PANEL", "group"):
            continue
        missing = int(column.na_count)
        if missing:
            counts[name] = missing
    keep = np.ones(nrows, dtype=bool)
    for name, column in columns:
        if name in ("PANEL", "group"):
            continue
        keep &= ~column.na_mask
    dropped_rows = int((~keep).sum())
    notes: list[str] = []
    if dropped_rows:
        detail = "，".join(f"{name}: {count}" for name, count in counts.items())
        geom = f"geom_{layer.geom.name}"
        message = f"layer[{index}]（{geom}）删除了 {dropped_rows} 行含缺失值的观测（{detail}）"
        notes.append(message)
        if not bool(layer.params.get("na_rm", False)):
            _warnings.warn(message, BuildWarning, stacklevel=4)
        columns = [(name, _gather_column(column, keep)) for name, column in columns]

    notes_tuple = tuple(notes)
    remaining = int(keep.sum())
    return Aesthetics(
        table=ColumnTable(columns, nrows=remaining),
        deferred=tuple(deferred),
        dropped=MappingProxyType(counts),
        notes=notes_tuple,
        empty=remaining == 0,
    )


# ---------------------------------------------------------------------------
# 阶段 2：compute_stat
# ---------------------------------------------------------------------------


def compute_stat(layer: Layer, aesthetics: Aesthetics) -> ColumnTable:
    """阶段 2：按 `layer.stat.name` 算统计量。

    本任务实现 `identity` 与 `count`；`bin` / `boxplot` / `smooth` / `align`
    留给 M1-8（报错会点名，不静默当成 identity）。
    """
    if aesthetics.empty:
        return _EMPTY
    name = layer.stat.name
    if name == "identity":
        return aesthetics.table
    if name == "count":
        return _stat_count(aesthetics.table)
    raise BuildError(f"stat {name!r} 尚未实现（M1-8）；M1-3 只实现 identity / count")


def _stat_count(table: ColumnTable) -> ColumnTable:
    """`stat_count`：每个分组内按 x 汇总计数（上游 `StatCount$compute_group`）。"""
    if "x" not in table or "group" not in table:
        raise BuildError("stat_count 需要 x 与 group 两列（数据阶段没有映射 x？）")
    x_column = table.column("x")
    x_values = _column_values(x_column)
    weight = (
        _column_values(table.column("weight")).astype(np.float64)
        if "weight" in table
        else np.ones(table.nrows, dtype=np.float64)
    )
    groups = _column_values(table.column("group")).astype(np.int64)

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
        for name, column in _items(table):
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
        result.append(("x", _gather_column(x_column, picked_all)))
    else:
        result.append(("x", _gather_column(x_column, np.zeros(0, dtype=np.int64))))
    result.append(("flipped_aes", Column("bool", np.zeros(total, dtype=bool))))
    for name, column in _items(table):
        if name == "x" or name not in frames[0]:
            continue
        # 常量列取每个组的代表行（组内值相同，取哪一行都一样）。
        source_rows = np.concatenate(
            [
                np.full(len(f["count"]), f["x_rows"][0] if f["x_rows"] else 0, dtype=np.int64)
                for f in frames
            ]
        )
        result.append((name, _gather_column(column, source_rows)))
    return ColumnTable(result, nrows=total)


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
# 阶段 3：map_statistic
# ---------------------------------------------------------------------------


def map_statistic(layer: Layer, statistic: ColumnTable, aesthetics: Aesthetics) -> ColumnTable:
    """阶段 3：把 `after_stat(...)` 与 stat 的缺省映射落成美学列（追加在末尾）。"""
    if aesthetics.empty:
        return _EMPTY
    stat_values = {name: _column_values(column) for name, column in _items(statistic)}
    columns = list(_items(statistic))
    nrows = statistic.nrows

    for name, spec in aesthetics.deferred:
        try:
            values = eval_after_stat(spec, stat_values, nrows=nrows)
        except Exception as exc:
            raise BuildError(f"after_stat({spec.source}) 求值失败：{exc}") from exc
        columns = _put(columns, name, _column_from_values(values))

    for name, source in _STAT_DEFAULT_AES.get(layer.stat.name, ()):
        if name in dict(columns) or any(name == key for key, _ in aesthetics.deferred):
            continue
        if source not in stat_values:
            raise BuildError(
                f"stat {layer.stat.name!r} 的缺省映射 {name} = after_stat({source}) 找不到"
                f"统计量 {source!r}；stat 输出列：{', '.join(stat_values)}"
            )
        columns = _put(columns, name, _column_from_values(stat_values[source]))
    return ColumnTable(columns, nrows=nrows)


def _put(columns: list[tuple[str, Column]], name: str, column: Column) -> list[tuple[str, Column]]:
    """已有同名列就原位替换，否则追加到末尾（R 的 `data[names] <- ...` 语义）。"""
    for position, (key, _) in enumerate(columns):
        if key == name:
            columns[position] = (name, column)
            return columns
    columns.append((name, column))
    return columns


# ---------------------------------------------------------------------------
# 阶段 4：compute_position
# ---------------------------------------------------------------------------


def compute_position(layer: Layer, mapped: ColumnTable, index: int = 0) -> ColumnTable:
    """阶段 4：位置调整。本任务实现 `identity` 与 `stack`。

    `stack` 按 x 分组把 y 反向累加（上游 `collide(reverse = FALSE)`：第一个
    group 在最上面），同时写 `ymin` / `ymax`，并把 `y` 设成 `ymax`；x 没有重复
    值时和上游一样退化成 identity（只由 finish 的 geom setup 补锚点）。
    """
    if mapped.nrows == 0:
        return _EMPTY
    name = layer.position.name
    if name == "identity":
        return mapped
    if name == "stack":
        return _position_stack(mapped, layer.position.params)
    raise BuildError(
        f"position {name!r} 尚未实现；M1-3 只实现 identity / stack"
        '（boxplot 的 dodge2 请显式写 position="identity" 或等后续任务）'
    )


def _position_stack(table: ColumnTable, params: Mapping[str, Any]) -> ColumnTable:
    if "y" not in table or "x" not in table:
        raise BuildError("position_stack 需要 x 与 y 两列")
    x_values = _column_values(table.column("x"))
    y_values = _column_values(table.column("y")).astype(np.float64)
    x_keys = [repr(item) for item in x_values.tolist()]
    if len(set(x_keys)) == len(x_keys):
        return table

    group = (
        _column_values(table.column("group")).astype(np.int64)
        if "group" in table
        else np.zeros(table.nrows, dtype=np.int64)
    )
    vjust = float(params.get("vjust", 1.0))
    ymin = np.zeros(table.nrows, dtype=np.float64)
    ymax = np.zeros(table.nrows, dtype=np.float64)
    for key in dict.fromkeys(x_keys):
        rows = np.array([i for i, item in enumerate(x_keys) if item == key], dtype=np.int64)
        rows = rows[np.argsort(-group[rows], kind="stable")]
        for subset in (rows[y_values[rows] >= 0], rows[y_values[rows] < 0]):
            if subset.size == 0:
                continue
            heights = np.cumsum(y_values[subset])
            ymin[subset] = heights - y_values[subset]
            ymax[subset] = heights
    y = (1.0 - vjust) * ymin + vjust * ymax
    columns = list(_items(table))
    columns = _put(columns, "ymin", Column("float", ymin))
    columns = _put(columns, "ymax", Column("float", ymax))
    columns = _put(columns, "y", Column("float", y))
    return ColumnTable(columns, nrows=table.nrows)


# ---------------------------------------------------------------------------
# 阶段 5：map_scales
# ---------------------------------------------------------------------------


def map_scales(scales: ScaleSet, positioned: ColumnTable) -> ColumnTable:
    """阶段 5：逐列过 `ScaleSet.map`（本任务 identity；离散位置 → 1..n）。"""
    if positioned.nrows == 0:
        return _EMPTY
    columns: list[tuple[str, Column]] = []
    for name, column in _items(positioned):
        mapped = scales.map(column, name)
        columns.append(
            (name, mapped if isinstance(mapped, Column) else _column_from_values(mapped))
        )
    return ColumnTable(columns, nrows=positioned.nrows)


# ---------------------------------------------------------------------------
# 阶段 6：finish
# ---------------------------------------------------------------------------


def finish(layer: Layer, scaled: ColumnTable, index: int = 0) -> ColumnTable:
    """阶段 6：补齐 geom 派生的坐标列与 `default_aes`，得到 ggplot2 内置数据。

    顺序照上游：`required_aes` 校验 → `Geom$setup_data()`（bar/col/histogram 的
    `ymin/ymax/xmin/xmax`、boxplot 的 `flipped_aes/xmin/xmax`）→
    `Geom$use_defaults()`（按 spec 键顺序追加）。
    """
    if scaled.nrows == 0:
        return _EMPTY
    _check_required_aes(layer, scaled, index)
    columns = _geom_setup(layer, scaled)
    for name, value in layer.geom.default_aes.items():
        if name in dict(columns):
            continue
        columns = _put(columns, name, _default_column(value, scaled.nrows))
    return ColumnTable(columns, nrows=scaled.nrows)


def _check_required_aes(layer: Layer, table: ColumnTable, index: int) -> None:
    missing: list[str] = []
    for alternatives in required_aes_groups(layer.geom.required_aes):
        if not any(name in table or name in layer.params for name in alternatives):
            missing.append("|".join(alternatives))
    if missing:
        raise MissingAesError(
            f"layer[{index}]（geom_{layer.geom.name}）缺少必需的美学："
            + "，".join(missing)
            + f"；已有列：{', '.join(table.names)}"
        )


def _geom_setup(layer: Layer, table: ColumnTable) -> list[tuple[str, Column]]:
    """上游 `Geom$setup_data()` 里对最终数据有影响的部分。"""
    columns = list(_items(table))
    name = layer.geom.name
    nrows = table.nrows

    if name in _BAR_GEOMS:
        columns = _put(columns, "flipped_aes", Column("bool", np.zeros(nrows, dtype=bool)))
        y = _column_values(table.column("y")).astype(np.float64) if "y" in table else None
        if y is not None and "ymin" not in dict(columns):
            columns = _put(columns, "ymin", Column("float", np.minimum(y, 0.0)))
        if y is not None and "ymax" not in dict(columns):
            columns = _put(columns, "ymax", Column("float", np.maximum(y, 0.0)))
        width = _width(layer, table)
        x = _column_values(table.column("x")).astype(np.float64)
        just = float(layer.params.get("just", 0.5))
        if "xmin" not in dict(columns):
            columns = _put(columns, "xmin", Column("float", x - width * just))
        if "xmax" not in dict(columns):
            columns = _put(columns, "xmax", Column("float", x + width * (1.0 - just)))
        # 上游 setup_data 在算完 xmin/xmax 后把 width / just 去掉，缺省 width 由
        # use_defaults 在末尾补回来（列序与 R 一致）。
        columns = [(key, column) for key, column in columns if key not in ("width", "just")]
    elif name == "boxplot":
        columns = _put(columns, "flipped_aes", Column("bool", np.zeros(nrows, dtype=bool)))
        width = _width(layer, table)
        x = _column_values(table.column("x")).astype(np.float64)
        if "xmin" not in dict(columns):
            columns = _put(columns, "xmin", Column("float", x - width / 2.0))
        if "xmax" not in dict(columns):
            columns = _put(columns, "xmax", Column("float", x + width / 2.0))
        columns = [(key, column) for key, column in columns if key != "width"]
    return columns


def _width(layer: Layer, table: ColumnTable) -> np.ndarray | float:
    """柱/箱宽度：映射列 > 层参数 > geom 缺省。"""
    if "width" in table:
        return _column_values(table.column("width")).astype(np.float64)
    if "width" in layer.params:
        return float(layer.params["width"])
    return float(layer.geom.default_aes.get("width", 0.9))


def _default_column(value: Any, nrows: int) -> Column:
    """`default_aes` 的静态值 → 列（标量广播；`None` 是整列缺失）。"""
    if value is None:
        return Column("float", np.zeros(nrows), na_mask=np.ones(nrows, dtype=bool))
    if isinstance(value, (bool, np.bool_)):
        return Column("bool", np.full(nrows, bool(value), dtype=bool))
    if isinstance(value, str):
        return Column("str", np.array([value] * nrows, dtype=object))
    if isinstance(value, (int, np.integer)):
        return Column("int", np.full(nrows, int(value)))
    if isinstance(value, (float, np.floating)):
        return Column("float", np.full(nrows, float(value)))
    raise BuildError(f"default_aes 的值 {value!r} 不是标量，M1-3 不支持逐行缺省值")


# ---------------------------------------------------------------------------
# 组装：LayerBuild / PlotBuild
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LayerBuild:
    """一层的数据：六个阶段各一张表，外加缺失值 / 空层记录。"""

    index: int
    geom: str
    stat: str
    position: str
    aesthetics: ColumnTable
    statistic: ColumnTable
    mapped: ColumnTable
    positioned: ColumnTable
    scaled: ColumnTable
    data: ColumnTable
    dropped_missing: Mapping[str, int]
    empty: bool
    notes: tuple[str, ...]

    @property
    def stages(self) -> Mapping[str, ColumnTable]:
        """阶段名 → 该阶段输出的表（顺序同 :data:`STAGES`）。"""
        return MappingProxyType(
            {
                "compute_aesthetics": self.aesthetics,
                "compute_stat": self.statistic,
                "map_statistic": self.mapped,
                "compute_position": self.positioned,
                "map_scales": self.scaled,
                "finish": self.data,
            }
        )

    @property
    def nrows(self) -> int:
        return self.data.nrows


@dataclass(frozen=True, slots=True)
class PlotBuild:
    """整张图的构建结果：按层顺序，外加训练好的标度与提示。"""

    layers: tuple[LayerBuild, ...]
    scales: ScaleSet
    warnings: tuple[str, ...]

    @property
    def empty_layers(self) -> tuple[int, ...]:
        """0 行、被跳过但留下记录了的图层下标。"""
        return tuple(layer.index for layer in self.layers if layer.empty)


@dataclass(frozen=True, slots=True)
class _Stages:
    index: int
    layer: Layer
    aesthetics: Aesthetics
    statistic: ColumnTable
    mapped: ColumnTable
    positioned: ColumnTable


def _compute_stages(plot: ggplot, layer: Layer, index: int) -> _Stages:
    aesthetics = compute_aesthetics(plot, layer, index)
    statistic = compute_stat(layer, aesthetics)
    mapped = map_statistic(layer, statistic, aesthetics)
    positioned = compute_position(layer, mapped, index)
    return _Stages(index, layer, aesthetics, statistic, mapped, positioned)


def _assemble(stages: _Stages, scales: ScaleSet) -> LayerBuild:
    layer = stages.layer
    scaled = map_scales(scales, stages.positioned)
    data = finish(layer, scaled, stages.index)
    return LayerBuild(
        index=stages.index,
        geom=layer.geom.name,
        stat=layer.stat.name,
        position=layer.position.name,
        aesthetics=stages.aesthetics.table,
        statistic=stages.statistic,
        mapped=stages.mapped,
        positioned=stages.positioned,
        scaled=scaled,
        data=data,
        dropped_missing=stages.aesthetics.dropped,
        empty=stages.aesthetics.empty,
        notes=stages.aesthetics.notes,
    )


def build_layer(
    plot: ggplot,
    layer: Layer,
    index: int = 0,
    scales: ScaleSet | None = None,
) -> LayerBuild:
    """构建单层（六阶段全走一遍）。

    `scales` 给出时复用调用方的标度（本函数仍会用这一层的列训练它）；不给就
    新建一个。跨层联合训练请用 :func:`build_plot`。
    """
    if scales is None:
        scales = ScaleSet()
    stages = _compute_stages(plot, layer, index)
    for name, column in _items(stages.positioned):
        scales.train(column, name)
    return _assemble(stages, scales)


def build_plot(plot: ggplot) -> PlotBuild:
    """按层顺序构建整张图；**本任务不产出 gtable / 不出图**。

    标度先在所有层上训练，再统一映射（上游 `scales$train_df(data)` 的口径），
    所以同一离散 x 在不同层里得到同一套 1..n 编码。
    """
    scales = ScaleSet()
    stages = [_compute_stages(plot, layer, index) for index, layer in enumerate(plot.layers)]
    for stage in stages:
        for name, column in _items(stage.positioned):
            scales.train(column, name)
    builds = tuple(_assemble(stage, scales) for stage in stages)
    notes = tuple(note for build in builds for note in build.notes)
    return PlotBuild(layers=builds, scales=scales, warnings=notes)

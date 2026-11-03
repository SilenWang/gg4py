"""`ggcore.build` —— 图层流水线：`ggplot` + `Layer` → 「已算好的每层数据」。

六个阶段，每个阶段的中间列都能单独取出（测试与 R 对拍用）：

```
compute_aesthetics → compute_stat → map_statistic → compute_position → map_scales → finish
```

    build = build_plot(ggplot(mpg, aes(x="displ", y="hwy")) + geom_point())
    layer = build.layers[0]
    layer.aesthetics.names      # ("x", "y", "PANEL", "group")
    layer.data.names            # R `ggplot_build()$data[[1]]` 的列名与列序
    layer.scaled.column("x").values  # 第 5 阶段输出的 x（标度变换后的空间）

本模块只做「数据」：不产出 gtable、不画图、不碰 IR（M1-7 才把这里的结果送进 IR）。
口径全文见 `docs/notes/build.md`，要点：

- **数据优先级**：`layer.data` > `plot.data`；`inherit_aes=False` 时只用层自己的
  mapping，否则层 mapping 在前、plot mapping 补缺（上游 `computed_mapping` 的
  合并顺序，列序也按它走）。
- **缺省 aes** 从 `Geom.default_aes` 补，追加顺序 = spec 的键顺序（上游
  `use_defaults()` 的口径）；`required_aes` 缺失报 :class:`MissingAesError`，
  消息里列出缺哪一组。
- **缺失值**：按参与计算的 aes 逐列计数（`LayerBuild.dropped_missing`），
  **行保留**——ggplot2 4.0.3 的 `$data` 不删 NA 行，删除在绘制期
  `Geom$handle_na()`（M1-7）。
- **分组**：用 M1-2 的 `compute_groups()`（0 起），这里转成 ggplot2 内置数据的
  1 起编号；`group` 显式映射优先。
- **标度**：映射全部经 :class:`ggcore.scales.ScaleSet`（M1-4）。`plot.scales`
  里的显式标度优先，其余按列类型解析成默认标度；位置数据在训练前先过
  `transform_scales()`（上游 `scales$transform_df()`），第二段训练用 position
  之后的数据。流水线里不写死任何线性映射（`tests/test_build.py` 用自定义子类
  证明）。
- **空层**：0 行不报错，后续阶段给空表，`PlotBuild.empty_layers` 留记录。

边界：`src/ggcore` 只 import 标准库 + numpy + ggcore，所以数据必须是
:class:`ggcore.data.ColumnTable`；DataFrame-like 请先在包外转好
（`ggio.frame.to_column_table(df)`），本模块不 import pandas / Arrow。
"""

from __future__ import annotations

import ast
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import numpy as np

from ggcore.aes import Aes, AesSpec, as_aes
from ggcore.coord import (
    CoordBase,
    PanelParams,
    coord_from_component,
    count_dropped,
    count_out_of_bounds,
    count_rows_dropped,
)
from ggcore.data import Column, ColumnTable
from ggcore.eval import NO_GROUP, compute_groups, eval_aes, eval_after_stat, parse_aes
from ggcore.facet import (
    FacetBase,
    FacetLayout,
    PanelScales,
    PanelScaleSet,
    facet_from_component,
)
from ggcore.layer import Layer, Position
from ggcore.registry import construct, registered, required_aes_groups
from ggcore.scales import ScaleSet

if TYPE_CHECKING:  # 只用于类型标注，避免 build ↔ plot 的运行时环
    from ggcore.plot import ggplot

__all__ = [
    "STAGES",
    "Aesthetics",
    "BuildError",
    "BuildWarning",
    "LayerBuild",
    "MissingAesError",
    "PanelBuild",
    "PanelScaleSet",
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
#: `StatCount` / `StatBin` 同时给了 `x` 与 `y`（都指向 `after_stat(count)`）：
#: 竖向柱补 `y`，横向柱（`flipped_aes`）补 `x`；缺哪个补哪个，顺序不变。
_STAT_DEFAULT_AES: Mapping[str, tuple[tuple[str, str], ...]] = MappingProxyType(
    {
        "count": (("x", "count"), ("y", "count")),
        "bin": (("x", "count"), ("y", "count")),
        # M2-7 长尾 B：geom_count / geom_bin_2d / geom_hex / geom_density /
        # geom_qq / geom_contour_filled 的 `Stat$default_aes`（与下面 M2-6 的
        # 同名列合并成一份表；两边取值一致，`contour_filled` 用带 `order` 的版本）。
        "sum": (("size", "n"),),
        "bin2d": (("fill", "count"),),
        "bin_2d": (("fill", "count"),),
        "binhex": (("fill", "count"),),
        "bin_hex": (("fill", "count"),),
        "summary_2d": (("fill", "value"),),
        "summary_hex": (("fill", "value"),),
        "density": (("x", "density"), ("y", "density")),
        "contour": (("order", "level"),),
        "contour_filled": (("order", "level"), ("fill", "level")),
        # `stat_density_2d` 的链式 contour **不经过** map_statistic()：密度族即使
        # 做了等值线也不会有 `order` 列（上游 `StatDensity2d$compute_layer()`）。
        "density_2d": (),
        "density_2d_filled": (("fill", "level"),),
        # M2-6 的长尾 stat（`ggcore.stat_longtail.DEFAULT_AES` 的同一份表；
        # 这里内联是因为 build 在 import 期不能反向 import stat_longtail）。
        "qq": (("x", "theoretical"), ("y", "sample")),
        "ecdf": (("x", "ecdf"), ("y", "ecdf")),
    }
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
# 阶段 1：compute_aesthetics
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Aesthetics:
    """阶段 1 的产物：数据美学表 + 被推迟的 after_stat 映射。

    `dropped` 是「列名 → 该列缺失行数」（**只是计数，行不删**）；`notes` 是
    已经发出去的提示文本；`empty` 表示 0 行——后续阶段走空表路径。
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


def compute_aesthetics(
    plot: ggplot,
    layer: Layer,
    index: int = 0,
    *,
    panels: Any = None,
    data_table: ColumnTable | None = None,
) -> Aesthetics:
    """阶段 1：合并 mapping、求值数据美学、补 PANEL / group、统计缺失。

    返回的 `table` 列序 = 层/plot mapping 顺序（after_stat 的不进表）→ `PANEL` →
    `group`（显式 group 留在 mapping 原位，与上游 `add_group()` 一致）。
    缺失行**不删除**，只记进 `dropped_missing`；`build` 会在这一步之后调用
    :func:`map_position` 做位置标度的第一次编码。

    `panels` 是每行的 PANEL（1 起；分面时由 `FacetBase.map_data` 给出）。
    不给时与 M1-3 完全一致：整层写 `"1"`（单面板的字节不变）。
    """
    table = _resolve_data(plot, layer) if data_table is None else data_table
    # 上游 `stat_function()` 的 `checks`：空数据补一行 `group = 1`
    # （`ensure_nonempty_data()`），否则 0 行会在阶段 2 之前被短路掉。
    if table.nrows == 0 and layer.stat.name == "function":
        table = ColumnTable([("group", Column("int", np.array([1.0])))], nrows=1)
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

    # 分组：M1-2 给 0 起的 id，ggplot2 的内置数据是 1 起。NA 也是一个水平，
    # 所以只有「没有任何离散 aes」时才是 NO_GROUP。
    ids = compute_groups(mapping, table)
    group = Column("int", np.where(ids >= 0, ids + 1, NO_GROUP).astype(np.int64))
    if panels is None:
        panel_column = Column("str", np.full(nrows, "1", dtype=str))
    else:
        values = np.asarray(panels, dtype=np.int64)
        if values.shape != (nrows,):
            raise BuildError(f"panels 长度 {values.shape} 与数据行数 {nrows} 不符")
        panel_column = Column("str", np.array([str(int(value)) for value in values], dtype=str))
    group_position = next((i for i, (name, _) in enumerate(columns) if name == "group"), None)
    if group_position is None:
        columns.append(("PANEL", panel_column))
        columns.append(("group", group))
    else:
        columns[group_position] = ("group", group)
        columns.append(("PANEL", panel_column))

    # 缺失值：**只统计、不删行**。ggplot2 4.0.3 的 `$data` 保留 NA 行，删除
    # 发生在绘制期 `Geom$handle_na()`（只看 required_aes + non_missing_aes），
    # 由 M1-7 负责发 "Removed N rows" 的 warning。
    counts: dict[str, int] = {}
    for name, column in columns:
        if name in ("PANEL", "group"):
            continue
        missing = int(column.na_count)
        if missing:
            counts[name] = missing

    return Aesthetics(
        table=ColumnTable(columns, nrows=nrows),
        deferred=tuple(deferred),
        dropped=MappingProxyType(counts),
        notes=(),
        empty=nrows == 0,
    )


def transform_scales(scales: ScaleSet, aesthetics: Aesthetics) -> Aesthetics:
    """阶段 1 与「第一次位置训练」之间：位置数据先做变换。

    上游 `build_ggplot()` 在 `compute_aesthetics()` 之后、`train_position()`
    之前调用 `scales$transform_df(data)`。所以 `scale_x_log10()` 训练到的是
    `log10(x)`，`$data$x` 也是 log10 空间的值（x = 1/10/100 → 0/1/2）。
    没有变换的标度（identity）原样通过。
    """
    if aesthetics.table.nrows == 0:
        return aesthetics
    return replace(aesthetics, table=scales.transform_table(aesthetics.table))


def map_position(scales: ScaleSet, aesthetics: Aesthetics) -> Aesthetics:
    """阶段 1 与阶段 2 之间：位置标度的第一次映射。

    上游 `build_ggplot()` 在 `compute_aesthetics()` 之后立刻
    `layout$train_position()` + `layout$map_position()`，所以 stat 拿到的 x/y
    已经是位置值（离散 → 1..n，NA → 最后一个水平；连续 → 变换后的值）。
    `layout$map_position()` 只碰位置美学，colour / fill 等留到阶段 5。
    """
    return replace(aesthetics, table=_map_position_table(scales, aesthetics.table))


def _map_position_table(scales: ScaleSet, table: ColumnTable) -> ColumnTable:
    if table.nrows == 0:
        return _EMPTY
    return ColumnTable(
        [
            (name, _as_column(scales.map(column, name)) if name in POSITION_AESTHETICS else column)
            for name, column in _items(table)
        ],
        nrows=table.nrows,
    )


def _as_column(value: Any) -> Column:
    """`ScaleSet.map` 的结果统一成 Column。"""
    return value if isinstance(value, Column) else _column_from_values(value)


def _train(scales: ScaleSet, table: ColumnTable) -> None:
    for name, column in _items(table):
        scales.train(column, name)


# ---------------------------------------------------------------------------
# 阶段 2：compute_stat
# ---------------------------------------------------------------------------


def compute_stat(
    layer: Layer,
    aesthetics: Aesthetics,
    *,
    scales: Any = None,
    raw: ColumnTable | None = None,
) -> ColumnTable:
    """阶段 2：按 `layer.stat.name` 算统计量（实现见 :mod:`ggcore.stat`）。

    `identity` 原样通过；`bin` / `count` / `boxplot` / `smooth` / `align` 交给
    `ggcore.stat.compute_stat()`。`scales` 是这一面板的 `ScaleSet`（`stat_bin`
    的断点、`stat_smooth(fullrange = TRUE)` 的范围要用），`raw` 是位置标度映射
    之前的美学表（横向判定用 `is_mapped_discrete()`）。不认识的名字报错并列出
    已实现的 stat，不静默当成 identity。
    """
    if aesthetics.empty:
        return _EMPTY
    from ggcore.stat import compute_stat as _compute

    return _compute(layer, aesthetics, scales=scales, raw=raw)


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
            # 空图层（例如等值线一层都没生成）：没有统计量可映射，列也就没有。
            if nrows == 0:
                continue
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


def compute_position(
    layer: Layer,
    mapped: ColumnTable,
    index: int = 0,
    raw: ColumnTable | None = None,
) -> ColumnTable:
    """阶段 4：geom 派生的坐标列 + 位置调整。

    顺序照上游：`required_aes` 校验 → `Geom$setup_data()` → `Position$compute_layer()`。
    `setup_data()` 在 `compute_position()` **之前**，所以 `flipped_aes` /
    `xmin` / `xmax` / `ymin` / `ymax` 的列序与 R 一致；stage 输出
    （`LayerBuild.positioned`）已经包含这些列。

    位置调整本身在 :mod:`ggcore.position`（`identity` / `stack` / `fill` /
    `dodge` / `dodge2` / `jitter` / `nudge`）。这里**按名字查注册表**拿到实现，
    所以 `geom_col(position="dodge")` 与 `p + position_dodge()` 走同一条路：
    换掉注册项，两条路径同时变（`tests/test_position.py` 守着）。

    `line` 的 `setup_data()` 还会按 `(PANEL, group, x)` 重排行序（上游
    `GeomLine$setup_data()`），路径的连接顺序由它决定。
    """
    if mapped.nrows == 0:
        return _EMPTY
    _check_required_aes(layer, mapped, index)
    columns = _geom_setup(layer, mapped, raw)
    # `setup_data()` 可以改变行数（`geom_dotplot` 按 `count` 展开成点），所以行数
    # 取 setup 之后的结果，不是 `mapped.nrows`。
    nrows = int(columns[0][1].size) if columns else 0
    table = ColumnTable(columns, nrows=nrows)
    position = _resolve_position(layer.position)
    return position.compute_layer(table)


def _resolve_position(position: Position) -> Any:
    """`Position`（名字 + 参数）→ 注册表里的可执行实现。

    注册项是 `position_*` 的构造器（返回 :class:`ggcore.position.Position*` 的
    子类实例），参数在这里重新过一遍构造器：与直接调用 `position_dodge(...)`
    同源，也顺带做参数校验。
    """
    name = position.name
    try:
        impl = construct("position", name, **dict(position.params))
    except LookupError:
        raise BuildError(
            f"position {name!r} 未注册；可用：{', '.join(registered('position'))}"
        ) from None
    except (TypeError, ValueError) as exc:
        raise BuildError(f"position {name!r} 的参数不对：{exc}") from exc
    compute = getattr(impl, "compute_layer", None)
    if not callable(compute):
        raise BuildError(
            f"position {name!r} 的注册项 {type(impl).__name__} 没有 compute_layer()；"
            "位置实现必须提供 compute_layer(data, params=None)"
        )
    return impl


# ---------------------------------------------------------------------------
# 阶段 5：map_scales
# ---------------------------------------------------------------------------


def map_scales(scales: ScaleSet, positioned: ColumnTable) -> ColumnTable:
    """阶段 5：逐列过 `ScaleSet.map`（连续位置 = trans 空间 + oob censor；
    离散位置 → 1..n；colour / fill / size / alpha / shape = 调色板 / rescale）。"""
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
    """阶段 6：补 `default_aes` 与 `geom_*(...)` 的字面参数，得到 ggplot2 内置数据。

    顺序照上游 `Geom$use_defaults()`：

    1. 先按 `default_aes` 的键序补缺失列（列序就是从这一步来的）；
    2. 再把 `intersect(geom$ aesthetics(), names(params))` 的层参数写回 data
       （`geom_point(colour = "red", size = 3)` / `geom_bar(fill = "steelblue")`
       / `geom_col(width = 0.3)`）：已有列原位覆盖，没有的列追加到末尾。
    """
    if scaled.nrows == 0:
        return _EMPTY
    columns = list(_items(scaled))
    for name, value in layer.geom.default_aes.items():
        if name in dict(columns):
            continue
        columns = _put(columns, name, _default_column(value, scaled.nrows))
    for name, value in _aes_params(layer).items():
        columns = _put(columns, name, _value_column(value, scaled.nrows))
    return ColumnTable(columns, nrows=scaled.nrows)


def _geom_aesthetics(geom: Any) -> tuple[str, ...]:
    """`Geom$aesthetics()`：required_aes 展开 + default_aes 名字 + group。"""
    names: list[str] = []
    for alternatives in required_aes_groups(geom.required_aes):
        names.extend(alternatives)
    names.extend(geom.default_aes)
    names.extend(getattr(geom, "optional_aes", ()))
    names.append("group")
    return tuple(dict.fromkeys(names))


def _aes_params(layer: Layer) -> dict[str, Any]:
    """层参数里属于「几何美学」的部分（上游 `aes_params`）。"""
    allowed = set(_geom_aesthetics(layer.geom))
    return {name: value for name, value in layer.params.items() if name in allowed}


def _value_column(value: Any, nrows: int) -> Column:
    """层参数的取值 → 列：标量 / 长度 1 广播，长度 n 逐行，`None` 整列缺失。"""
    if value is None:
        return _default_column(None, nrows)
    if isinstance(value, (bool, np.bool_, str)):
        return _default_column(value, nrows)
    if isinstance(value, (int, float, np.integer, np.floating)):
        # R 的 aes 参数是 double（`geom_point(size = 3)` 的 size 是 3，不是 3L）。
        return Column("float", np.full(nrows, float(value)))
    array = np.asarray(value)
    if array.ndim == 0:
        return _default_column(array.item(), nrows)
    if array.ndim != 1:
        raise BuildError(f"geom 参数必须是标量或一维数组，得到 {array.ndim} 维")
    if array.size == 1:
        return _default_column(array[0], nrows)
    if array.size != nrows:
        raise BuildError(f"geom 参数长度 {array.size} 与数据行数 {nrows} 不符")
    return _column_from_values(array)


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


def _geom_setup(
    layer: Layer, table: ColumnTable, raw: ColumnTable | None = None
) -> list[tuple[str, Column]]:
    """上游 `Geom$setup_data()`：按 geom 名查 `ggcore.geom` 的实现（M1-7）。

    `raw` 是位置标度映射**之前**的美学表：离散位置那时的 kind 还是 str /
    categorical，geom 的 `setup_params()` 用它复现 R 的 `is_mapped_discrete()`
    判断（横向 bar / boxplot 的 `flipped_aes`）。
    """
    geom_params = layer.geom.setup_params(table, layer.params, raw=raw)
    data = layer.geom.setup_data(table, geom_params)
    return list(_items(data))


def _legacy_geom_setup(layer: Layer, table: ColumnTable) -> list[tuple[str, Column]]:
    """M1-3 的旧实现（保留给对照测试；生产路径走 :func:`_geom_setup`）。"""
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
    elif name == "line":
        # GeomLine$setup_data(): flipped_aes + 按 (PANEL, group, x) 重排行序。
        columns = _put(columns, "flipped_aes", Column("bool", np.zeros(nrows, dtype=bool)))
        columns = _sorted(columns, table)
    return columns


def _sorted(columns: list[tuple[str, Column]], table: ColumnTable) -> list[tuple[str, Column]]:
    """按 `(PANEL, group, x)` 稳定排序（上游 `order(data$PANEL, data$group, data$x)`）。"""
    keys = [
        _column_values(table.column("x")).astype(np.float64),
        _column_values(table.column("group")).astype(np.float64),
        _column_values(table.column("PANEL")),
    ]
    order = np.lexsort(keys)
    return [(name, _gather_column(column, order)) for name, column in columns]


def _width(layer: Layer, table: ColumnTable) -> np.ndarray | float:
    """柱/箱宽度：映射列 > 层参数 > geom 缺省。"""
    if "width" in table:
        return _column_values(table.column("width")).astype(np.float64)
    if "width" in layer.params:
        return float(layer.params["width"])
    return float(layer.geom.default_aes.get("width", 0.9))


def _default_column(value: Any, nrows: int) -> Column:
    """`default_aes` 的静态值 → 列（标量广播；`None` 是整列缺失）。

    类型照 R 的内置数据：`None` 落成 **logical NA**（`colour` / `fill` /
    `alpha` 的缺省都是 `NA`），整数按 Python 字面量类型走（`linetype = 1` 是
    integer、`shape = 19.0` / `weight = 1.0` 是 double——spec 里写成对应的字面量）。
    """
    if value is None:
        return Column("bool", np.zeros(nrows, dtype=bool), na_mask=np.ones(nrows, dtype=bool))
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
    """一层的数据：六个阶段各一张表，外加缺失值计数与空层标记。"""

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
    #: 图层的几何参数（`geom_point(size = 3)` 的 `size`）；绘制期读它（M1-7）。
    params: Mapping[str, Any] = field(default_factory=dict)
    #: 产生这一层的 `Geom` 对象（`handle_na()` / `draw()` 的入口）；可缺省。
    geom_object: Any = None
    #: `geom_*(show_legend=)`：`None` 是自动（ggplot2 的 `NA`），`False` 不进图例。
    show_legend: bool | None = None

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
class PanelBuild:
    """一个面板的可断言部分：位置、分面值、面板参数与训练好的 x/y 标度。"""

    panel: int
    row: int
    col: int
    scale_x: int
    scale_y: int
    facet_values: Mapping[str, str]
    panel_params: PanelParams
    scales: PanelScaleSet


@dataclass(frozen=True, slots=True)
class PlotBuild:
    """整张图的构建结果：按层顺序，外加训练好的标度、坐标面板参数与提示。"""

    layers: tuple[LayerBuild, ...]
    scales: ScaleSet
    warnings: tuple[str, ...]
    #: 解析后的坐标系（`plot.coordinates`，默认 `coord_cartesian()`）。
    coord: CoordBase | None = None
    #: 面板范围 / limits / clip / 等比例（M1-5）。直接构造 `PlotBuild` 时可为空。
    #: 分面时是**第一个**面板的参数（后向兼容）；每面板一份见 :attr:`panels`。
    panel_params: PanelParams | None = None
    #: 可执行的分面对象（null / wrap / grid）。
    facet: FacetBase | None = None
    #: 分面布局表（`PANEL / ROW / COL / <facet vars> / SCALE_X / SCALE_Y`）。
    layout: FacetLayout | None = None
    #: 每面板一份参数与标度（单面板时也有一条）。
    panels: tuple[PanelBuild, ...] = ()
    #: 构建时的主题（`facet_table()` 取 strip / spacing 的元素值）。
    theme: Any = None
    #: `labs()` 的标签集合（`title` / `x` / `y` / 各美学）；图例标题与轴标题用它。
    labels: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    #: `guides()` 的 component（按键 = 美学名或 guide 名）。
    guides: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    #: 每层合并后的原始映射（`aes()` 的原文）：图例标题与「哪些图层映射了这个美学」。
    raw_mappings: tuple[Mapping[str, Any], ...] = ()
    #: `annotation_*()`（M2-S2）：scene 的轴阶段绘制，不进图层流水线。
    annotations: tuple[Any, ...] = ()
    #: 文本度量（`ggcore.units.Metrics`）；`scene_from_build()` 注入，布局/图例用。
    metrics: Any = None

    @property
    def empty_layers(self) -> tuple[int, ...]:
        """0 行、被跳过但留下记录了的图层下标。"""
        return tuple(layer.index for layer in self.layers if layer.empty)

    @property
    def panel_params_by_panel(self) -> Mapping[int, PanelParams]:
        """`{PANEL: PanelParams}`（每面板一份）。"""
        return MappingProxyType({panel.panel: panel.panel_params for panel in self.panels})

    def facet_table(self, metrics: Any = None, *, right_inside: bool = False) -> Any:
        """分面的 gtable（panel 矩形 + strip + spacing）；单面板给 1×1 表。

        `metrics` 给出时 strip 尺寸走真实字体度量（M1-7 的场景装配）。
        `space = "free"` 需要逐面板范围：这里从各面板的 `PanelParams` 取
        `x_range` / `y_range` 一起交给 `facet_table()`（上游 `init_gtable()` 的
        `ranges` 参数）。`aspect` 按 R `draw_panels()` 解析（`facet_aspect()`）：
        `coord_fixed(ratio=)` 与 `space = "free"` 同时存在时只折 `ratio`，
        否则用首面板的 `Coord$aspect()`。

        `right_inside=True` 把右侧 strip 从 `"outside"` 回退成 `"inside"`
        （右侧有次轴带时 `plot_layout()` 用它避免 strip 压住次轴标签）。
        """
        from ggcore.facet import facet_aspect, facet_table

        if self.layout is None or self.facet is None:
            raise BuildError("这张图没有分面布局；请先用 build_plot() 构建")
        ranges = {
            panel.panel: (panel.panel_params.x_range, panel.panel_params.y_range)
            for panel in self.panels
        }
        params = self.panels[0].panel_params if self.panels else self.panel_params
        return facet_table(
            self.layout,
            self.facet,
            self.theme,
            metrics=metrics,
            ranges=ranges or None,
            aspect=facet_aspect(self.facet, self.coord, params),
            right_inside=right_inside,
        )


@dataclass(frozen=True, slots=True)
class _Stages:
    index: int
    layer: Layer
    aesthetics: Aesthetics
    statistic: ColumnTable
    mapped: ColumnTable
    positioned: ColumnTable


def _compute_stages(
    aesthetics: Aesthetics,
    layer: Layer,
    index: int,
    raw: ColumnTable | None = None,
    scales: Any = None,
) -> _Stages:
    """阶段 2–4：输入是已经过位置标度第一次编码的 `Aesthetics`。

    `raw` 是映射前的美学表（同 :func:`compute_position` 的 `raw`）；`scales` 是
    stat 需要的面板标度（`stat_bin` 的断点范围）。
    """
    statistic = compute_stat(layer, aesthetics, scales=scales, raw=raw)
    mapped = map_statistic(layer, statistic, aesthetics)
    positioned = compute_position(layer, mapped, index, raw)
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
        params=stages.layer.params,
        geom_object=stages.layer.geom,
        show_legend=stages.layer.show_legend,
    )


# ---------------------------------------------------------------------------
# 分面：面板切片 / 每面板标度
# ---------------------------------------------------------------------------


def _slice_table(table: ColumnTable, rows: np.ndarray) -> ColumnTable:
    """按行号取子表（保留 kind / levels / na_mask）。"""
    return ColumnTable([(name, _gather_column(column, rows)) for name, column in _items(table)])


def _concat_tables(tables: Sequence[ColumnTable]) -> ColumnTable:
    """竖向拼接；列名与列序必须一致（同层各面板的同一阶段输出）。"""
    pieces = [table for table in tables if table.nrows]
    if not pieces:
        return _EMPTY
    names = pieces[0].names
    columns: list[tuple[str, Column]] = []
    for name in names:
        columns_in = [table.column(name) for table in pieces]
        kinds = {column.kind for column in columns_in}
        if len(kinds) > 1:
            raise BuildError(f"面板拼接时列 {name!r} 的类型不一致：{sorted(kinds)}")
        first = columns_in[0]
        values = np.concatenate([np.asarray(column.values) for column in columns_in])
        masks = np.concatenate([np.asarray(column.na_mask) for column in columns_in])
        columns.append((name, Column(first.kind, values, levels=first.levels, na_mask=masks)))
    return ColumnTable(columns, nrows=sum(table.nrows for table in pieces))


def _panel_ids_of(table: ColumnTable) -> np.ndarray:
    """表里的 PANEL 列 → 1 起的 int 数组（空表给空数组）。"""
    if table.nrows == 0 or "PANEL" not in table:
        return np.zeros(table.nrows, dtype=np.int64)
    return np.array([int(value) for value in table.column("PANEL").values], dtype=np.int64)


def _panel_slices(panels: np.ndarray) -> list[tuple[int, np.ndarray]]:
    """`(PANEL, 行号)` 列表，按 PANEL 升序（上游 `dapply()` 的分组顺序）。"""
    out: list[tuple[int, np.ndarray]] = []
    for panel in sorted({int(value) for value in panels.tolist() if int(value) > 0}):
        out.append((panel, np.flatnonzero(panels == panel)))
    return out


def _scales_for(scales: Any, panel: int) -> Any:
    """取面板标度：分面用 `PanelScales.for_panel()`，单面板就是同一个 `ScaleSet`。"""
    if scales is None:
        return None
    for_panel = getattr(scales, "for_panel", None)
    return for_panel(panel) if callable(for_panel) else scales


def _restore_order(table: ColumnTable, order: np.ndarray) -> ColumnTable:
    """拼接后的表按原行序还原（`order` 是拼接顺序里的源行号）。"""
    if order.size == 0 or bool(np.array_equal(order, np.arange(order.size))):
        return table
    return _slice_table(table, np.argsort(order))


def _transform_panels(
    scales: PanelScales,
    aesthetics: Aesthetics,
    panels: np.ndarray,
) -> Aesthetics:
    if aesthetics.table.nrows == 0:
        return aesthetics
    pieces: list[ColumnTable] = []
    order: list[np.ndarray] = []
    for panel, rows in _panel_slices(panels):
        subset = replace(aesthetics, table=_slice_table(aesthetics.table, rows))
        pieces.append(transform_scales(scales.for_panel(panel), subset).table)
        order.append(rows)
    return replace(
        aesthetics,
        table=_restore_order(_concat_tables(pieces), np.concatenate(order)),
    )


def _map_position_panels(
    scales: PanelScales,
    aesthetics: Aesthetics,
    panels: np.ndarray,
) -> Aesthetics:
    if aesthetics.table.nrows == 0:
        return aesthetics
    pieces: list[ColumnTable] = []
    order: list[np.ndarray] = []
    for panel, rows in _panel_slices(panels):
        subset = replace(aesthetics, table=_slice_table(aesthetics.table, rows))
        pieces.append(map_position(scales.for_panel(panel), subset).table)
        order.append(rows)
    return replace(
        aesthetics,
        table=_restore_order(_concat_tables(pieces), np.concatenate(order)),
    )


def _compute_panel_stages(
    aesthetics: Aesthetics,
    layer: Layer,
    index: int,
    panels: np.ndarray,
    raw: ColumnTable | None = None,
    scales: Any = None,
) -> _Stages:
    """阶段 2–4：identity stat / position 保持原行序，其余按 PANEL 分组。"""
    if aesthetics.empty:
        return _Stages(index, layer, aesthetics, _EMPTY, _EMPTY, _EMPTY)
    if layer.stat.name == "identity":
        statistic = compute_stat(layer, aesthetics, scales=scales, raw=raw)
    else:
        statistic = _concat_tables(
            [
                compute_stat(
                    layer,
                    replace(aesthetics, table=_slice_table(aesthetics.table, rows), empty=False),
                    scales=_scales_for(scales, panel),
                    raw=raw,
                )
                for panel, rows in _panel_slices(panels)
            ]
        )
    mapped = map_statistic(layer, statistic, aesthetics)
    if layer.position.name == "identity":
        positioned = compute_position(layer, mapped, index, raw)
    else:
        panel_ids = _panel_ids_of(mapped)
        positioned = _concat_tables(
            [
                compute_position(layer, _slice_table(mapped, rows), index, raw)
                for _, rows in _panel_slices(panel_ids)
            ]
        )
    return _Stages(index, layer, aesthetics, statistic, mapped, positioned)


def _map_scales_panels(
    scales: PanelScales,
    positioned: ColumnTable,
) -> tuple[ColumnTable, dict[int, ColumnTable]]:
    """阶段 5 按面板映射，再按原行序拼回；同时留下每面板的 scaled 表。"""
    if positioned.nrows == 0:
        return _EMPTY, {}
    panel_ids = _panel_ids_of(positioned)
    pieces: list[ColumnTable] = []
    order: list[np.ndarray] = []
    per_panel: dict[int, ColumnTable] = {}
    for panel, rows in _panel_slices(panel_ids):
        subset = _slice_table(positioned, rows)
        mapped = map_scales(scales.for_panel(panel), subset)
        pieces.append(mapped)
        order.append(rows)
        per_panel[panel] = mapped
    return _restore_order(_concat_tables(pieces), np.concatenate(order)), per_panel


def build_layer(
    plot: ggplot,
    layer: Layer,
    index: int = 0,
    scales: ScaleSet | None = None,
) -> LayerBuild:
    """构建单层（六阶段全走一遍）。

    `scales` 给出时复用调用方的标度（本函数仍会用这一层的列训练它）；不给就
    新建一个。位置标度按上游口径训练两次（`compute_aesthetics` 之后、
    `compute_position` 之后各一次）。跨层联合训练请用 :func:`build_plot`。

    分面图请直接用 :func:`build_plot`：面板标度池与布局是整张图的，单层函数
    拿不到其它层的数据。
    """
    facet = facet_from_component(plot.facet)
    if not facet.is_null:
        raise BuildError("分面图请用 build_plot()（build_layer 只服务单面板）")
    if scales is None:
        scales = ScaleSet(plot.scales)
    aesthetics = compute_aesthetics(plot, layer, index)
    raw_table = aesthetics.table
    aesthetics = transform_scales(scales, aesthetics)
    _train(scales, aesthetics.table)
    aesthetics = map_position(scales, aesthetics)
    stages = _compute_stages(aesthetics, layer, index, raw_table, scales)
    # 上游 compute_position 之后再 train 一次：这一次的数据已经包含 geom setup
    # 派生的坐标列（xmin/xmax/ymin/ymax），连续标度要靠它才能把柱子的锚点收进
    # 范围（否则 stage 5 的 oob 会把锚点 censor 成 NA）。
    _train(scales, stages.positioned)
    return _assemble(stages, scales)


def build_plot(plot: ggplot) -> PlotBuild:
    """按层顺序构建整张图；**本任务不产出 grob / 不出图**。

    标度先在所有层上训练，再统一映射（上游 `scales$train_df(data)` 的口径），
    所以同一离散 x 在不同层里得到同一套 1..n 编码；位置标度同样保留上游的
    两段训练（aesthetics 之后、position 之后各一次）。

    `facet_null` 走与 M1-5 完全相同的单面板路径（输出逐字节不变）；wrap / grid
    先 `compute_layout()`，再按 PANEL 切数据跑同一套六阶段，位置标度按
    `free_x` / `free_y` 分配给面板（wrap）或行/列（grid）。
    """
    facet = facet_from_component(plot.facet)
    if not facet.is_null:
        return _build_plot_facets(plot, facet)
    layout = facet.compute_layout([])
    scales = ScaleSet(plot.scales)
    raw = [compute_aesthetics(plot, layer, index) for index, layer in enumerate(plot.layers)]
    # 位置标度映射前的美学表：geom 的 `setup_params()` 用它判断离散位置
    # （R 的 `is_mapped_discrete()`，M1-7 的横向 geom）。
    raw_tables = [aesthetics.table for aesthetics in raw]
    raw = [transform_scales(scales, aesthetics) for aesthetics in raw]
    for aesthetics in raw:
        _train(scales, aesthetics.table)
    mapped = [map_position(scales, aesthetics) for aesthetics in raw]
    stages = [
        _compute_stages(aesthetics, layer, index, raw_tables[index], scales)
        for index, (aesthetics, layer) in enumerate(zip(mapped, plot.layers, strict=True))
    ]
    # 第二段训练用 position 之后的数据（含 xmin/xmax/ymin/ymax），见 build_layer。
    # 上游在这之前调 `layout$reset_scales()`（分箱位置标度切到 after_stat 语义）。
    scales.reset()
    for staged in stages:
        _train(scales, staged.positioned)
    builds = tuple(_assemble(staged, scales) for staged in stages)
    coord = coord_from_component(plot.coordinates)
    panel_params = coord.panel_params(scales)
    scaled = tuple(build.scaled for build in builds)
    panel_params = panel_params.with_counts(
        out_of_bounds=count_out_of_bounds(panel_params, scaled),
        dropped=count_dropped(scaled),
        rows_dropped=count_rows_dropped(scaled),
    )
    notes = tuple(note for build in builds for note in build.notes) + panel_params.warnings()
    raw_mappings = tuple(dict(_resolve_mapping(plot, layer)) for layer in plot.layers)
    return PlotBuild(
        layers=builds,
        scales=scales,
        warnings=notes,
        coord=coord,
        panel_params=panel_params,
        facet=facet,
        layout=layout,
        panels=(
            PanelBuild(
                panel=1,
                row=1,
                col=1,
                scale_x=1,
                scale_y=1,
                facet_values={},
                panel_params=panel_params,
                scales=PanelScaleSet(scales),
            ),
        ),
        theme=plot.theme,
        labels=_plot_labels(plot),
        guides=_plot_guides(plot),
        annotations=tuple(getattr(plot, "annotations", ()) or ()),
        raw_mappings=raw_mappings,
    )


def _plot_labels(plot: Any) -> Mapping[str, Any]:
    labels = getattr(plot, "labels", None) or {}
    return MappingProxyType(dict(labels))


def _plot_guides(plot: Any) -> Mapping[str, Any]:
    guides = getattr(plot, "guides", None) or {}
    return MappingProxyType(dict(guides))


def _build_plot_facets(plot: ggplot, facet: FacetBase) -> PlotBuild:
    """wrap / grid 的整图构建：布局 → 每面板标度 → 按 PANEL 切数据。"""
    coord = coord_from_component(plot.coordinates)
    ratio = getattr(coord, "ratio", None)
    space = str(getattr(facet, "space", "fixed") or "fixed")
    # 只有 `facet_grid(space = "free")`（两维都 free）能配自由刻度 + `ratio`
    # （R 4.0.3 `FacetGrid$draw_panels()`）：`space = "free_x"` / `"free_y"` 与
    # `facet_wrap()` 的自由刻度在 R 里仍是
    # `can't use free scales with coord_cartesian() with a fixed ratio argument`。
    if (facet.free_x or facet.free_y) and ratio is not None:
        if not (facet.kind == "grid" and space == "free"):
            raise BuildError(
                "自由刻度不能和 coord_fixed(ratio=…) 一起用"
                '（上游同样报错：只有 facet_grid(space="free") 的两维自由刻度'
                '能配 ratio；space="free_x"/"free_y" 与 facet_wrap 都会报错）'
            )
    # `coord_polar()` / `coord_radial()` 的面板范围不是普通 (x, y) 区间，
    # R 4.0.3 在 `init_gtable()` 里算 space 权重时直接报
    # `values must be length 1`（上游 bug）。gg4py 曾静默出非正圆面板；
    # 按 parity 口径明确报错，不猜一个 R 自己都产生不了的结果。
    if space != "fixed" and str(getattr(coord, "name", "")) in ("polar", "radial"):
        raise BuildError(
            f"coord_{getattr(coord, 'name', 'polar')}() 不能和 space={space!r} 一起用"
            '（R 4.0.3 在 init_gtable() 里报 "values must be length 1"，'
            "见 docs/notes/facet.md §7）"
        )
    layers = list(plot.layers)
    tables = [_resolve_data(plot, layer) for layer in layers]
    layout = facet.compute_layout(tables)
    maps = [facet.map_data(table, layout) for table in tables]
    data_tables = [
        table
        if bool(np.array_equal(mapping.rows, np.arange(table.nrows)))
        else _slice_table(table, mapping.rows)
        for table, mapping in zip(tables, maps, strict=True)
    ]
    scales = facet.init_scales(layout, plot.scales)

    raw = [
        compute_aesthetics(
            plot,
            layer,
            index,
            panels=maps[index].panels,
            data_table=data_tables[index],
        )
        for index, layer in enumerate(layers)
    ]
    raw_tables = [aesthetics.table for aesthetics in raw]
    raw = [
        _transform_panels(scales, aesthetics, maps[index].panels)
        for index, aesthetics in enumerate(raw)
    ]
    # 第一段训练：所有层、所有面板都先训练，再统一 map_position。
    for index, aesthetics in enumerate(raw):
        for panel, rows in _panel_slices(maps[index].panels):
            _train(scales.for_panel(panel), _slice_table(aesthetics.table, rows))
    mapped = [
        _map_position_panels(scales, aesthetics, maps[index].panels)
        for index, aesthetics in enumerate(raw)
    ]
    stages = [
        _compute_panel_stages(
            aesthetics, layer, index, maps[index].panels, raw_tables[index], scales
        )
        for index, (aesthetics, layer) in enumerate(zip(mapped, layers, strict=True))
    ]
    # 第二段训练用 position 之后的数据（含 xmin/xmax/ymin/ymax）。
    # 上游在 compute_position() 之后、train_position() 之前调
    # `layout$reset_scales()`（分箱位置标度把 map 切到 after_stat 语义）。
    for panel in layout.panel_ids:
        scales.for_panel(panel).reset()
    for staged in stages:
        panel_ids = _panel_ids_of(staged.positioned)
        for panel, rows in _panel_slices(panel_ids):
            _train(scales.for_panel(panel), _slice_table(staged.positioned, rows))

    builds: list[LayerBuild] = []
    scaled_by_panel: list[dict[int, ColumnTable]] = []
    for staged in stages:
        scaled, per_panel = _map_scales_panels(scales, staged.positioned)
        data = finish(staged.layer, scaled, staged.index)
        builds.append(
            LayerBuild(
                index=staged.index,
                geom=staged.layer.geom.name,
                stat=staged.layer.stat.name,
                position=staged.layer.position.name,
                aesthetics=staged.aesthetics.table,
                statistic=staged.statistic,
                mapped=staged.mapped,
                positioned=staged.positioned,
                scaled=scaled,
                data=data,
                dropped_missing=staged.aesthetics.dropped,
                empty=staged.aesthetics.empty,
                notes=staged.aesthetics.notes,
                params=staged.layer.params,
                geom_object=staged.layer.geom,
                show_legend=staged.layer.show_legend,
            )
        )
        scaled_by_panel.append(per_panel)

    panels: list[PanelBuild] = []
    for panel in layout.panel_ids:
        panel_scales = scales.for_panel(panel)
        panel_params = coord.panel_params(panel_scales)
        panel_tables = tuple(
            per_panel[panel] for per_panel in scaled_by_panel if panel in per_panel
        )
        panel_params = panel_params.with_counts(
            out_of_bounds=count_out_of_bounds(panel_params, panel_tables),
            dropped=count_dropped(panel_tables),
            rows_dropped=count_rows_dropped(panel_tables),
        )
        panels.append(
            PanelBuild(
                panel=panel,
                row=layout.row_of(panel),
                col=layout.col_of(panel),
                scale_x=layout.scale_x_of(panel),
                scale_y=layout.scale_y_of(panel),
                facet_values=MappingProxyType(layout.facet_values(panel)),
                panel_params=panel_params,
                scales=panel_scales,
            )
        )

    notes = tuple(note for build in builds for note in build.notes) + tuple(
        note for panel in panels for note in panel.panel_params.warnings()
    )
    raw_mappings = tuple(dict(_resolve_mapping(plot, layer)) for layer in layers)
    return PlotBuild(
        layers=tuple(builds),
        scales=scales.shared,
        warnings=notes,
        coord=coord,
        panel_params=panels[0].panel_params,
        facet=facet,
        layout=layout,
        panels=tuple(panels),
        theme=plot.theme,
        labels=_plot_labels(plot),
        guides=_plot_guides(plot),
        annotations=tuple(getattr(plot, "annotations", ()) or ()),
        raw_mappings=raw_mappings,
    )

"""`ggcore.facet` —— 分面（M1-6）：`facet_null` / `facet_wrap` / `facet_grid`。

分面回答三个问题，接口照上游 `Facet` 原型（`R/facet-.R` /
`R/facet-wrap.R` / `R/facet-grid-.R`，ggplot2 4.0.3）：

1. **布局**：:meth:`FacetBase.compute_layout` 把数据里的分面变量变成
   `PANEL / ROW / COL / <facet vars> / SCALE_X / SCALE_Y` 一张表；
2. **面板标度**：`free = {"x": bool, "y": bool}` 时每个面板（wrap）或每列/每行
   （grid）一份位置标度，固定刻度时所有面板共用一份；
3. **数据归属**：:meth:`FacetBase.map_data` 给每一行找 PANEL（1 起）。

布局顺序按**水平（levels）**而不是出现顺序：分类列用 `Column.levels`，普通
字符串列按升序，数值按数值升序，NA 排在最后。`facet_grid(as.table = FALSE)`
把行变量倒过来（上游 `rev_order()`），列不受影响。

只做「结构」：完整 grob 绘制留给 M1-7。这里给出的 gtable 已经把
panel 行列、strip 文本、`panel.spacing` 摆好，:class:`FacetTable` 能直接回答
「每个面板矩形在哪、strip 上写什么」。

M2-3 补全：`scales` 的逐面板范围、`space = "free"` 的 null 权重、
`facet_grid(margins=)` 的 `(all)` 面板、`label_value` / `label_both` /
`label_context` / `labeller()`、strip 的真实文字度量（含 angle）与
`strip.placement` 都已实现对拍，见 `docs/notes/facet.md`。
"""

from __future__ import annotations

import ast
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import numpy as np

from ggcore.aes import Aes
from ggcore.axis import margin_sides_cm, text_line_cm, text_width_cm
from ggcore.components import Facet
from ggcore.data import Column, ColumnTable
from ggcore.eval import eval_aes, parse_aes
from ggcore.gtable import CellBox, GTable, Placement, gtable
from ggcore.scales import ScaleSet
from ggcore.theme import (
    ElementBlank,
    ElementRect,
    ElementText,
    ResolvedTheme,
    Theme,
    resolve_theme,
)
from ggcore.units import Unit, UnitContext, unit

__all__ = [
    "FREE_SCALES",
    "FacetBase",
    "FacetError",
    "FacetGrid",
    "FacetLayout",
    "FacetNull",
    "FacetStrip",
    "FacetTable",
    "FacetVar",
    "FacetWrap",
    "PanelMap",
    "PanelScaleSet",
    "PanelScales",
    "StripPart",
    "facet_aspect",
    "facet_from_component",
    "facet_table",
    "label_both",
    "label_context",
    "label_value",
    "labeller",
]

#: `scales =` 的四个取值 → `(free_x, free_y)`（上游 `facet_*()` 的解析）。
FREE_SCALES: Mapping[str, tuple[bool, bool]] = {
    "fixed": (False, False),
    "free": (True, True),
    "free_x": (True, False),
    "free_y": (False, True),
}

#: `facet_wrap(dir=)` 的 8 个方向（4.0.3 把 `h` / `v` 先折成其中四个）。
_WRAP_DIRS = ("lt", "tl", "lb", "bl", "rt", "tr", "rb", "br")


class FacetError(ValueError):
    """分面参数无法解析，或数据里没有分面变量。"""


# ---------------------------------------------------------------------------
# 分面变量
# ---------------------------------------------------------------------------


def _key(value: Any) -> Any:
    """分面值 → 可哈希、可排序的规范键（NA → None，逻辑值保留 bool）。"""
    if value is None:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) else float(value)
    if isinstance(value, int):
        return float(value)
    return str(value)


def _label(value: Any) -> str:
    """`label_value` 的文本：NA → "NA"，逻辑值 → TRUE/FALSE，整数浮点去掉 `.0`。"""
    if value is None:
        return "NA"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


@dataclass(frozen=True, slots=True)
class FacetVar:
    """一个分面变量：布局里的名字 + 取值表达式。

    `expression` 里写列名（`"a"`）或任意 aes 表达式（`"a + b"`）；分面值的
    水平顺序优先取源列的 `levels`（categorical 的显式顺序），否则按值排序。
    """

    name: str
    expression: Any

    def values(self, table: ColumnTable) -> list[Any]:
        spec = parse_aes(self.expression)
        if spec.after_stat:
            raise FacetError(f"分面变量 {self.name!r} 不能用 after_stat(...)")
        raw = eval_aes(spec, table, nrows=table.nrows)
        return [_key(item) for item in raw.tolist()]

    def explicit_levels(self, table: ColumnTable) -> tuple[Any, ...] | None:
        """源列是离散列时给它的 levels（顺序就是分面顺序）。"""
        spec = parse_aes(self.expression)
        body = None if spec.tree is None else spec.tree.body
        if isinstance(body, ast.Name) and body.id in table:
            column = table.column(body.id)
            if column.is_discrete and column.levels:
                return tuple(_key(level) for level in column.levels)
        return None


def _facet_vars(facets: Any) -> tuple[FacetVar, ...]:
    """`facet_wrap(facets=...)` → 分面变量表。

    接受：列名字符串、字符串序列、`aes(...)`（键是布局里的变量名，值是该列
    的表达式），以及显式 :class:`FacetVar`。
    """
    if facets is None:
        return ()
    if isinstance(facets, FacetVar):
        return (facets,)
    if isinstance(facets, str):
        return (FacetVar(facets, facets),)
    if isinstance(facets, Aes):
        return tuple(FacetVar(name, expression) for name, expression in facets.items())
    if isinstance(facets, Mapping):
        return tuple(FacetVar(str(name), expression) for name, expression in facets.items())
    if isinstance(facets, Sequence):
        out: list[FacetVar] = []
        for item in facets:
            if isinstance(item, FacetVar):
                out.append(item)
            elif isinstance(item, str):
                out.append(FacetVar(item, item))
            else:
                raise FacetError(f"分面变量必须是列名或 FacetVar，收到 {type(item).__name__}")
        return tuple(out)
    raise FacetError(f"不认识的分面写法 {facets!r}（列名 / 列名序列 / aes(...)）")


# ---------------------------------------------------------------------------
# 布局
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FacetLayout:
    """分面布局表（上游 `ggplot_build(p)$layout$layout`）。

    `table` 的列序：`PANEL / ROW / COL / <facet vars> / SCALE_X / SCALE_Y`。
    PANEL 1 起；`SCALE_X` / `SCALE_Y` 指向该面板用的位置标度槽位（固定刻度时
    全是 1，wrap 自由刻度时每个面板一个，grid 自由刻度时每列/每行一个）。

    分面变量列保留**原始类型**（numeric / bool / str + `na_mask`），用于
    `map_data()` 的逐值匹配；显示文本在 `label_table` 的同类列里（`label_value`
    的口径），`value()` 读原始值、`label()` 读显示文本。
    """

    kind: str
    facet_vars: tuple[str, ...]
    table: ColumnTable
    label_table: ColumnTable
    nrow: int
    ncol: int

    def __post_init__(self) -> None:
        for name in ("PANEL", "ROW", "COL", "SCALE_X", "SCALE_Y"):
            if name not in self.table:
                raise FacetError(f"布局表缺少 {name} 列")
        if self.nrow < 1 or self.ncol < 1:
            raise FacetError(f"面板行列必须 ≥ 1，收到 {self.nrow} × {self.ncol}")

    @property
    def npanels(self) -> int:
        return self.table.nrows

    @property
    def panel_ids(self) -> tuple[int, ...]:
        return tuple(int(value) for value in self.table.column("PANEL").values)

    def value(self, panel: int, name: str) -> Any:
        row = panel - 1
        if not 0 <= row < self.table.nrows:
            raise KeyError(f"没有 PANEL={panel}")
        column = self.table.column(name)
        if bool(column.na_mask[row]):
            return None
        value = column.values[row]
        return value.item() if hasattr(value, "item") else value

    def label(self, panel: int, name: str) -> str:
        row = panel - 1
        if not 0 <= row < self.table.nrows:
            raise KeyError(f"没有 PANEL={panel}")
        return str(self.label_table.column(name).values[row])

    def row_of(self, panel: int) -> int:
        return int(self.value(panel, "ROW"))

    def col_of(self, panel: int) -> int:
        return int(self.value(panel, "COL"))

    def scale_x_of(self, panel: int) -> int:
        return int(self.value(panel, "SCALE_X"))

    def scale_y_of(self, panel: int) -> int:
        return int(self.value(panel, "SCALE_Y"))

    def panels_in_row(self, row: int) -> tuple[int, ...]:
        return tuple(panel for panel in self.panel_ids if self.row_of(panel) == row)

    def panels_in_col(self, col: int) -> tuple[int, ...]:
        return tuple(panel for panel in self.panel_ids if self.col_of(panel) == col)

    def facet_values(self, panel: int) -> dict[str, str]:
        """面板的显示文本（`facet_values` 沿用 M1-6 的 `{变量: str}` 契约）。"""
        return {name: self.label(panel, name) for name in self.facet_vars}


def _layout_table(
    kind: str,
    facet_vars: tuple[str, ...],
    rows: Sequence[tuple[int, int, dict[str, Any], dict[str, str]]],
    nrow: int,
    ncol: int,
) -> FacetLayout:
    """行记录 → 布局表；`rows` 每项是 `(ROW, COL, 原始值, 显示标签)`。"""
    count = len(rows)
    columns: list[tuple[str, Column]] = [
        ("PANEL", Column("int", np.arange(1, count + 1, dtype=np.int64))),
        ("ROW", Column("int", np.array([row for row, _, _, _ in rows], dtype=np.int64))),
        ("COL", Column("int", np.array([col for _, col, _, _ in rows], dtype=np.int64))),
    ]
    label_columns: list[tuple[str, Column]] = []
    for name in facet_vars:
        columns.append((name, _typed_column([values[name] for _, _, values, _ in rows])))
        label_columns.append(
            (name, Column("str", np.array([labels[name] for _, _, _, labels in rows], dtype=str)))
        )
    scale_x = np.array([values["__SCALE_X"] for _, _, values, _ in rows], dtype=np.int64)
    scale_y = np.array([values["__SCALE_Y"] for _, _, values, _ in rows], dtype=np.int64)
    columns.append(("SCALE_X", Column("int", scale_x)))
    columns.append(("SCALE_Y", Column("int", scale_y)))
    return FacetLayout(
        kind=kind,
        facet_vars=facet_vars,
        table=ColumnTable(columns, nrows=count),
        label_table=ColumnTable(label_columns, nrows=count),
        nrow=nrow,
        ncol=ncol,
    )


def _typed_column(values: Sequence[Any]) -> Column:
    """分面值 → 保留原始类型的 `Column`（NA 进 `na_mask`）。"""
    missing = np.array([value is None for value in values], dtype=bool)
    present = [value for value in values if value is not None]
    if present and all(isinstance(value, bool) for value in present):
        return Column(
            "bool",
            np.array([False if value is None else bool(value) for value in values], dtype=bool),
            na_mask=missing,
        )
    if present and all(isinstance(value, float) for value in present):
        return Column(
            "float",
            np.array(
                [0.0 if value is None else float(value) for value in values], dtype=np.float64
            ),
            na_mask=missing,
        )
    return Column(
        "str",
        np.array(["" if value is None else str(value) for value in values], dtype=str),
        na_mask=missing,
    )


def _is_missing_key(key: Any) -> bool:
    return key is None


class _Levels:
    """每个分面变量的水平表 + 排序键（跨图层取并集）。"""

    def __init__(self, layers: Sequence[ColumnTable], vars: Sequence[FacetVar]) -> None:
        self.vars = tuple(vars)
        self.observed: dict[str, list[Any]] = {var.name: [] for var in vars}
        self.explicit: dict[str, tuple[Any, ...]] = {}
        for table in layers:
            for var in vars:
                if not _has_var(table, var):
                    continue
                for value in var.values(table):
                    if value not in self.observed[var.name]:
                        self.observed[var.name].append(value)
                levels = var.explicit_levels(table)
                if levels is not None and var.name not in self.explicit:
                    self.explicit[var.name] = levels
        self.levels: dict[str, tuple[Any, ...]] = {
            var.name: self._ordered(var.name) for var in vars
        }
        self.rank: dict[str, dict[Any, int]] = {
            name: {value: index for index, value in enumerate(values)}
            for name, values in self.levels.items()
        }

    def _ordered(self, name: str) -> tuple[Any, ...]:
        observed = [value for value in self.observed[name] if not _is_missing_key(value)]
        # `drop = FALSE` 要把显式 levels 里**没出现**的值也展开成空面板，
        # 所以显式 levels 原样保留（上游 factor 的 levels 不因数据缺席而缩短）。
        explicit = list(self.explicit.get(name, ()))
        known = set(explicit)
        rest = [value for value in observed if value not in known]
        if any(isinstance(value, float) for value in rest) and not any(
            isinstance(value, str) for value in rest
        ):
            rest.sort()
        else:
            rest.sort(key=lambda value: str(value))
        if any(_is_missing_key(value) for value in self.observed[name]):
            rest.append(None)
        return tuple(explicit + rest)

    def sort_key(self, values: Mapping[str, Any]) -> tuple[Any, ...]:
        out: list[Any] = []
        for var in self.vars:
            value = values[var.name]
            if _is_missing_key(value):
                out.append((1, 0))
            else:
                out.append((0, self.rank[var.name][value]))
        return tuple(out)


def _combos(
    layers: Sequence[ColumnTable],
    vars: Sequence[FacetVar],
    drop: bool,
    levels: _Levels,
) -> tuple[tuple[dict[str, Any], ...], list[dict[str, Any]]]:
    """分面组合的**有序**列表（按 levels），外加每个组合的标签值。

    返回 `(combos, labels)`；两者等长、同序。`drop = False` 时把所有水平
    的笛卡尔积都列出来（上游 `unique_combs()`）。
    """
    names = [var.name for var in vars]
    if not names:
        return (({},), [{}])

    seen: dict[tuple[Any, ...], dict[str, Any]] = {}
    if drop:
        for table in layers:
            present = [var for var in vars if _has_var(table, var)]
            if len(present) != len(vars):
                continue
            values = {var.name: var.values(table) for var in vars}
            for index in range(table.nrows):
                combo = {var.name: values[var.name][index] for var in vars}
                seen.setdefault(tuple(combo[name] for name in names), combo)
    else:
        for combo in _product(levels, names):
            seen[tuple(combo[name] for name in names)] = combo

    if not seen:
        wanted = "、".join(names)
        raise FacetError(
            f"分面变量（{wanted}）在数据里必须至少有一个值；"
            "请检查列名，或确认至少一层同时含有全部分面变量"
        )
    ordered = sorted(seen.values(), key=levels.sort_key)
    labels = [{name: _label(combo[name]) for name in names} for combo in ordered]
    return tuple(ordered), labels


def _product(levels: _Levels, names: Sequence[str]) -> list[dict[str, Any]]:
    """所有水平的笛卡尔积（第一个变量变化最快，与 R `expand.grid()` 一致）。"""
    combos: list[dict[str, Any]] = [{}]
    for name in names:
        expanded: list[dict[str, Any]] = []
        for value in levels.levels[name]:
            for combo in combos:
                expanded.append({**combo, name: value})
        combos = expanded
    return combos


def _has_var(table: ColumnTable, var: FacetVar) -> bool:
    """层里是否含这个分面变量的全部引用列（常量表达式总是算有）。"""
    spec = parse_aes(var.expression)
    return all(name in table for name in spec.columns)


def _missing_vars(table: ColumnTable, vars: Sequence[FacetVar]) -> list[FacetVar]:
    return [var for var in vars if not _has_var(table, var)]


# ---------------------------------------------------------------------------
# 分面基类
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PanelMap:
    """一层的分面归属：`rows` 是输出行对应的源行号（缺分面变量时会复制行）。"""

    panels: np.ndarray
    rows: np.ndarray

    @property
    def nrows(self) -> int:
        return int(self.panels.size)


class PanelScaleSet(ScaleSet):
    """一个面板看到的标度：位置走该面板自己的槽位，其余共享全局标度。

    上游 `layout$get_scales(panel)` 返回的就是这种「位置按面板分、非位置共用」
    的组合。继承 :class:`ggcore.scales.ScaleSet` 只是为了满足坐标系的
    `isinstance` 检查；所有查询方法都转发给两个真实对象，本类自己不持有标度。
    """

    def __init__(
        self,
        shared: ScaleSet,
        x_set: ScaleSet | None = None,
        y_set: ScaleSet | None = None,
    ) -> None:
        super().__init__({})
        self.shared = shared
        self.x_set = x_set
        self.y_set = y_set

    def _target(self, aesthetic: str) -> ScaleSet:
        if aesthetic in ("x", "xmin", "xmax", "xend") and self.x_set is not None:
            return self.x_set
        if aesthetic in ("y", "ymin", "ymax", "yend") and self.y_set is not None:
            return self.y_set
        return self.shared

    # -- 流水线入口 -------------------------------------------------------

    def train(self, values: Any, aesthetic: str) -> None:
        self._target(aesthetic).train(values, aesthetic)

    def transform(self, values: Any, aesthetic: str) -> Any:
        return self._target(aesthetic).transform(values, aesthetic)

    def transform_table(self, table: ColumnTable) -> ColumnTable:
        if table.nrows == 0:
            return table
        return ColumnTable(
            [
                (name, self._target(name).transform(column, name))
                for name, column in zip(table.names, table.columns(), strict=True)
            ],
            nrows=table.nrows,
        )

    def map(self, values: Any, aesthetic: str) -> Any:
        return self._target(aesthetic).map(values, aesthetic)

    def reset(self) -> None:
        """转发给真实持有的三个集合（共享 + 位置槽位）。

        共享集可能被多个面板重复 reset；各标度的 reset 必须幂等（分箱位置标度
        只是把 after_stat 置 True）。
        """
        self.shared.reset()
        if self.x_set is not None:
            self.x_set.reset()
        if self.y_set is not None:
            self.y_set.reset()

    # -- 查询 -------------------------------------------------------------

    def scale(self, aesthetic: str) -> Any:
        return self._target(aesthetic).scale(aesthetic)

    def limits(self, aesthetic: str) -> Any:
        return self._target(aesthetic).limits(aesthetic)

    def expanded_limits(self, aesthetic: str) -> Any:
        return self._target(aesthetic).expanded_limits(aesthetic)

    def breaks(self, aesthetic: str) -> tuple[Any, ...]:
        return self._target(aesthetic).breaks(aesthetic)

    def labels(self, aesthetic: str) -> tuple[Any, ...]:
        return self._target(aesthetic).labels(aesthetic)

    def levels(self, aesthetic: str) -> tuple[str, ...]:
        return self._target(aesthetic).levels(aesthetic)

    @property
    def trained(self) -> Mapping[str, tuple[str, ...]]:
        out = dict(self.shared.trained)
        for part in (self.x_set, self.y_set):
            if part is not None:
                out.update(part.trained)
        return MappingProxyType(out)

    def aesthetics(self) -> tuple[str, ...]:
        names = list(self.shared.aesthetics())
        for part in (self.x_set, self.y_set):
            if part is not None:
                for name in part.aesthetics():
                    if name not in names:
                        names.append(name)
        return tuple(names)


@dataclass(frozen=True, slots=True)
class PanelScales:
    """整张图的面板标度池：共享集 + 每面板（或每行/每列）的位置标度。"""

    layout: FacetLayout
    shared: ScaleSet
    x_sets: tuple[ScaleSet, ...] | None
    y_sets: tuple[ScaleSet, ...] | None

    @classmethod
    def create(
        cls,
        layout: FacetLayout,
        scales: ScaleSet | Mapping[str, Any],
        free: tuple[bool, bool],
    ) -> PanelScales:
        shared = scales if isinstance(scales, ScaleSet) else ScaleSet(scales)
        x_sets = None
        y_sets = None
        if free[0]:
            count = int(layout.table.column("SCALE_X").values.max())
            x_sets = tuple(ScaleSet(shared.specs) for _ in range(count))
        if free[1]:
            count = int(layout.table.column("SCALE_Y").values.max())
            y_sets = tuple(ScaleSet(shared.specs) for _ in range(count))
        return cls(layout=layout, shared=shared, x_sets=x_sets, y_sets=y_sets)

    def for_panel(self, panel: int) -> PanelScaleSet:
        x_set = None
        y_set = None
        if self.x_sets is not None:
            x_set = self.x_sets[self.layout.scale_x_of(panel) - 1]
        if self.y_sets is not None:
            y_set = self.y_sets[self.layout.scale_y_of(panel) - 1]
        return PanelScaleSet(self.shared, x_set, y_set)


@dataclass(frozen=True, slots=True)
class FacetBase:
    """分面公共部分：变量、free 轴、drop、labeller。"""

    facet_vars: tuple[FacetVar, ...] = ()
    free: tuple[bool, bool] = (False, False)
    drop: bool = True
    labeller: Any = "label_value"
    kind: str = "null"

    # -- 参数 ---------------------------------------------------------------

    @property
    def free_x(self) -> bool:
        return self.free[0]

    @property
    def free_y(self) -> bool:
        return self.free[1]

    @property
    def is_null(self) -> bool:
        return self.kind == "null"

    # -- 布局 ---------------------------------------------------------------

    def compute_layout(self, data: Sequence[ColumnTable] | ColumnTable) -> FacetLayout:
        """数据 → 布局表。`data` 是各层原始数据的列表（上游 `layout$setup`）。"""
        raise NotImplementedError

    def map_data(self, data: ColumnTable, layout: FacetLayout) -> PanelMap:
        """一层数据 → 每行的 PANEL（1 起）。"""
        if not self.facet_vars:
            return PanelMap(
                panels=np.ones(data.nrows, dtype=np.int64),
                rows=np.arange(data.nrows, dtype=np.int64),
            )
        missing = _missing_vars(data, self.facet_vars)
        return _map_with_replication(data, layout, self.facet_vars, missing)

    def init_scales(
        self,
        layout: FacetLayout,
        scales: ScaleSet | Mapping[str, Any],
        free: tuple[bool, bool] | None = None,
    ) -> PanelScales:
        """面板标度池（上游 `Facet$init_scales()`）。

        `free` 不给时用本对象的 `free`；固定刻度的轴共用 `shared`，
        自由刻度的轴各槽位一份 `ScaleSet`（fresh，未训练）。
        """
        return PanelScales.create(layout, scales, self.free if free is None else free)

    # -- 标签 ---------------------------------------------------------------

    def strip_texts(self, layout: FacetLayout) -> dict[int, str]:
        """每个面板的 strip 文本（wrap：面板顶部；grid 另见 :func:`facet_table`）。"""
        return {panel: self._strip_text(layout, panel) for panel in layout.panel_ids}

    def strip_labels(self, layout: FacetLayout, panel: int) -> dict[str, str]:
        """一个面板的**逐变量**标签（上游每变量一条 strip）。

        `label_both` / `label_context` 让标签带上变量名；多变量分面在 R 里是
        多条 strip 叠在一起，不是一条多行文本，所以这里保留变量粒度。
        """
        values = {name: [layout.label(panel, name)] for name in layout.facet_vars}
        labels = _labeller(self.labeller, values)
        return {name: labels[name][0] for name in layout.facet_vars}

    def _strip_text(self, layout: FacetLayout, panel: int) -> str:
        labels = self.strip_labels(layout, panel)
        return "\n".join(labels[name] or "" for name in layout.facet_vars)


def _map_with_replication(
    data: ColumnTable,
    layout: FacetLayout,
    vars: Sequence[FacetVar],
    missing: Sequence[FacetVar],
) -> PanelMap:
    """按分面变量找 PANEL；层里缺某变量时按布局的水平复制数据行。

    匹配用布局里的**原始值**（numeric / bool / str / NA 的 `na_mask`），
    不用显示文本——否则字符串 "NA" 会与真正的缺失值撞键。
    """
    names = [var.name for var in vars]
    key_map = {
        tuple(layout.value(panel, name) for name in names): panel for panel in layout.panel_ids
    }
    present = [var for var in vars if var not in missing]
    values = {var.name: np.asarray(var.values(data), dtype=object) for var in present}
    missing_levels = [
        list(dict.fromkeys(layout.value(panel, var.name) for panel in layout.panel_ids))
        for var in missing
    ]
    combinations: list[dict[str, Any]] = [{}]
    for var, levels in zip(missing, missing_levels, strict=True):
        combinations = [{**combo, var.name: level} for level in levels for combo in combinations]

    panel_out: list[int] = []
    row_out: list[int] = []
    for index in range(data.nrows):
        for combo in combinations:
            key = tuple(combo[name] if name in combo else values[name][index] for name in names)
            try:
                panel_out.append(key_map[key])
            except KeyError:
                shown = {name: _label(value) for name, value in zip(names, key, strict=True)}
                raise FacetError(
                    f"分面值 {shown!r} 不在布局里（drop = FALSE 的分面组合之外的数据无法落面板）"
                ) from None
            row_out.append(index)
    return PanelMap(
        panels=np.array(panel_out, dtype=np.int64),
        rows=np.array(row_out, dtype=np.int64),
    )


def _labeller(labeller: Any, labels: Mapping[str, list[str]]) -> dict[str, list[str]]:
    """`labeller` 参数 → `{变量名: [标签…]}`（上游 `validate_labeller()` 的调用面）。

    支持上游 4.0.3 的常用形态：

    - `"label_value"`（默认）/ `"label_both"` / `"label_context"`；
    - `{"变量": {值: 标签}}` / `{"变量": 函数}` —— 逐变量覆盖；
    - `{值: 标签}` —— 单变量简写（同一个值表作用到每个变量）；
    - 函数 `f({变量: [值…]}) -> {变量: [标签…]}`（与 :func:`labeller` 的产物同形）。
    """
    function = _as_labeller(labeller)
    result = function({name: list(values) for name, values in labels.items()})
    if not isinstance(result, Mapping):
        raise FacetError("labeller 必须返回 {变量名: [标签…]}")
    out: dict[str, list[str]] = {}
    for name, values in labels.items():
        mapped = result.get(name)
        if mapped is None:
            mapped = values
        if isinstance(mapped, str):
            mapped = [mapped]
        mapped = [str(item) for item in mapped]
        if len(mapped) != len(values):
            raise FacetError(
                f"labeller 给变量 {name!r} 返回 {len(mapped)} 个标签，"
                f"但该变量有 {len(values)} 个水平"
            )
        out[name] = mapped
    return out


def label_value(labels: Mapping[str, Any], multi_line: bool = True) -> dict[str, list[str]]:
    """上游 `label_value()`：值本身就是标签。"""
    del multi_line
    return {name: [str(value) for value in values] for name, values in labels.items()}


def label_both(
    labels: Mapping[str, Any],
    multi_line: bool = True,
    sep: str = ": ",
) -> dict[str, list[str]]:
    """上游 `label_both()`：每条标签写成 `变量: 值`。"""
    del multi_line
    return {name: [f"{name}{sep}{value}" for value in values] for name, values in labels.items()}


def label_context(
    labels: Mapping[str, Any],
    multi_line: bool = True,
    sep: str = ": ",
) -> dict[str, list[str]]:
    """上游 `label_context()`：单变量等同 `label_value`，多变量等同 `label_both`。"""
    if len(labels) == 1:
        return label_value(labels, multi_line)
    return label_both(labels, multi_line, sep)


#: `labeller = "label_*"` 的字符串写法 → 函数（上游 `validate_labeller()`）。
_NAMED_LABELLERS: Mapping[str, Any] = {
    "label_value": label_value,
    "label_both": label_both,
    "label_context": label_context,
}


def _as_labeller(spec: Any) -> Any:
    """任意 labeller 写法 → 统一签名的函数 `f({变量: [值…]}) -> {变量: [标签…]}`。

    不认识的写法点名报错，不静默退回 `label_value`（标签错了却画得出来最难查）。
    """
    if spec is None:
        return label_value
    if isinstance(spec, str):
        if spec not in _NAMED_LABELLERS:
            raise FacetError(
                f"labeller 只能是 {', '.join(_NAMED_LABELLERS)}、"
                "{{变量: labeller}}、{值: 标签} 或函数，"
                f"收到 {spec!r}"
            )
        return _NAMED_LABELLERS[spec]
    if isinstance(spec, Mapping):
        if all(isinstance(value, Mapping) or callable(value) for value in spec.values()):
            return labeller(**{str(key): value for key, value in spec.items()})
        # `{值: 标签}` 简写：同一个值表作用到每个变量。
        table = {str(key): str(value) for key, value in spec.items()}

        def _by_value(labels: Mapping[str, Any]) -> dict[str, list[str]]:
            return {
                name: [table.get(str(value), str(value)) for value in values]
                for name, values in labels.items()
            }

        return _by_value
    if callable(spec):
        return spec
    raise FacetError(f"不认识的 labeller 写法 {spec!r}（label_* / 映射 / 函数）")


def labeller(
    _default: Any = "label_value",
    multi_line: bool = True,
    sep: str = ": ",
    **overrides: Any,
) -> Any:
    """上游 `labeller(..., .default = label_value)`：逐变量覆盖，其余走默认。

    ```python
    labeller(a={"q": "Q", "p": "P"}, b="label_both")
    ```
    """
    del multi_line, sep
    default = _as_labeller(_default)
    per_var = {str(name): _as_labeller(spec) for name, spec in overrides.items()}

    def apply(labels: Mapping[str, Any]) -> dict[str, list[str]]:
        base = default({name: list(values) for name, values in labels.items()})
        out: dict[str, list[str]] = {
            str(name): [str(v) for v in vals] for name, vals in base.items()
        }
        for name, values in labels.items():
            if name not in per_var:
                out.setdefault(name, [str(value) for value in values])
                continue
            mapped = per_var[name]({name: list(values)})
            labels_for_var = mapped.get(name, [str(value) for value in values])
            out[name] = [str(item) for item in labels_for_var]
        return out

    return apply


@dataclass(frozen=True, slots=True)
class FacetNull(FacetBase):
    """`facet_null()`：一张面板。布局与 M1-5 的单面板完全一致。"""

    kind: str = "null"

    def compute_layout(self, data: Sequence[ColumnTable] | ColumnTable) -> FacetLayout:
        return _layout_table(
            "null",
            (),
            [(1, 1, {"__SCALE_X": 1, "__SCALE_Y": 1}, {})],
            nrow=1,
            ncol=1,
        )


@dataclass(frozen=True, slots=True)
class FacetWrap(FacetBase):
    """`facet_wrap()`：一维面板流按 `dir` 折成行列。"""

    nrow: int | None = None
    ncol: int | None = None
    dir: str = "lt"
    as_table: bool = True
    strip_position: str = "top"
    space: str = "fixed"
    kind: str = "wrap"

    def __post_init__(self) -> None:
        for name in ("nrow", "ncol"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, int) or value < 1):
                raise FacetError(f"{name} 必须是 ≥ 1 的整数或 None，收到 {value!r}")
        if self.dir not in _WRAP_DIRS:
            raise FacetError(f"dir 只能是 {_WRAP_DIRS}，收到 {self.dir!r}")
        if self.strip_position != "top":
            raise FacetError(
                f"strip.position = {self.strip_position!r} 尚未实现；M1-6 只支持 'top'"
            )
        if self.space not in ("fixed", "free_x", "free_y"):
            raise FacetError(
                "facet_wrap 的 space 只能是 'fixed' / 'free_x' / 'free_y'（上游不接受 "
                f"'free'），收到 {self.space!r}"
            )
        if self.space == "free_x":
            # 上游：space = "free_x" 强制一行（列宽按 x 范围分配），并忽略 nrow/ncol。
            object.__setattr__(self, "nrow", 1)
            object.__setattr__(self, "ncol", None)
        elif self.space == "free_y":
            object.__setattr__(self, "ncol", 1)
            object.__setattr__(self, "nrow", None)

    def compute_layout(self, data: Sequence[ColumnTable] | ColumnTable) -> FacetLayout:
        layers = _as_layers(data)
        if not self.facet_vars:
            return FacetNull().compute_layout(layers)
        levels = _Levels(layers, self.facet_vars)
        combos, labels = _combos(layers, self.facet_vars, self.drop, levels)
        count = len(combos)
        nrow, ncol = _wrap_dims(count, self.nrow, self.ncol)
        rows: list[tuple[int, int, dict[str, Any], dict[str, str]]] = []
        for index, (combo, label) in enumerate(zip(combos, labels, strict=True), start=1):
            row, col = _wrap_position(index, nrow, ncol, self.dir)
            rows.append(
                (
                    row,
                    col,
                    {
                        **combo,
                        "__SCALE_X": index if self.free_x else 1,
                        "__SCALE_Y": index if self.free_y else 1,
                    },
                    label,
                )
            )
        return _layout_table("wrap", tuple(var.name for var in self.facet_vars), rows, nrow, ncol)


@dataclass(frozen=True, slots=True)
class FacetGrid(FacetBase):
    """`facet_grid(rows=..., cols=...)`：行 × 列面板矩阵。"""

    row_vars: tuple[FacetVar, ...] = ()
    col_vars: tuple[FacetVar, ...] = ()
    as_table: bool = True
    space: str = "fixed"
    margins: bool | tuple[str, ...] = False
    kind: str = "grid"

    def __post_init__(self) -> None:
        if self.space not in ("fixed", "free", "free_x", "free_y"):
            raise FacetError(
                f"space 只能是 'fixed' / 'free' / 'free_x' / 'free_y'，收到 {self.space!r}"
            )
        both = {var.name for var in self.row_vars} & {var.name for var in self.col_vars}
        if both:
            raise FacetError(
                f"分面变量只能出现在 rows 或 cols 之一，重复：{', '.join(sorted(both))}"
            )
        object.__setattr__(self, "facet_vars", self.row_vars + self.col_vars)
        margins = self.margins
        if isinstance(margins, str):
            margins = (margins,)
        if isinstance(margins, (list, tuple, set, frozenset)):
            names = tuple(str(name) for name in margins)
            known = {var.name for var in self.facet_vars}
            unknown = [name for name in names if name not in known]
            if unknown:
                raise FacetError(
                    f"margins 里的变量不在分面变量中：{', '.join(unknown)}"
                    f"（分面变量：{', '.join(sorted(known)) or '无'}）"
                )
            object.__setattr__(self, "margins", names)
        elif margins is not None and not isinstance(margins, bool):
            raise FacetError(f"margins 只能是逻辑值或变量名序列，收到 {margins!r}")

    # -- margins ------------------------------------------------------------

    @property
    def margin_sets(self) -> tuple[tuple[str, ...], ...]:
        """需要替换成 `"(all)"` 的变量集合（上游 `reshape_margins()`）。

        例：`rows = ("a", "b")`、`cols = ("g",)`、`margins = True` →
        `((), ("a", "b"), ("b",), ("g",), ("a", "b", "g"), ("b", "g"))`
        —— 空集是普通面板，其余每个集合追加一批 margin 面板。
        """
        return _margin_sets(
            tuple(var.name for var in self.row_vars),
            tuple(var.name for var in self.col_vars),
            self.margins,
        )

    def compute_layout(self, data: Sequence[ColumnTable] | ColumnTable) -> FacetLayout:
        layers = _as_layers(data)
        if not self.facet_vars:
            return FacetNull().compute_layout(layers)
        levels = _Levels(layers, self.facet_vars)
        row_names = [var.name for var in self.row_vars]
        col_names = [var.name for var in self.col_vars]
        # 上游 facet_grid：每一维是「该维已观察水平」的组合，再取两维的
        # **笛卡尔积**——缺数据的格子是空面板，不是被删掉。
        row_levels = _dimension_combos(layers, self.row_vars, self.drop, levels)
        col_levels = _dimension_combos(layers, self.col_vars, self.drop, levels)
        if not self.as_table:
            row_levels = list(reversed(row_levels))
        margin_sets = self.margin_sets
        margin_layout = any(margin_sets)
        if margin_layout:
            # margins 把分面值写成字符（`"(all)"` 与其它值同列）；map_data()
            # 也用 `_label()` 的口径比对，见 FacetGrid.map_data()。
            row_levels = _with_margins(row_levels, row_names, margin_sets)
            col_levels = _with_margins(col_levels, col_names, margin_sets)

        rows: list[tuple[int, int, dict[str, Any], dict[str, str]]] = []
        row_index = {value: index + 1 for index, value in enumerate(row_levels)}
        col_index = {value: index + 1 for index, value in enumerate(col_levels)}
        for row_value in row_levels:
            for col_value in col_levels:
                combo = dict(zip(row_names, row_value, strict=True)) if row_names else {}
                combo.update(dict(zip(col_names, col_value, strict=True)) if col_names else {})
                if margin_layout:
                    combo = {
                        name: value if value == _ALL else _label(value)
                        for name, value in combo.items()
                    }
                row = row_index[row_value]
                col = col_index[col_value]
                label = {var.name: _label(combo[var.name]) for var in self.facet_vars}
                rows.append(
                    (
                        row,
                        col,
                        {
                            **combo,
                            "__SCALE_X": col if self.free_x else 1,
                            "__SCALE_Y": row if self.free_y else 1,
                        },
                        label,
                    )
                )
        return _layout_table(
            "grid",
            tuple(var.name for var in self.facet_vars),
            rows,
            nrow=len(row_levels),
            ncol=len(col_levels),
        )

    def map_data(self, data: ColumnTable, layout: FacetLayout) -> PanelMap:
        """margins：一行数据同时落进普通面板与它所属的每个 margin 面板。"""
        if not any(self.margin_sets) or not self.facet_vars:
            return FacetBase.map_data(self, data, layout)
        missing = _missing_vars(data, self.facet_vars)
        if missing:
            # 缺少分面变量的层走通用的「按布局水平复制」路径（margin 面板不复制）。
            return FacetBase.map_data(self, data, layout)
        names = [var.name for var in self.facet_vars]
        key_map = {
            tuple(layout.value(panel, name) for name in names): panel for panel in layout.panel_ids
        }
        values = {
            var.name: [_label(value) for value in var.values(data)] for var in self.facet_vars
        }
        margin_sets = self.margin_sets
        panel_out: list[int] = []
        row_out: list[int] = []
        for index in range(data.nrows):
            keys: list[tuple[str, ...]] = [tuple(values[name][index] for name in names)]
            for margin in margin_sets:
                if not margin:
                    continue
                key = tuple(_ALL if name in margin else values[name][index] for name in names)
                if key not in keys:
                    keys.append(key)
            for key in keys:
                panel = key_map.get(key)
                if panel is None:  # pragma: no cover - 布局保证所有组合都在
                    continue
                panel_out.append(panel)
                row_out.append(index)
        return PanelMap(
            panels=np.array(panel_out, dtype=np.int64),
            rows=np.array(row_out, dtype=np.int64),
        )


def _as_layers(data: Sequence[ColumnTable] | ColumnTable) -> list[ColumnTable]:
    if isinstance(data, ColumnTable):
        return [data]
    layers = list(data)
    if not layers:
        return [ColumnTable()]
    return layers


#: margins 面板的分面值（上游 `reshape_add_margins()` 的 `"(all)"`）。
_ALL = "(all)"


def _margin_sets(
    row_names: Sequence[str],
    col_names: Sequence[str],
    margins: bool | tuple[str, ...] | None,
) -> tuple[tuple[str, ...], ...]:
    """`margins` → 需要替换成 `"(all)"` 的变量集合（上游 `reshape_margins()`）。

    顺序照 `expand.grid()`：第一个维度变化最快，空集（普通面板）排第一。
    `rows = ("a", "b")`、`cols = ("g",)`、`margins = True` 得到
    `((), ("a", "b"), ("b",), ("g",), ("a", "b", "g"), ("b", "g"))`
    —— 与 R 4.0.3 的 `reshape_margins()` 输出逐项一致（多变量的部分 margin 是
    从第一个被指定的变量到该维末尾的**后缀**）。
    """
    if margins is False or margins is None:
        return ()
    if margins is True:
        wanted = {str(name) for name in (*row_names, *col_names)}
    elif isinstance(margins, str):  # pragma: no cover - 归一化在 __post_init__
        wanted = {margins}
    else:
        wanted = {str(name) for name in margins}
    per_dim: list[tuple[tuple[str, ...], ...]] = []
    for dim in (tuple(row_names), tuple(col_names)):
        suffixes: list[tuple[str, ...]] = [()]
        for index, name in enumerate(dim):
            if name in wanted:
                suffix = dim[index:]
                if suffix not in suffixes:
                    suffixes.append(suffix)
        per_dim.append(tuple(suffixes))
    if not any(len(suffixes) > 1 for suffixes in per_dim):
        return ()
    sets: list[tuple[str, ...]] = []
    for col_suffix in per_dim[1]:
        for row_suffix in per_dim[0]:
            merged = (*row_suffix, *col_suffix)
            if merged not in sets:
                sets.append(merged)
    return tuple(sets)


def _with_margins(
    levels: Sequence[tuple[Any, ...]],
    names: Sequence[str],
    margin_sets: Sequence[tuple[str, ...]],
) -> list[tuple[Any, ...]]:
    """给一个 grid 维度补上 margin 组合，并按「原顺序 + `(all)` 最后」排序。"""
    if not names:
        return list(levels)
    order: dict[str, dict[Any, int]] = {name: {} for name in names}
    for level in levels:
        for name, value in zip(names, level, strict=True):
            order[name].setdefault(value, len(order[name]))
    out = list(levels)
    for level in levels:
        values = dict(zip(names, level, strict=True))
        for margin in margin_sets:
            affected = [name for name in names if name in margin]
            if not affected:
                continue
            candidate = tuple(_ALL if name in affected else value for name, value in values.items())
            if candidate not in out:
                out.append(candidate)
    out.sort(
        key=lambda level: tuple(
            (1, 0) if value == _ALL else (0, order[name][value])
            for name, value in zip(names, level, strict=True)
        )
    )
    return out


def _dimension_combos(
    layers: Sequence[ColumnTable],
    vars: Sequence[FacetVar],
    drop: bool,
    levels: _Levels,
) -> list[tuple[Any, ...]]:
    """一个 grid 维度的取值组合（上游 `facet_grid` 的 row / col 水平）。

    `drop = TRUE` 只取该维度里**观察到的**组合；`drop = FALSE` 取该维度各变量
    全部 levels 的笛卡尔积（含没出现的 factor level）。
    """
    names = [var.name for var in vars]
    if not names:
        return [()]
    if drop:
        seen: list[tuple[Any, ...]] = []
        for table in layers:
            if not all(_has_var(table, var) for var in vars):
                continue
            values = {var.name: var.values(table) for var in vars}
            for index in range(table.nrows):
                key = tuple(values[name][index] for name in names)
                if key not in seen:
                    seen.append(key)
        if not seen:
            wanted = "、".join(names)
            raise FacetError(
                f"分面变量（{wanted}）在数据里必须至少有一个值；"
                "请检查列名，或确认至少一层同时含有全部分面变量"
            )
        combos = seen
    else:
        combos = [tuple(combo[name] for name in names) for combo in _product(levels, names)]
    return sorted(
        combos,
        key=lambda key: tuple(
            levels.rank[name][value] for name, value in zip(names, key, strict=True)
        ),
    )


def _wrap_dims(n: int, nrow: int | None, ncol: int | None) -> tuple[int, int]:
    """上游 `wrap_dims()`：两边都不给时用 `n2mfrow()`，然后按需补另一边。"""
    if ncol is None and nrow is None:
        # grDevices::n2mfrow(n) = (rows, cols) = (ceil(sqrt(n)), ceil(n / ceil(sqrt(n)))),
        # 但 n ≤ 3 时是 (n, 1)；wrap_dims 交换两列后使用：
        #   n ≤ 3 → 1 × n；其余 → ceil(n / ceil(sqrt(n))) 行 × ceil(sqrt(n)) 列。
        # 覆盖 1..20：13 → 4 × 4，17 → 4 × 5，20 → 4 × 5（与 R 一致）。
        if n <= 3:
            nrow, ncol = 1, n
        else:
            ncol = math.ceil(math.sqrt(n))
            nrow = math.ceil(n / ncol)
    elif ncol is None:
        assert nrow is not None
        ncol = math.ceil(n / nrow)
    elif nrow is None:
        nrow = math.ceil(n / ncol)
    assert nrow is not None and ncol is not None
    if nrow * ncol < n:
        raise FacetError(
            f"需要 {n} 个面板，但 nrow × ncol = {nrow} × {ncol} 只放得下 {nrow * ncol} 个"
        )
    return nrow, ncol


def _wrap_position(index: int, nrow: int, ncol: int, direction: str) -> tuple[int, int]:
    """上游 `wrap_layout()`：1 起的面板号 → (ROW, COL)。"""
    if direction in ("lt", "rt"):
        row = (index - 1) // ncol + 1
    elif direction in ("tl", "tr"):
        row = (index - 1) % nrow + 1
    elif direction in ("lb", "rb"):
        row = nrow - (index - 1) // ncol
    else:  # bl, br
        row = nrow - (index - 1) % nrow
    if direction in ("lt", "lb"):
        col = (index - 1) % ncol + 1
    elif direction in ("tl", "bl"):
        col = (index - 1) // nrow + 1
    elif direction in ("rt", "rb"):
        col = ncol - (index - 1) % ncol
    else:  # tr, br
        col = ncol - (index - 1) // nrow
    return int(row), int(col)


# ---------------------------------------------------------------------------
# 组件 → 实现
# ---------------------------------------------------------------------------


def _free_from(scales: str | None) -> tuple[bool, bool]:
    key = "fixed" if scales is None else str(scales)
    if key not in FREE_SCALES:
        raise FacetError(f"scales 只能是 {', '.join(FREE_SCALES)}，收到 {scales!r}")
    return FREE_SCALES[key]


def _param(params: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    """R 的 `as.table` 与 Python 的 `as_table` 两种写法都认。"""
    for name in names:
        if name in params:
            return params[name]
    return default


def _wrap_dir(direction: str, as_table: bool) -> str:
    """`dir = "h" | "v"` → 4.0.3 的 8 方向（`as.table` 决定起点）。"""
    if direction in _WRAP_DIRS:
        return direction
    if direction == "h":
        return "lt" if as_table else "lb"
    if direction == "v":
        return "tl" if as_table else "tr"
    raise FacetError(f"dir 只能是 'h' / 'v' / {_WRAP_DIRS}，收到 {direction!r}")


def facet_from_component(component: Facet | FacetBase | None) -> FacetBase:
    """`ggcore.components.Facet`（名字 + 参数）→ 可执行的分面对象。"""
    if component is None:
        return FacetNull()
    if isinstance(component, FacetBase):
        return component
    if not isinstance(component, Facet):
        raise TypeError(f"facet 需要 ggcore.components.Facet，收到 {type(component).__name__}")
    name = component.name
    params = dict(component.params)
    if name == "null":
        return FacetNull(labeller=params.get("labeller", "label_value"))
    if name == "wrap":
        as_table = bool(_param(params, "as_table", "as.table", default=True))
        direction = _wrap_dir(str(params.get("dir", "h")), as_table)
        return FacetWrap(
            facet_vars=_facet_vars(params.get("facets")),
            free=_free_from(params.get("scales")),
            drop=bool(params.get("drop", True)),
            labeller=params.get("labeller", "label_value"),
            nrow=params.get("nrow"),
            ncol=params.get("ncol"),
            dir=direction,
            as_table=as_table,
            strip_position=str(_param(params, "strip_position", "strip.position", default="top")),
            space=str(params.get("space", "fixed")),
        )
    if name == "grid":
        as_table = bool(_param(params, "as_table", "as.table", default=True))
        return FacetGrid(
            free=_free_from(params.get("scales")),
            drop=bool(params.get("drop", True)),
            labeller=params.get("labeller", "label_value"),
            row_vars=_facet_vars(params.get("rows")),
            col_vars=_facet_vars(params.get("cols")),
            as_table=as_table,
            space=str(params.get("space", "fixed")),
            margins=params.get("margins", False),
        )
    raise FacetError(f"分面 {name!r} 尚未实现（已实现：null / wrap / grid）")


# ---------------------------------------------------------------------------
# gtable：面板矩形 + strip + panel.spacing
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Grob:
    """占位 grob：M1-6 只给结构，M1-7 换成真实 grob / IR 节点。"""

    kind: str
    name: str
    text: str | None = None
    panel: int | None = None
    side: str | None = None
    fill: str | None = None


@dataclass(frozen=True, slots=True)
class StripPart:
    """strip 里的一段：多变量分面时**每个变量一段**（上游逐变量堆叠/并排）。

    `text` 是该变量的标签（`label_value` 的口径；`label_both` 已带变量名）。
    """

    var: str
    text: str
    fill: str | None = None


@dataclass(frozen=True, slots=True)
class FacetStrip:
    """一条 strip 单元格：`side` 是 `"top"` / `"right"`。

    `parts` 按**绘制顺序**排列：顶部 strip 自上而下堆叠（最后一个变量最靠近
    面板，R 的 `weave_tables_row()`），右侧 strip 自左向右并排、同样最后一个
    变量最靠近面板（R `build_strip(horizontal = FALSE)` 先 `rev()` 行变量再
    `weave_tables_col()`，所以 `x + y ~ .` 的右侧第一格是 `y`）。单变量时只有
    一段，`text` 与 `parts[0].text` 相同。
    """

    name: str
    side: str
    text: str
    panel: int
    row: int
    col: int
    #: `strip.background.x` / `.y` 的 fill（`element_blank()` 时为 None）。
    fill: str | None = None
    parts: tuple[StripPart, ...] = ()
    #: `strip.placement = "outside"`：单元格不在 gtable 里，画在轴带之外。
    outside: bool = False

    @property
    def vars(self) -> tuple[str, ...]:
        return tuple(part.var for part in self.parts)


@dataclass(frozen=True, slots=True)
class FacetTable:
    """分面的 gtable + 可断言结构。"""

    layout: FacetLayout
    gtable: GTable
    panels: tuple[tuple[int, int, int, int, int], ...]
    """`(PANEL, t, l, b, r)`，1 起。"""
    strips: tuple[FacetStrip, ...]
    #: 顶部 strip 块的总高（cm；多变量时是各变量 strip 的堆叠高度之和）。
    strip_height_cm: float
    #: 右侧 strip 块的总宽（cm；多变量时是各变量 strip 的宽度之和）。
    strip_width_cm: float = 0.0
    #: 面板列的 null 权重（`space = "free"` 时来自逐面板范围差；否则全是 1）。
    width_weights: tuple[float, ...] = ()
    #: 面板行的 null 权重。
    height_weights: tuple[float, ...] = ()
    #: `strip.placement` 的解析值（`"inside"` / `"outside"`），按 top / right。
    top_placement: str = "inside"
    right_placement: str = "inside"
    #: grid 的 `respect = TRUE`：null 宽与 null 高取同一物理尺寸（R `init_gtable()`）。
    respect: bool = False
    #: `init_gtable()` 的 `aspect_ratio`（已折进行权重）；`respect=False` 时为 None。
    aspect_ratio: float | None = None

    def panel_boxes(
        self,
        width_cm: float,
        height_cm: float,
        *,
        ctx: UnitContext | None = None,
    ) -> dict[int, CellBox]:
        """面板矩形（cm；尺寸来自 gtable 的行列，不含坐标轴/图例留白）。"""
        sizes = self.gtable.resolve(width_cm, height_cm, ctx=ctx)
        boxes: dict[int, CellBox] = {}
        for panel, top, left, bottom, right in self.panels:
            boxes[panel] = self.gtable.region_box(
                top,
                left,
                bottom,
                right,
                width_cm=width_cm,
                height_cm=height_cm,
                sizes=sizes,
            )
        return boxes

    def strip_for(self, panel: int, side: str = "top") -> FacetStrip | None:
        return next(
            (strip for strip in self.strips if strip.panel == panel and strip.side == side),
            None,
        )


def facet_table(
    layout: FacetLayout,
    facet: FacetBase | None = None,
    theme: Theme | ResolvedTheme | None = None,
    metrics: Any = None,
    ranges: Mapping[int, tuple[Sequence[float] | None, Sequence[float] | None]] | None = None,
    *,
    aspect: float | None = None,
    right_inside: bool = False,
) -> FacetTable:
    """布局 → 面板 gtable（panel 行列 + strip + panel.spacing）。

    `ranges` 给出每个面板的 `(x_range, y_range)`（`PanelParams` 的量）时，
    `space = "free"` 的面板按范围差分配 null 权重（上游 `Facet$init_gtable()`）。

    `aspect` 是 R `init_gtable(aspect_ratio =)` 的那个值（**已解析**：`coord_fixed`
    的 `ratio`，或 `coord$aspect(ranges[[1]])`）。按上游口径折进**行权重**
    （`heights × |aspect|`），并令 `respect = TRUE`（null 宽 = null 高）；这样
    `space = "free"` 时每个面板的高/宽自动等于 `ratio × yspan / xspan`，不会被
    再乘一次范围。`None` = 不等比例（`respect = FALSE`，行列权重都是原值）。

    `right_inside` 把右侧 strip 强制回退成 `"inside"`：右侧有次轴带时
    `strip.placement = "outside"` 会压到次轴标签上（见 `docs/notes/facet.md` §7）。

    strip 的尺寸走 `_strip_extent()`：真实 `stringWidth`（有 `metrics` 时）/ 行高，
    随文字角度与变量个数变化——多变量分面每个变量一条 strip（堆叠/并排）。
    """
    facet = facet_from_component(facet) if facet is not None else FacetNull()
    resolved = theme if isinstance(theme, ResolvedTheme) else resolve_theme(theme or Theme())
    spacing_x = _unit_cm(resolved, "panel.spacing.x")
    spacing_y = _unit_cm(resolved, "panel.spacing.y")

    nrow, ncol = layout.nrow, layout.ncol
    if facet.kind == "wrap":
        top_names: tuple[str, ...] = layout.facet_vars
        right_names: tuple[str, ...] = ()
    elif facet.kind == "grid":
        top_names = tuple(var.name for var in getattr(facet, "col_vars", ()))
        right_names = tuple(var.name for var in getattr(facet, "row_vars", ()))
    else:
        top_names, right_names = (), ()

    top_fill = _strip_fill(resolved, "strip.background.x") if top_names else None
    right_fill = _strip_fill(resolved, "strip.background.y") if right_names else None

    # 顶部 / 右侧的锚点：wrap 是每个面板，grid 是每列 / 每行（取该行/列首个面板）。
    top_anchors: list[tuple[int, int, int]] = []
    if top_names:
        if facet.kind == "wrap":
            top_anchors = [
                (panel, layout.row_of(panel), layout.col_of(panel)) for panel in layout.panel_ids
            ]
        else:
            top_anchors = [
                (layout.panels_in_col(col)[0], 1, col)
                for col in range(1, ncol + 1)
                if layout.panels_in_col(col)
            ]
    right_anchors: list[tuple[int, int, int]] = []
    if right_names:
        right_anchors = [
            (layout.panels_in_row(row)[0], row, 1)
            for row in range(1, nrow + 1)
            if layout.panels_in_row(row)
        ]

    top_labels = {
        panel: _labels_for(layout, facet, panel, top_names) for panel, _, _ in top_anchors
    }
    right_labels = {
        panel: _labels_for(layout, facet, panel, right_names) for panel, _, _ in right_anchors
    }

    def _extents(
        names: Sequence[str],
        labels: Mapping[int, Mapping[str, str]],
        element: str,
        horizontal: bool,
    ) -> dict[str, float]:
        out: dict[str, float] = {}
        for name in names:
            texts = [values[name] for values in labels.values() if name in values]
            out[name] = _strip_extent(
                resolved, element, horizontal=horizontal, metrics=metrics, texts=texts
            )
        return out

    top_extents = _extents(top_names, top_labels, "strip.text.x", False)
    right_extents = _extents(right_names, right_labels, "strip.text.y", True)
    strip_h = float(sum(top_extents.values()))
    strip_w = float(sum(right_extents.values()))

    # `space = "free"`：面板宽高按范围差分配（上游 `init_gtable()` 读 ROW==1 /
    # COL==1 的面板范围；wrap 的 space 只能是 free_x / free_y，行列数因此是 1）。
    # `aspect` 按上游口径折进**行权重**（`heights × |aspect|`）并开 `respect`：
    # null 宽 = null 高，面板高/宽因此是 `aspect × yspan / xspan`（free 时每列 /
    # 行权重已是范围差，不能再拿 `aspect_ratio` 乘一次，见 SIL-759）。
    space = str(getattr(facet, "space", "fixed") or "fixed")
    respect = aspect is not None
    aspect_scale = 1.0 if aspect is None else abs(float(aspect))
    width_weights = tuple(
        _span_weight(ranges, layout, col=col, axis="x") if space in ("free", "free_x") else 1.0
        for col in range(1, ncol + 1)
    )
    height_weights = tuple(
        (_span_weight(ranges, layout, row=row, axis="y") if space in ("free", "free_y") else 1.0)
        * aspect_scale
        for row in range(1, nrow + 1)
    )
    top_placement = str(resolved.get("strip.placement.x") or "inside")
    right_placement = str(resolved.get("strip.placement.y") or "inside")
    if right_inside and right_names:
        # 右侧有次轴带时 `outside` 会压到次轴标签上；M2-1 把次轴版式收好之前
        # 显式回退 inside（strip 占 gtable 列，落在面板与次轴之间，不重叠）。
        right_placement = "inside"
    # `outside` 的 strip 不占 gtable 行列：它画在轴带之外，空间由整页版式
    # （`plot_layout()`）另算。
    outside_top = bool(top_names) and top_placement == "outside"
    outside_right = bool(right_names) and right_placement == "outside"

    # wrap 的每个面板行上方都有一条 strip；grid 的顶部 strip 只有一行。
    strip_each_row = bool(top_names) and facet.kind == "wrap" and not outside_top

    widths: list[Unit] = []
    for col in range(1, ncol + 1):
        if col > 1:
            widths.append(spacing_x)
        widths.append(unit(width_weights[col - 1], "null"))
    heights: list[Unit] = []
    for row in range(1, nrow + 1):
        if row > 1:
            heights.append(spacing_y)
        if strip_each_row or (top_names and not outside_top and row == 1):
            heights.append(unit(strip_h, "cm"))
        heights.append(unit(height_weights[row - 1], "null"))
    if right_names and not outside_right:
        widths.append(unit(strip_w, "cm"))

    def _row(row: int) -> int:
        base = 2 if (top_names and not outside_top) else 1
        stride = 2 + (1 if strip_each_row else 0)
        return base + stride * (row - 1)

    def _col(col: int) -> int:
        return 2 * col - 1

    placements: list[Placement] = []
    grobs: list[_Grob] = []
    panels: list[tuple[int, int, int, int, int]] = []
    strips: list[FacetStrip] = []

    for panel in layout.panel_ids:
        row, col = layout.row_of(panel), layout.col_of(panel)
        top, left = _row(row), _col(col)
        name = f"panel-{col}-{row}"
        placements.append(Placement(t=top, l=left, b=top, r=left, z=1, clip="off", name=name))
        grobs.append(_Grob("panel", name, panel=panel))
        panels.append((panel, top, left, top, left))
        # grid 的顶部 strip 只有一行（每列一条）；wrap 每个面板行都有一条。
        if top_names and (facet.kind != "grid" or row == 1):
            labels = top_labels[panel]
            parts = tuple(
                StripPart(name, labels[name], top_fill) for name in top_names if name in labels
            )
            text = "\n".join(part.text for part in parts)
            strip_name = f"strip-t-{col}-{row}" if facet.kind == "wrap" else f"strip-t-{col}"
            if not outside_top:
                placements.append(
                    Placement(
                        t=top - 1,
                        l=left,
                        b=top - 1,
                        r=left,
                        z=2,
                        clip="off",
                        name=strip_name,
                    )
                )
            if not outside_top:
                grobs.append(
                    _Grob("strip", strip_name, text=text, panel=panel, side="top", fill=top_fill)
                )
            strips.append(
                FacetStrip(
                    name=strip_name,
                    side="top",
                    text=text,
                    panel=panel,
                    row=row,
                    col=col,
                    fill=top_fill,
                    parts=parts,
                    outside=outside_top,
                )
            )

    if right_names:
        right = len(widths)
        for row in range(1, nrow + 1):
            panels_in_row = layout.panels_in_row(row)
            if not panels_in_row:
                continue
            panel = panels_in_row[0]
            labels = right_labels[panel]
            # R `build_strip(horizontal = FALSE)` 对右侧 strip 先 `rev()` 行变量再
            # `weave_tables_col()`：最后一个变量在最左（最靠近面板）。顶部堆叠
            # 不反转（R 的 `horizontal = TRUE` 分支直接 weave）。
            parts = tuple(
                StripPart(name, labels[name], right_fill)
                for name in reversed(right_names)
                if name in labels
            )
            text = "\n".join(part.text for part in parts)
            name = f"strip-r-{row}"
            t = _row(row)
            if not outside_right:
                placements.append(Placement(t=t, l=right, b=t, r=right, z=2, clip="off", name=name))
            if not outside_right:
                grobs.append(
                    _Grob(
                        "strip",
                        name,
                        text=text,
                        panel=panel,
                        side="right",
                        fill=right_fill,
                    )
                )
            strips.append(
                FacetStrip(
                    name=name,
                    side="right",
                    text=text,
                    panel=panel,
                    row=row,
                    col=0,
                    fill=right_fill,
                    parts=parts,
                    outside=outside_right,
                )
            )

    table = gtable(widths=widths, heights=heights, name="layout")
    table = GTable(
        widths=table.widths,
        heights=table.heights,
        name="layout",
        grobs=tuple(grobs),
        layout=tuple(placements),
    )
    return FacetTable(
        layout=layout,
        gtable=table,
        panels=tuple(panels),
        strips=tuple(strips),
        strip_height_cm=strip_h,
        strip_width_cm=strip_w,
        width_weights=width_weights,
        height_weights=height_weights,
        top_placement=top_placement,
        right_placement=right_placement,
        respect=respect,
        aspect_ratio=aspect,
    )


def facet_aspect(
    facet: FacetBase | None,
    coord: Any,
    params: Any,
    theme_aspect: float | None = None,
) -> float | None:
    """`init_gtable()` 的 `aspect_ratio`（R `FacetGrid$draw_panels` 的解析）。

    上游 4.0.3 的顺序：

    - `theme$aspect.ratio` 优先（`aspect_ratio %||% ...`），任何 facet 都认；
    - `space` 两维都 free（只有 grid 的 `"free"`）且坐标不自由（`coord_fixed`）：
      `aspect = coord$ratio`——**不是** `coord$aspect()`，范围差已经由行列权重承担；
    - 其余情形：`aspect = coord$aspect(ranges[[1]])`，即首个面板的
      `PanelParams.aspect_ratio`（`ratio × yspan / xspan`；polar 是 1）。

    自由刻度与 `coord_fixed` 的非法组合在 `build._build_plot_facets()` 就报错，
    这里不重复判定（`params` 为 None 时给 None）。
    """
    if theme_aspect is not None:
        return abs(float(theme_aspect))
    if facet is None or getattr(facet, "kind", "null") == "null":
        return params.aspect_ratio if params is not None else None
    space = str(getattr(facet, "space", "fixed") or "fixed")
    ratio = getattr(coord, "ratio", None)
    if ratio is not None and space == "free":
        return abs(float(ratio))
    return params.aspect_ratio if params is not None else None


def _labels_for(
    layout: FacetLayout,
    facet: FacetBase,
    panel: int,
    names: Sequence[str],
) -> dict[str, str]:
    """一个面板在给定变量集合上的逐变量标签（走 labeller）。"""
    if not names:
        return {}
    values = {name: [layout.label(panel, name)] for name in names}
    labels = _labeller(facet.labeller, values)
    return {name: labels[name][0] for name in names}


def _span_weight(
    ranges: Mapping[int, tuple[Sequence[float] | None, Sequence[float] | None]] | None,
    layout: FacetLayout,
    *,
    col: int | None = None,
    row: int | None = None,
    axis: str,
) -> float:
    """一个面板列 / 行的 null 权重 = 该面板范围差（上游 `init_gtable()`）。

    x 权重取 `ROW == 1` 的面板（grid 每列顶端；wrap 的 space=free_x 只有一行），
    y 权重取 `COL == 1` 的面板。找不到时退回该列 / 行里第一个面板，再退回 1。
    """
    if not ranges:
        return 1.0
    order = [1, None]
    for wanted_row in order:
        for panel in layout.panel_ids:
            if col is not None and layout.col_of(panel) != col:
                continue
            if row is not None and layout.row_of(panel) != row:
                continue
            if axis == "x" and wanted_row is not None:
                if layout.row_of(panel) != wanted_row:
                    continue
            if axis == "y" and wanted_row is not None:
                if layout.col_of(panel) != wanted_row:
                    continue
            entry = ranges.get(panel)
            if entry is None:
                continue
            spread = entry[0] if axis == "x" else entry[1]
            if spread is None or len(spread) < 2:
                continue
            value = abs(float(spread[1]) - float(spread[0]))
            if value > 0:
                return value
    return 1.0


def _unit_cm(resolved: ResolvedTheme, name: str) -> Unit:
    value = resolved[name]
    if isinstance(value, Unit):
        return value
    if isinstance(value, (int, float)):
        return unit(float(value), "cm")
    raise FacetError(f"主题元素 {name!r} 不是单位：{value!r}")


def _strip_extent(
    resolved: ResolvedTheme,
    element_name: str = "strip.text.x",
    *,
    horizontal: bool = False,
    metrics: Any = None,
    texts: Sequence[str] = (),
) -> float:
    """strip 单元格的宽（`horizontal=True`）/ 高（cm），含 margin。空白元素为 0。

    口径照 grid 的 `widthDetails()` / `heightDetails()`：

    - 文字不旋转（angle 0 / 180）：宽 = 最宽一行的 `stringWidth`，高 = 行高 × 行数；
    - 文字旋转 90°（`strip.text.y` 默认 -90）：两者对调——宽 = 行高 × 行数，
      高 = 最宽一行的宽度。grid 的旋转不改变文字本身的量测，只是把「横/竖」换位。

    行高用 `text_line_cm()`（`TEXT_LINE_EM` = R 的 `stringHeight()` + descent，
    见 docs/notes/guide.md）；宽度走 `text_width_cm()`：有 `metrics` 时是真实
    `stringWidth`，没有时按 `FALLBACK_CHAR_EM` 估。

    SIL-715 #8：旧实现对**列宽**也套 `TEXT_LINE_EM`（7.87pt），而 `theme_void()`
    的 strip 文字是 angle 0，`stringWidth("u")` 只有 4.909pt（R 4.0.3 + svglite；
    `t` 只有 2.45pt）——`.facet-grid-ab` 的右 strip 列因此偏宽 3pt，面板整体
    左移。这里按真实宽度量。
    """
    element = resolved[element_name]
    if isinstance(element, ElementBlank) or not isinstance(element, ElementText):
        return 0.0
    size = float(element.size or 0.0)
    # 主题没写 family 时按设备的默认 sans（与 svglite 的 Arimo 同度量）量宽；
    # `text_width_cm()` 的缺省字面是布局用的 Noto Sans，比 R 的 'u' 宽 10%。
    family = element.family or "sans"
    angle = float(element.angle or 0.0)
    # grid 的 `rot` 只在绘制时生效，量测时把 90° / 270° 当成「横竖对调」。
    rotated = abs(angle % 180.0) > 1e-9
    lines = [text for text in texts if text] or [""]
    widest = max(text_width_cm(text, size, metrics, family) for text in lines)
    row_count = max((text.count("\n") + 1 for text in texts if text), default=1)
    line = text_line_cm(size) * row_count
    mt, mr, mb, ml = margin_sides_cm(element.margin)
    if horizontal:
        return (line if rotated else widest) + ml + mr
    return (widest if rotated else line) + mt + mb


def _strip_fill(resolved: ResolvedTheme, element_name: str) -> str | None:
    """`strip.background.x/.y` 的 fill；`element_blank()` 或 NA 给 None。"""
    element = resolved[element_name]
    if not isinstance(element, ElementRect):
        return None
    return element.fill if isinstance(element.fill, str) else None

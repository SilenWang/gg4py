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

`margins = TRUE` 与 `space = "free"` 还没有实现（见
`docs/notes/facet.md` 的账本）。
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
from ggcore.units import Unit, UnitContext, convert_height, unit

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
    "facet_from_component",
    "facet_table",
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

#: R `as.character()` 对单行文本的近似高度（em）。上游 strip 高度 =
#: `stringHeight()` + 上下 margin；8.8pt 字号下 R 量的 8.4pt（≈0.955em）。
#: M1-7 接上真实文字度量后换成 `MetricProvider.strheight()`。
_STRIP_TEXT_EM = 0.955


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

    def _strip_text(self, layout: FacetLayout, panel: int) -> str:
        values = {name: layout.label(panel, name) for name in layout.facet_vars}
        labels = _labeller(self.labeller, {name: [value] for name, value in values.items()})
        return "\n".join(labels[name][0] or "" for name in layout.facet_vars)


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
    """`labeller` → `{变量名: [标签…]}`。

    支持 `"label_value"`（默认）、`{变量: {值: 标签}}` 映射与 `f(labels)`
    函数（输入输出都是同一个 dict 形状，便于测试）。
    """
    if labeller is None or labeller == "label_value":
        return {name: list(values) for name, values in labels.items()}
    if callable(labeller):
        result = labeller({name: list(values) for name, values in labels.items()})
        if not isinstance(result, Mapping):
            raise FacetError("labeller 函数必须返回 {变量名: [标签…]}")
        return {str(name): [str(item) for item in values] for name, values in result.items()}
    if isinstance(labeller, Mapping):
        out: dict[str, list[str]] = {}
        for name, values in labels.items():
            table = labeller.get(name, {})
            if not isinstance(table, Mapping):
                raise FacetError(f"labeller[{name!r}] 必须是 {{值: 标签}} 映射")
            out[name] = [str(table.get(value, value)) for value in values]
        return out
    raise FacetError(f"不认识的 labeller 写法 {labeller!r}（label_value / 映射 / 函数）")


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
        if self.space not in ("fixed", "free", "free_x", "free_y"):
            raise FacetError(
                f"space 只能是 'fixed' / 'free' / 'free_x' / 'free_y'，收到 {self.space!r}"
            )
        if self.space != "fixed":
            # 上游按面板范围给 null 单位分配权重；当前 gtable 只有等宽面板。
            # 报错而不是静默按 fixed 画（见 docs/notes/facet.md §7 的后续任务）。
            raise FacetError(
                f"facet_wrap(space = {self.space!r}) 尚未实现：面板宽高要按数据范围"
                "分配 null 权重，留给后续任务 M1-6+「facet space 的面板尺寸约束」；"
                "M1-6 只支持 'fixed'"
            )

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
    margins: bool = False
    kind: str = "grid"

    def __post_init__(self) -> None:
        if self.margins:
            # TODO(M1-6+)：`margins = TRUE` 要在 base 上 reshape_add_margins()
            # 追加「全部」行/列；M1-6 先支持 FALSE。
            raise FacetError("facet_grid(margins = True) 尚未实现（M1-6 只支持 False）")
        if self.space not in ("fixed", "free", "free_x", "free_y"):
            raise FacetError(
                f"space 只能是 'fixed' / 'free' / 'free_x' / 'free_y'，收到 {self.space!r}"
            )
        if self.space != "fixed":
            raise FacetError(
                f"space = {self.space!r} 尚未实现；M1-6 只支持 'fixed'"
                "（space = 'free' 会按范围分配面板宽高）"
            )
        both = {var.name for var in self.row_vars} & {var.name for var in self.col_vars}
        if both:
            raise FacetError(
                f"分面变量只能出现在 rows 或 cols 之一，重复：{', '.join(sorted(both))}"
            )
        object.__setattr__(self, "facet_vars", self.row_vars + self.col_vars)

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

        rows: list[tuple[int, int, dict[str, Any], dict[str, str]]] = []
        row_index = {value: index + 1 for index, value in enumerate(row_levels)}
        col_index = {value: index + 1 for index, value in enumerate(col_levels)}
        for row_value in row_levels:
            for col_value in col_levels:
                combo = dict(zip(row_names, row_value, strict=True)) if row_names else {}
                combo.update(dict(zip(col_names, col_value, strict=True)) if col_names else {})
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


def _as_layers(data: Sequence[ColumnTable] | ColumnTable) -> list[ColumnTable]:
    if isinstance(data, ColumnTable):
        return [data]
    layers = list(data)
    if not layers:
        return [ColumnTable()]
    return layers


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
            margins=bool(params.get("margins", False)),
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
class FacetStrip:
    """一条 strip：`side` 是 `"top"` / `"right"`，`text` 已按 labeller 折行。"""

    name: str
    side: str
    text: str
    panel: int
    row: int
    col: int
    #: `strip.background.x` / `.y` 的 fill（`element_blank()` 时为 None）。
    fill: str | None = None


@dataclass(frozen=True, slots=True)
class FacetTable:
    """分面的 gtable + 可断言结构。"""

    layout: FacetLayout
    gtable: GTable
    panels: tuple[tuple[int, int, int, int, int], ...]
    """`(PANEL, t, l, b, r)`，1 起。"""
    strips: tuple[FacetStrip, ...]
    strip_height_cm: float
    strip_width_cm: float = 0.0

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
) -> FacetTable:
    """布局 → 面板 gtable（panel 行列 + 顶部/右侧 strip + panel.spacing）。"""
    facet = facet_from_component(facet) if facet is not None else FacetNull()
    resolved = theme if isinstance(theme, ResolvedTheme) else resolve_theme(theme or Theme())
    spacing_x = _unit_cm(resolved, "panel.spacing.x")
    spacing_y = _unit_cm(resolved, "panel.spacing.y")

    nrow, ncol = layout.nrow, layout.ncol
    if facet.kind == "wrap":
        has_top = bool(layout.facet_vars)
    elif facet.kind == "grid":
        has_top = bool(getattr(facet, "col_vars", ()))
    else:
        has_top = False
    has_right = facet.kind == "grid" and bool(getattr(facet, "row_vars", ()))
    # 顶部 strip 跟 `strip.text.x`、右侧 strip 跟 `strip.text.y`（尺寸与背景各走
    # 自己的元素；`strip.background.x/.y` 继承自 `strip.background`）。
    strip_h = _strip_extent(resolved, "strip.text.x", horizontal=False) if has_top else 0.0
    strip_w = _strip_extent(resolved, "strip.text.y", horizontal=True) if has_right else 0.0
    top_fill = _strip_fill(resolved, "strip.background.x") if has_top else None
    right_fill = _strip_fill(resolved, "strip.background.y") if has_right else None
    # wrap 的每个面板行上方都有一条 strip；grid 的顶部 strip 只有一行。
    strip_each_row = has_top and facet.kind == "wrap"

    widths: list[Unit] = []
    for col in range(ncol):
        if col:
            widths.append(spacing_x)
        widths.append(unit(1.0, "null"))
    heights: list[Unit] = []
    for row in range(1, nrow + 1):
        if row > 1:
            heights.append(spacing_y)
        if has_top and (strip_each_row or row == 1):
            heights.append(unit(strip_h, "cm"))
        heights.append(unit(1.0, "null"))
    if has_right:
        widths.append(unit(strip_w, "cm"))

    def _row(row: int) -> int:
        base = 2 if has_top else 1
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
        if has_top and (facet.kind != "grid" or row == 1):
            text = _panel_label(layout, facet, panel)
            strip_name = f"strip-t-{col}-{row}" if facet.kind == "wrap" else f"strip-t-{col}"
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
                )
            )

    if has_right:
        right = len(widths)
        for row in range(1, nrow + 1):
            panels_in_row = layout.panels_in_row(row)
            if not panels_in_row:
                continue
            text = _row_label(layout, facet, panels_in_row[0])
            name = f"strip-r-{row}"
            t = _row(row)
            placements.append(Placement(t=t, l=right, b=t, r=right, z=2, clip="off", name=name))
            grobs.append(
                _Grob(
                    "strip",
                    name,
                    text=text,
                    panel=panels_in_row[0],
                    side="right",
                    fill=right_fill,
                )
            )
            strips.append(
                FacetStrip(
                    name=name,
                    side="right",
                    text=text,
                    panel=panels_in_row[0],
                    row=row,
                    col=0,
                    fill=right_fill,
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
    )


def _panel_label(layout: FacetLayout, facet: FacetBase, panel: int) -> str:
    if facet.kind == "grid":
        names = tuple(var.name for var in getattr(facet, "col_vars", ()))
    else:
        names = layout.facet_vars
    return _label_for(layout, facet, panel, names)


def _row_label(layout: FacetLayout, facet: FacetBase, panel: int) -> str:
    names = tuple(var.name for var in getattr(facet, "row_vars", ()))
    return _label_for(layout, facet, panel, names)


def _label_for(
    layout: FacetLayout,
    facet: FacetBase,
    panel: int,
    names: Sequence[str],
) -> str:
    if not names:
        return ""
    values = {name: [layout.label(panel, name)] for name in names}
    labels = _labeller(facet.labeller, values)
    return "\n".join(labels[name][0] or "" for name in names)


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
) -> float:
    """strip 的高/宽（cm）：文本行高 + 上下（左右）margin。空白元素为 0。"""
    element = resolved[element_name]
    if isinstance(element, ElementBlank) or not isinstance(element, ElementText):
        return 0.0
    size = float(element.size or 0.0)
    text_cm = size * _STRIP_TEXT_EM * 2.54 / 72.0
    margin = element.margin
    if margin is None:
        return text_cm
    ctx = UnitContext()
    sides = (margin.l, margin.r) if horizontal else (margin.t, margin.b)
    extra = 0.0
    for side in sides:
        if side is not None:
            extra += float(np.asarray(convert_height(side, "cm", ctx=ctx)).sum())
    return text_cm + extra


def _strip_fill(resolved: ResolvedTheme, element_name: str) -> str | None:
    """`strip.background.x/.y` 的 fill；`element_blank()` 或 NA 给 None。"""
    element = resolved[element_name]
    if not isinstance(element, ElementRect):
        return None
    return element.fill if isinstance(element.fill, str) else None

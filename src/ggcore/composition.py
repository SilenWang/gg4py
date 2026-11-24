"""多图合并（M3-1 / SIL-1001）：patchwork 式组合骨架 + panel 几何对齐。

口径钉 patchwork 1.3.2（`R/plot_patchwork.R` / `R/plot_layout.R` 的实测源码）：

- 每个子图先走 :func:`ggcore.plot_gtable.plot_gtable`（`ggplotGrob()` 的对等物），
  再压成**标准 18×15 子表**（`TABLE_ROWS` / `TABLE_COLS`，panel 在 `(10, 8)`）；
- 按 layout 网格把子表拼进一张大表：**同一 layout 列的子图逐槽位取 max 列宽、
  同一 layout 行的子图逐槽位取 max 行高**（`table_dims()`），panel 行 / 列换成
  `null` 权重（`set_panel_dimensions()`）；
- 结果是普通 :class:`ggcore.gtable.GTable`，经 `scene([gtable], tree)` /
  `plotspec.build_scene({"gtable": ...})` 输出 IR —— **IR 不改**；
- 嵌套组合（`(p1 | p2) / (p3 | p4)`）是「内层大表压成 18×15 子表再参与外层」，
  与 patchwork 一样**跨嵌套层不对齐**（官方 vignette 的已知行为）。

## API

```python
import gg4py

(p1 | p2) / p3          # `|` 并排、`/` 上下（Python 优先级：/ 与 * > + > |）
p1 + p2 + plot_layout(ncol=2, widths=[2, 1])
gg4py.wrap_plots(p1, p2, p3, ncol=2, byrow=True)
gg4py.plot_spacer()     # 占位空格
```

`+`（plot + plot）按 patchwork 语义**追加**；加 `plot_layout(...)` 则更新网格
设置；加 `theme()` / `geom_*()` 等仍是原来的单图路径（`gg_add` 先按组件类型
分派，只有 ggplot / Patchwork / Spacer / PatchLayout 才进组合层）。

## 18×15 规范化

patchwork 的 `plot_table()` 是 `ggplotGrob()` + `add_strips()`：单面板的
16×13 表在 panel 四条边各补一条 0mm 的 strip 行 / 列 → 18×15，panel 落在
`(10, 8)`。带分面的表多行多列，`simplify_gt()` 先把 panel 块**坍缩**成 1 行
1 列（块里所有行列求和），再补缺失的 strip —— 同样回到 18×15。这里照做，
但只保留单位向量（渲染不用原表的语义槽位，见下）。

## 渲染

`plot_gtable()` 的 grob 是**语义槽位**（`PanelSlot` / `PlotCell`），不携带轴的
刻度、图例等绘制信息，不能直接画。所以组合表的每个子图块放一棵**实际渲染
树**（`geom.scene.page_grobs()` 的产物）：组合表解析出块矩形与块内 panel 矩形，
子图用 `plot_layout(panel_box=...)` 以「组合表给的 panel 矩形」重算版式，于是
渲染出来的 panel 与表级 panel 逐值一致。

已知差异（`docs/notes/composition.md`）：

- 子图的固定槽位（标题 / 轴 / 图例 / margin）按**子图自身**尺寸贴着 panel
  摆，跨图只统一 panel 几何；patchwork 会把槽位宽度也统一（标题会在统一列里
  居中）。本 issue 的验收项是 panel 矩形，这一项留给后续 stage；
- `guides="collect"` / `guide_area()` / 轴收集 / panel_spacing 不在本期（SIL-1002
  起）。
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from ggcore.build import build_plot
from ggcore.geom.scene import Box, page_grobs
from ggcore.geom.scene import plot_layout as scene_layout
from ggcore.gtable import GTable, Placement
from ggcore.plot_gtable import plot_gtable
from ggcore.units import (
    CM_PER_INCH,
    Unit,
    UnitContext,
    convert_height,
    convert_width,
    unit,
    unit_c,
    unit_sum,
)

__all__ = [
    "PANEL_COL",
    "PANEL_ROW",
    "TABLE_COLS",
    "TABLE_ROWS",
    "ComposeError",
    "PatchLayout",
    "Patchwork",
    "Spacer",
    "is_composable",
    "plot_layout",
    "plot_spacer",
    "wrap_plots",
]

#: 标准子表的行列数与 panel 落点（1 起），与 patchwork 的 `TABLE_ROWS` /
#: `TABLE_COLS` / `PANEL_ROW` / `PANEL_COL` 一致。
TABLE_ROWS = 18
TABLE_COLS = 15
PANEL_ROW = 10
PANEL_COL = 8


class ComposeError(ValueError):
    """组合层拒绝的输入（不是可组合对象、布局装不下、子表超出标准尺寸）。"""


# ---------------------------------------------------------------------------
# 公开对象
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PatchLayout:
    """`plot_layout()` 的返回值：网格设置（patchwork 的 `plot_layout` 对象）。"""

    ncol: int | None = None
    nrow: int | None = None
    byrow: bool | None = None
    widths: tuple[float, ...] | None = None
    heights: tuple[float, ...] | None = None

    def merged(self, other: PatchLayout) -> PatchLayout:
        """后给的设置覆盖先给的（`+ plot_layout()` 的语义；`None` 不覆盖）。"""
        return PatchLayout(
            ncol=other.ncol if other.ncol is not None else self.ncol,
            nrow=other.nrow if other.nrow is not None else self.nrow,
            byrow=other.byrow if other.byrow is not None else self.byrow,
            widths=other.widths if other.widths is not None else self.widths,
            heights=other.heights if other.heights is not None else self.heights,
        )


@dataclass(frozen=True, slots=True)
class Spacer:
    """`plot_spacer()`：一个空的 18×15 占位块（panel 一行一列 null）。"""


@dataclass(frozen=True)
class Patchwork:
    """patchwork 对象：子图（`ggplot` / `Patchwork` / `Spacer`）+ 网格设置。"""

    plots: tuple[Any, ...] = ()
    layout: PatchLayout = field(default_factory=PatchLayout)

    def __post_init__(self) -> None:
        for item in self.plots:
            if not is_composable(item):
                raise ComposeError(
                    f"不能把 {type(item).__name__} 放进组合；"
                    "可组合：ggplot / Patchwork / plot_spacer()"
                )
        object.__setattr__(self, "plots", tuple(self.plots))

    # -- 组合 ---------------------------------------------------------------

    def __add__(self, other: Any) -> Any:
        if isinstance(other, PatchLayout):
            return replace(self, layout=self.layout.merged(other))
        if is_composable(other):
            return replace(self, plots=(*self.plots, other))
        return NotImplemented

    def __or__(self, other: Any) -> Any:
        """`p1 | p2`：并排（同一行）。"""
        return _side_by_side(self, other)

    def __truediv__(self, other: Any) -> Any:
        """`p1 / p2`：上下（同一列）。"""
        return _stacked(self, other)

    def __mul__(self, other: Any) -> Any:
        raise TypeError(
            "组合层暂不支持 `*`（patchwork 的 `*` 是把右侧应用到每个子图）；"
            "并排用 `|`，上下用 `/`。注意 Python 里 `*` / `/` 的优先级高于 `+`："
            "`p1 + p2 | p3` 是 `(p1 + p2) | p3`，与 patchwork 一致。"
        )

    __rmul__ = __mul__

    # -- 渲染 / 表 -----------------------------------------------------------

    def gtable(
        self,
        *,
        metrics: Any = None,
        width_in: float = 7.0,
        height_in: float = 5.0,
    ) -> GTable:
        """合并成一张可绘制的 :class:`GTable`（`scene([gtable], tree)` 的输入）。"""
        return _build_gtable(self, metrics=metrics, width_in=width_in, height_in=height_in)

    def to_scene(
        self,
        *,
        metrics: Any = None,
        width_in: float = 7.0,
        height_in: float = 5.0,
    ) -> Any:
        """组合 → `ir.Scene`（走 `plotspec.build_scene({"gtable": ...})`）。"""
        from ggcore import plotspec

        table = self.gtable(metrics=metrics, width_in=width_in, height_in=height_in)
        return plotspec.build_scene(
            {"gtable": table, "size": [width_in, height_in]}, metrics=metrics
        )

    def __repr__(self) -> str:
        return f"<Patchwork: {len(self.plots)} plots, layout={self.layout!r}>"


def is_composable(value: Any) -> bool:
    """`value` 能不能进组合（`ggplot` / `Patchwork` / `Spacer`）。"""
    from ggcore.plot import ggplot

    return isinstance(value, (ggplot, Patchwork, Spacer))


def plot_spacer() -> Spacer:
    """patchwork 的 `plot_spacer()`：占位空格。"""
    return Spacer()


def plot_layout(
    *,
    ncol: int | None = None,
    nrow: int | None = None,
    byrow: bool | None = None,
    widths: Sequence[float] | None = None,
    heights: Sequence[float] | None = None,
) -> PatchLayout:
    """网格设置（patchwork 的 `plot_layout()`）。

    `widths` / `heights` 是**相对权重**（对应 `unit(widths, "null")`），不是绝对
    长度；长度不足时循环到列数 / 行数（与 patchwork 的 `rep(..., length.out=)` 一致）。
    """
    if ncol is not None and (isinstance(ncol, bool) or not isinstance(ncol, int) or ncol < 1):
        raise ComposeError(f"ncol 必须是 >= 1 的整数，收到 {ncol!r}")
    if nrow is not None and (isinstance(nrow, bool) or not isinstance(nrow, int) or nrow < 1):
        raise ComposeError(f"nrow 必须是 >= 1 的整数，收到 {nrow!r}")
    if byrow is not None and not isinstance(byrow, bool):
        raise ComposeError(f"byrow 必须是 bool，收到 {byrow!r}")
    return PatchLayout(
        ncol=ncol,
        nrow=nrow,
        byrow=byrow,
        widths=_weights(widths, "widths"),
        heights=_weights(heights, "heights"),
    )


def wrap_plots(*plots: Any, **kwargs: Any) -> Patchwork:
    """`wrap_plots(p1, p2, ...)` / `wrap_plots([p1, p2], ...)`。

    也接受 `ncol` / `nrow` / `byrow` / `widths` / `heights`（等同再 `+ plot_layout()`）。
    """
    layout = plot_layout(
        ncol=kwargs.pop("ncol", None),
        nrow=kwargs.pop("nrow", None),
        byrow=kwargs.pop("byrow", None),
        widths=kwargs.pop("widths", None),
        heights=kwargs.pop("heights", None),
    )
    if kwargs:
        unknown = ", ".join(sorted(kwargs))
        raise ComposeError(f"wrap_plots() 不认识这些参数：{unknown}")
    if len(plots) == 1 and isinstance(plots[0], (list, tuple)):
        plots = tuple(plots[0])
    if not plots:
        raise ComposeError("wrap_plots() 至少需要一张图")
    for item in plots:
        if not is_composable(item):
            raise ComposeError(
                "wrap_plots() 只认识 ggplot / Patchwork / plot_spacer()，收到 "
                f"{type(item).__name__}"
            )
    return Patchwork(plots=tuple(plots), layout=layout)


def _weights(values: Sequence[float] | None, name: str) -> tuple[float, ...] | None:
    if values is None:
        return None
    if isinstance(values, (str, bytes)):
        raise ComposeError(f"{name} 必须是数值序列，收到 {values!r}")
    out: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ComposeError(f"{name} 只能是数值，收到 {value!r}")
        number = float(value)
        if not math.isfinite(number) or number <= 0:
            raise ComposeError(f"{name} 必须是正的有限数值，收到 {value!r}")
        out.append(number)
    if not out:
        raise ComposeError(f"{name} 不能为空")
    return tuple(out)


def _side_by_side(left: Any, right: Any) -> Patchwork:
    """`|`：并排（patchwork `|.ggplot`）。

    左边已经是**一行**的 patchwork 时直接追加（`p1 | p2 | p3` 是 1×3）；
    否则把左右各当一个子图、新建一层 `nrow = 1`（`(p1 | p2) | (p3 | p4)` 是
    嵌套的两列，与 patchwork 的 `e1 - e2 + plot_layout(nrow = 1)` 同义）。
    """
    return _join(left, right, "nrow", "|")


def _stacked(left: Any, right: Any) -> Patchwork:
    """`/`：上下（patchwork `/.ggplot`），规则与 `|` 对称（`ncol = 1`）。"""
    return _join(left, right, "ncol", "/")


def _join(left: Any, right: Any, dim: str, op: str) -> Patchwork:
    if not is_composable(right):
        raise ComposeError(f"{type(right).__name__} 不能参与 `{op}`")
    if isinstance(left, Patchwork) and getattr(left.layout, dim) == 1:
        return replace(left, plots=(*left.plots, right))
    return Patchwork(
        plots=(left, right),
        layout=PatchLayout(**{dim: 1}),  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# 子表：18×15 规范化
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Sheet:
    """一个子图规范化后的表：15 个列宽 + 18 个行高（panel 在 (10, 8)）。"""

    widths: tuple[Unit, ...]
    heights: tuple[Unit, ...]


def _zero_unit() -> Unit:
    return unit(0.0, "cm")


def _panel_bounds(rows: Iterable[Placement]) -> tuple[int, int, int, int] | None:
    """子表的 panel 块包围盒（1 起，闭区间）。

    `plot_gtable()` 用 `panel` / `panel-*`；组合表（嵌套时）用 `panel-area-*`。
    两种都是「一个面板块」，嵌套时按包围盒整体坍缩。
    """
    rows = list(rows)
    panels = [row for row in rows if row.name == "panel" or row.name.startswith("panel-")]
    if not panels:
        return None
    return (
        min(row.t for row in panels),
        min(row.l for row in panels),
        max(row.b for row in panels),
        max(row.r for row in panels),
    )


def _sheet_from_table(table: GTable) -> _Sheet:
    """把 `plot_gtable()` 的表压成 18×15（panel 块坍缩 + 补 0 strip 行 / 列）。"""
    bounds = _panel_bounds(table.layout)
    if bounds is None:
        raise ComposeError("子图 gtable 里找不到 panel（plot_gtable() 的产物才有）")
    p_t, p_l, p_b, p_r = bounds
    widths = [Unit((element,)) for element in table.widths]
    heights = [Unit((element,)) for element in table.heights]
    if p_r > p_l:
        widths[p_l - 1 : p_r] = [unit_sum(*widths[p_l - 1 : p_r])]
    if p_b > p_t:
        heights[p_t - 1 : p_b] = [unit_sum(*heights[p_t - 1 : p_b])]
    left = PANEL_COL - p_l
    top = PANEL_ROW - p_t
    right = TABLE_COLS - len(widths) - left
    bottom = TABLE_ROWS - len(heights) - top
    if min(left, top, right, bottom) < 0:
        raise ComposeError(
            "子图规范化后超出标准 18×15 子表"
            f"（{len(heights)}×{len(widths)}，panel 在 {p_t},{p_l}）："
            "组合层首期只支持 ggplot2 4.0.3 的整页 gtable 结构"
        )
    zero = _zero_unit()
    return _Sheet(
        widths=tuple([zero] * left + widths + [zero] * right),
        heights=tuple([zero] * top + heights + [zero] * bottom),
    )


def _spacer_sheet() -> _Sheet:
    zero = _zero_unit()
    widths = [zero] * TABLE_COLS
    heights = [zero] * TABLE_ROWS
    widths[PANEL_COL - 1] = unit(1.0, "null")
    heights[PANEL_ROW - 1] = unit(1.0, "null")
    return _Sheet(widths=tuple(widths), heights=tuple(heights))


def _layout_metrics(metrics: Any) -> Any:
    from ggcore.plot_gtable import layout_metrics

    return layout_metrics(metrics)


def _sheet(plot: Any, metrics: Any) -> _Sheet:
    """任意可组合对象 → 18×15 子表（Patchwork 递归合并后规范化）。"""
    if isinstance(plot, Spacer):
        return _spacer_sheet()
    if isinstance(plot, Patchwork):
        table = _build_units(plot, metrics=metrics).table()
        return _sheet_from_table(table)
    from ggcore.plot import ggplot

    if isinstance(plot, ggplot):
        return _sheet_from_table(plot_gtable(plot, metrics=metrics))
    raise ComposeError(f"{type(plot).__name__} 不能作为组合子图")


# ---------------------------------------------------------------------------
# 布局网格
# ---------------------------------------------------------------------------


def _wrap_dims(count: int, nrow: int | None, ncol: int | None) -> tuple[int, int]:
    """`wrap_dims()`：`nrow` / `ncol` 缺省时按 `n2mfrow()`（近方形）。"""
    if ncol is None and nrow is None:
        nrow = math.ceil(math.sqrt(count))
        ncol = math.ceil(count / nrow)
    elif ncol is None:
        assert nrow is not None
        ncol = math.ceil(count / nrow)
    elif nrow is None:
        nrow = math.ceil(count / ncol)
    assert nrow is not None and ncol is not None
    if nrow * ncol < count:
        raise ComposeError(
            f"需要 {count} 个格子，但 nrow={nrow} × ncol={ncol} 只提供 {nrow * ncol} 个"
        )
    return nrow, ncol


def _design(count: int, nrow: int, ncol: int, byrow: bool) -> list[tuple[int, int, int, int]]:
    """每个子图占的 `(t, l, b, r)`（1 起；规则网格）。"""
    cells = nrow * ncol
    order = list(range(cells))
    if not byrow:
        # `matrix(..., byrow = FALSE)` 的填充顺序：先沿列往下。
        order = [t * ncol + left for left in range(ncol) for t in range(nrow)]
    areas: list[tuple[int, int, int, int]] = [(-1, -1, -1, -1)] * cells
    for index, cell in enumerate(order):
        t, left = divmod(cell, ncol)
        areas[index] = (t + 1, left + 1, t + 1, left + 1)
    return areas[:count]


def _repeat_weights(values: tuple[float, ...] | None, size: int) -> tuple[float, ...]:
    if values is None:
        return (1.0,) * size
    return tuple(values[index % len(values)] for index in range(size))


# ---------------------------------------------------------------------------
# 合并：单位向量
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Units:
    """合并后大表的单位向量 + 每个子图的位置（还没放 grob）。"""

    widths: Unit
    heights: Unit
    areas: tuple[tuple[int, int, int, int], ...]
    plots: tuple[Any, ...]
    nrow: int
    ncol: int

    def table(self) -> GTable:
        """只带 panel 记录的表（不回填渲染 grob；用于嵌套时的单位合并）。"""
        layout, grobs = _records(self)
        return GTable(
            widths=self.widths,
            heights=self.heights,
            layout=tuple(layout),
            grobs=tuple(grobs),
            name="patchwork",
        )


def _ctx(metrics: Any) -> UnitContext:
    return UnitContext(metrics=metrics)


def _cm(value: Unit, ctx: UnitContext, *, axis: str) -> float:
    return (
        convert_width(value, "cm", ctx=ctx) if axis == "x" else convert_height(value, "cm", ctx=ctx)
    )


def _build_units(patchwork: Patchwork, *, metrics: Any) -> _Units:
    metrics = _layout_metrics(metrics)
    ctx = _ctx(metrics)
    plots = tuple(patchwork.plots)
    nrow = patchwork.layout.nrow
    ncol = patchwork.layout.ncol
    # patchwork `build_patchwork()`：给了多列 weights / 多行 heights 而没给
    # ncol / nrow 时，长度就是网格的列数 / 行数。
    if ncol is None and patchwork.layout.widths is not None and len(patchwork.layout.widths) > 1:
        ncol = len(patchwork.layout.widths)
    if nrow is None and patchwork.layout.heights is not None and len(patchwork.layout.heights) > 1:
        nrow = len(patchwork.layout.heights)
    nrow, ncol = _wrap_dims(len(plots), nrow, ncol)
    areas = _design(len(plots), nrow, ncol, patchwork.layout.byrow is not False)
    sheets = [_sheet(plot, metrics) for plot in plots]

    # 同一 layout 列的子图逐槽位取 max（mm/cm 都能比）。
    columns: list[Unit] = []
    for col in range(1, ncol + 1):
        group = [sheet for sheet, area in zip(sheets, areas, strict=True) if area[1] == col]
        if not group:
            columns.extend([_zero_unit()] * TABLE_COLS)
            continue
        for slot in range(TABLE_COLS):
            best = max(_cm(sheet.widths[slot], ctx, axis="x") for sheet in group)
            columns.append(unit(best, "cm"))
    # 同一 layout 行的子图逐槽位取 max。
    rows: list[Unit] = []
    for row in range(1, nrow + 1):
        group = [sheet for sheet, area in zip(sheets, areas, strict=True) if area[0] == row]
        if not group:
            rows.extend([_zero_unit()] * TABLE_ROWS)
            continue
        for slot in range(TABLE_ROWS):
            best = max(_cm(sheet.heights[slot], ctx, axis="y") for sheet in group)
            rows.append(unit(best, "cm"))

    # panel 行 / 列换成 null 权重（`set_panel_dimensions()`）。
    width_weights = _repeat_weights(patchwork.layout.widths, ncol)
    height_weights = _repeat_weights(patchwork.layout.heights, nrow)
    for col in range(ncol):
        columns[col * TABLE_COLS + (PANEL_COL - 1)] = unit(width_weights[col], "null")
    for row in range(nrow):
        rows[row * TABLE_ROWS + (PANEL_ROW - 1)] = unit(height_weights[row], "null")
    return _Units(
        widths=unit_c(*columns),
        heights=unit_c(*rows),
        areas=tuple(areas),
        plots=plots,
        nrow=nrow,
        ncol=ncol,
    )


def _records(units: _Units) -> tuple[list[Placement], list[Any]]:
    from ggcore.grobs import ZeroGrob, g_tree

    layout: list[Placement] = []
    grobs: list[Any] = []
    for index, (t, left, b, right) in enumerate(units.areas):
        layout.append(
            Placement(
                t=(t - 1) * TABLE_ROWS + 1,
                l=(left - 1) * TABLE_COLS + 1,
                b=(b - 1) * TABLE_ROWS + TABLE_ROWS,
                r=(right - 1) * TABLE_COLS + TABLE_COLS,
                z=float(index + 1),
                clip="off",
                name=f"plot-{index}",
            )
        )
        grobs.append(g_tree(name=f"plot-{index}"))
    for row in range(1, units.nrow + 1):
        for col in range(1, units.ncol + 1):
            in_area = any(
                area[0] <= row <= area[2] and area[1] <= col <= area[3] for area in units.areas
            )
            if not in_area:
                continue
            layout.append(
                Placement(
                    t=(row - 1) * TABLE_ROWS + PANEL_ROW,
                    l=(col - 1) * TABLE_COLS + PANEL_COL,
                    b=(row - 1) * TABLE_ROWS + PANEL_ROW,
                    r=(col - 1) * TABLE_COLS + PANEL_COL,
                    z=0.5,
                    clip="off",
                    name=f"panel-area-{row}-{col}",
                )
            )
            grobs.append(ZeroGrob())
    return layout, grobs


# ---------------------------------------------------------------------------
# 合并：可绘制表
# ---------------------------------------------------------------------------


def _block_box(sizes: Any, area: tuple[int, int, int, int]) -> Box:
    t, left, _b, _r = area
    widths = sizes.widths_cm
    heights = sizes.heights_cm
    col0 = (left - 1) * TABLE_COLS
    row0 = (t - 1) * TABLE_ROWS
    width = sum(widths[col0 : col0 + TABLE_COLS])
    height = sum(heights[row0 : row0 + TABLE_ROWS])
    x = sum(widths[:col0])
    y = sum(heights[:row0])
    return Box(x, y, width, height)


def _panel_box(sizes: Any, area: tuple[int, int, int, int]) -> Box:
    t, left, _b, _r = area
    widths = sizes.widths_cm
    heights = sizes.heights_cm
    index_col = (left - 1) * TABLE_COLS + (PANEL_COL - 1)
    index_row = (t - 1) * TABLE_ROWS + (PANEL_ROW - 1)
    return Box(
        sum(widths[:index_col]),
        sum(heights[:index_row]),
        widths[index_col],
        heights[index_row],
    )


def _build_gtable(
    patchwork: Patchwork, *, metrics: Any, width_in: float, height_in: float
) -> GTable:
    metrics = _layout_metrics(metrics)
    units = _build_units(patchwork, metrics=metrics)
    ctx = _ctx(metrics)
    spans = GTable(
        widths=units.widths,
        heights=units.heights,
        name="patchwork",
    ).layout_spec()
    width_cm = float(width_in) * CM_PER_INCH
    height_cm = float(height_in) * CM_PER_INCH
    sizes = spans.resolve(width_cm, height_cm, ctx=ctx)

    grobs: list[Any] = []
    layout: list[Placement] = []
    for index, (plot, area) in enumerate(zip(units.plots, units.areas, strict=True)):
        block = _block_box(sizes, area)
        panel = _panel_box(sizes, area)
        # `GTableGrob` 会为每条 layout 记录 push 一个单元格视口（左下角是本地
        # 原点），所以块内坐标从这里起算——块的页面位置已经由那个视口给出。
        grobs.append(
            _block_grob(
                plot,
                index=index,
                block=Box(0.0, 0.0, block.width_cm, block.height_cm),
                panel=Box(
                    panel.x_cm - block.x_cm,
                    panel.y_cm - block.y_cm,
                    panel.width_cm,
                    panel.height_cm,
                ),
                metrics=metrics,
            )
        )
        layout.append(
            Placement(
                t=(area[0] - 1) * TABLE_ROWS + 1,
                l=(area[1] - 1) * TABLE_COLS + 1,
                b=(area[2] - 1) * TABLE_ROWS + TABLE_ROWS,
                r=(area[3] - 1) * TABLE_COLS + TABLE_COLS,
                z=float(index + 1),
                clip="off",
                name=f"plot-{index}",
            )
        )
    panel_layout, panel_grobs = _records(units)
    layout.extend(row for row in panel_layout if row.name.startswith("panel-area-"))
    grobs.extend(
        item
        for item, row in zip(panel_grobs, panel_layout, strict=True)
        if row.name.startswith("panel-area-")
    )
    return GTable(
        widths=units.widths,
        heights=units.heights,
        layout=tuple(layout),
        grobs=tuple(grobs),
        name="patchwork",
    )


def _block_grob(
    plot: Any,
    *,
    index: int,
    block: Box,
    panel: Box,
    metrics: Any,
) -> Any:
    """一个子图块的渲染树：坐标为块内 cm，块视口负责在父容器里定位。"""
    from ggcore.grobs import g_tree, viewport
    from ggcore.units import unit

    inner, page_width, page_height = _inner_grobs(plot, block=block, panel=panel, metrics=metrics)
    return g_tree(
        *inner,
        name=f"plot-{index}-content",
        vp=viewport(
            f"plot-{index}-content",
            x=unit(block.x_cm, "cm"),
            y=unit(block.y_cm, "cm"),
            width=unit(page_width, "cm"),
            height=unit(page_height, "cm"),
            just=("left", "bottom"),
            clip="off",
            gp={"fontsize": 12.0, "fontfamily": ""},
        ),
    )


def _inner_grobs(
    plot: Any, *, block: Box, panel: Box, metrics: Any
) -> tuple[list[Any], float, float]:
    """块内的渲染树 + 这张子图实际使用的页面尺寸（cm）。

    页面尺寸**不是**块尺寸：组合表的块宽 = 同列统一槽位和 + panel 列宽，而子图
    自身的固定槽位可能更窄。按「自身固定槽位 + 目标 panel 宽」渲染，panel 才会
    与表里的 panel 列逐值相等（同列 / 同行的 panel 矩形因此严格对齐），多出来的
    统一空间留在块的外侧。
    """
    if isinstance(plot, Spacer):
        return [], block.width_cm, block.height_cm
    if isinstance(plot, Patchwork):
        return _nested_grobs(plot, block=block, panel=panel, metrics=metrics)
    build = build_plot(plot)
    if build.metrics is not metrics:
        build = replace(build, metrics=metrics)
    natural = scene_layout(
        build,
        width_in=block.width_cm / CM_PER_INCH,
        height_in=block.height_cm / CM_PER_INCH,
        metrics=metrics,
    )
    left = natural.panel_area.x_cm
    bottom = natural.panel_area.y_cm
    right = block.width_cm - natural.panel_area.right
    top = block.height_cm - natural.panel_area.top
    page_width = left + panel.width_cm + right
    page_height = bottom + panel.height_cm + top
    layout = scene_layout(
        build,
        width_in=page_width / CM_PER_INCH,
        height_in=page_height / CM_PER_INCH,
        metrics=metrics,
        panel_box=Box(left, bottom, panel.width_cm, panel.height_cm),
    )
    return page_grobs(build, layout, metrics), page_width, page_height


def _nested_grobs(
    patchwork: Patchwork, *, block: Box, panel: Box, metrics: Any
) -> tuple[list[Any], float, float]:
    """嵌套组合：内层自己的 panel 分配整体缩放到外层给的 panel 框。"""
    units = _build_units(patchwork, metrics=metrics)
    ctx = _ctx(metrics)
    natural = (
        GTable(widths=units.widths, heights=units.heights)
        .layout_spec()
        .resolve(block.width_cm, block.height_cm, ctx=ctx)
    )
    left, right, bottom, top = _panel_margins(units, natural, block)
    page_width = left + panel.width_cm + right
    page_height = bottom + panel.height_cm + top
    sizes = _rescale_panel(units, natural, panel.width_cm, panel.height_cm)
    out: list[Any] = []
    for index, (child, area) in enumerate(zip(units.plots, units.areas, strict=True)):
        child_block = _block_box(sizes, area)
        child_panel = _panel_box(sizes, area)
        out.append(
            _block_grob(
                child,
                index=index,
                block=child_block,
                panel=child_panel,
                metrics=metrics,
            )
        )
    return out, page_width, page_height


def _panel_columns(units: _Units) -> list[int]:
    columns: list[int] = []
    for col in range(1, units.ncol + 1):
        if any(area[1] == col for area in units.areas):
            columns.append((col - 1) * TABLE_COLS + (PANEL_COL - 1))
    return columns


def _panel_rows(units: _Units) -> list[int]:
    rows: list[int] = []
    for row in range(1, units.nrow + 1):
        if any(area[0] == row for area in units.areas):
            rows.append((row - 1) * TABLE_ROWS + (PANEL_ROW - 1))
    return rows


def _panel_margins(units: _Units, sizes: Any, block: Box) -> tuple[float, float, float, float]:
    cols = _panel_columns(units)
    rows = _panel_rows(units)
    left = sum(sizes.widths_cm[: cols[0]])
    right = block.width_cm - sum(sizes.widths_cm[: cols[-1] + 1])
    bottom = sum(sizes.heights_cm[: rows[0]])
    top = block.height_cm - sum(sizes.heights_cm[: rows[-1] + 1])
    return left, right, bottom, top


def _rescale_panel(units: _Units, sizes: Any, target_width: float, target_height: float) -> Any:
    """把内层 panel 行 / 列按比例缩放到目标宽高（其它槽位不动）。"""
    from dataclasses import replace as _replace

    widths = list(sizes.widths_cm)
    heights = list(sizes.heights_cm)
    cols = _panel_columns(units)
    rows = _panel_rows(units)
    old_w = sum(widths[index] for index in cols)
    old_h = sum(heights[index] for index in rows)
    if old_w > 0:
        scale = target_width / old_w
        for index in cols:
            widths[index] *= scale
    if old_h > 0:
        scale = target_height / old_h
        for index in rows:
            heights[index] *= scale
    return _replace(sizes, widths_cm=tuple(widths), heights_cm=tuple(heights))

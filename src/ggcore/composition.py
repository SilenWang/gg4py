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
  居中）。SIL-1001 的验收项是 panel 矩形，这一项留给后续 stage；

## 图例（SIL-1002）

`plot_layout(guides="collect")` 从每个子图的 `plot_gtable()` 里抓 `guide-box-*`
槽位，把子图的图例槽清零（`add_guides(collect = TRUE)`），在组合层按结构 key
去重，再用**顶层主题**（默认 `Theme()`，`Patchwork + theme(...)` 覆盖）的
`legend.position` 组装成一个 `guide-box` 放到整张表的外侧；`guide_area()` 占的
那一格则把图例放进去。`guides="keep"` / `"auto"` 保持每个子图各自画图例。
轴收集 / `panel_spacing` 仍不在本期（SIL-1004）。
"""

from __future__ import annotations

import math
import re
import warnings
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from ggcore.build import build_plot
from ggcore.geom.scene import Box, _box_spacing_cm, _legend_position, page_grobs
from ggcore.geom.scene import plot_layout as scene_layout
from ggcore.gtable import GTable, Placement
from ggcore.guide import (
    GuideBuild,
    build_guides,
    guide_theme,
    legend_box_layout,
    legend_layout,
)
from ggcore.plot_gtable import plot_gtable
from ggcore.theme import Theme, merge_theme, resolve_theme
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
    "GuideArea",
    "PatchLayout",
    "Patchwork",
    "Spacer",
    "guide_area",
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
    #: `guides="auto"|"collect"|"keep"`（patchwork 的 `plot_layout(guides=)`）；
    #: `None` = 没给过（`merged()` 不覆盖）。
    guides: str | None = None

    def merged(self, other: PatchLayout) -> PatchLayout:
        """后给的设置覆盖先给的（`+ plot_layout()` 的语义；`None` 不覆盖）。"""
        return PatchLayout(
            ncol=other.ncol if other.ncol is not None else self.ncol,
            nrow=other.nrow if other.nrow is not None else self.nrow,
            byrow=other.byrow if other.byrow is not None else self.byrow,
            widths=other.widths if other.widths is not None else self.widths,
            heights=other.heights if other.heights is not None else self.heights,
            guides=other.guides if other.guides is not None else self.guides,
        )


@dataclass(frozen=True, slots=True)
class Spacer:
    """`plot_spacer()`：一个空的 18×15 占位块（panel 一行一列 null）。"""


@dataclass(frozen=True, slots=True)
class GuideArea:
    """`guide_area()`：占一格，`guides="collect"` 时把图例盒放进这一格。

    patchwork 里它是 `make_patch()` 加 `panel-guide_area` 标记：格子尺寸就是
    普通 panel 格（同行列权重），图例盒按 `legend.justification` 在格内居中。
    """


@dataclass(frozen=True)
class Patchwork:
    """patchwork 对象：子图（`ggplot` / `Patchwork` / `Spacer`）+ 网格设置。"""

    plots: tuple[Any, ...] = ()
    layout: PatchLayout = field(default_factory=PatchLayout)
    #: `+ theme(...)` 的注释主题（patchwork 的 annotation theme）：`guides="collect"`
    #: 时只用来决定图例盒的 `legend.position` 与排布（`legend.box` / spacing /
    #: justification），不改变各子图自己的主题。
    annotation_theme: Theme | None = None

    def __post_init__(self) -> None:
        for item in self.plots:
            if not is_composable(item):
                raise ComposeError(
                    f"不能把 {type(item).__name__} 放进组合；"
                    "可组合：ggplot / Patchwork / plot_spacer() / guide_area()"
                )
        object.__setattr__(self, "plots", tuple(self.plots))

    # -- 组合 ---------------------------------------------------------------

    def __add__(self, other: Any) -> Any:
        if isinstance(other, PatchLayout):
            return replace(self, layout=self.layout.merged(other))
        if isinstance(other, Theme):
            base = self.annotation_theme or Theme()
            return replace(self, annotation_theme=merge_theme(base, other))
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
    """`value` 能不能进组合（`ggplot` / `Patchwork` / `Spacer` / `GuideArea`）。"""
    from ggcore.plot import ggplot

    return isinstance(value, (ggplot, Patchwork, Spacer, GuideArea))


def plot_spacer() -> Spacer:
    """patchwork 的 `plot_spacer()`：占位空格。"""
    return Spacer()


def guide_area() -> GuideArea:
    """patchwork 的 `guide_area()`：`guides="collect"` 时图例放进这一格。"""
    return GuideArea()


def plot_layout(
    *,
    ncol: int | None = None,
    nrow: int | None = None,
    byrow: bool | None = None,
    widths: Sequence[float] | None = None,
    heights: Sequence[float] | None = None,
    guides: str | None = None,
) -> PatchLayout:
    """网格设置（patchwork 的 `plot_layout()`）。

    `widths` / `heights` 是**相对权重**（对应 `unit(widths, "null")`），不是绝对
    长度；长度不足时循环到列数 / 行数（与 patchwork 的 `rep(..., length.out=)` 一致）。

    `guides`：`"auto"`（子图各自画）、`"collect"`（同结构图例去重后提到顶层）、
    `"keep"`（即使外层 `collect` 也保留各自的图例，patchwork `plot_layout(guides=)`）。
    """
    if ncol is not None and (isinstance(ncol, bool) or not isinstance(ncol, int) or ncol < 1):
        raise ComposeError(f"ncol 必须是 >= 1 的整数，收到 {ncol!r}")
    if nrow is not None and (isinstance(nrow, bool) or not isinstance(nrow, int) or nrow < 1):
        raise ComposeError(f"nrow 必须是 >= 1 的整数，收到 {nrow!r}")
    if byrow is not None and not isinstance(byrow, bool):
        raise ComposeError(f"byrow 必须是 bool，收到 {byrow!r}")
    if guides is not None and guides not in ("auto", "collect", "keep"):
        raise ComposeError(f'guides 只能是 "auto" / "collect" / "keep"，收到 {guides!r}')
    return PatchLayout(
        ncol=ncol,
        nrow=nrow,
        byrow=byrow,
        widths=_weights(widths, "widths"),
        heights=_weights(heights, "heights"),
        guides=guides,
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
        guides=kwargs.pop("guides", None),
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
class _GuideSlot:
    """一个 `guide-box-*` 槽位（18×15 坐标，1 起）。

    `index` 是盒所在的列（left / right）或行（top / bottom），`gap` 是相邻的
    `legend.box.spacing` 槽（`plot_gtable()` 的 `_add_legend_boxes()` 顺序：
    right / bottom 的间距在盒之前，left / top 在盒之后）。
    """

    side: str
    index: int
    gap: int
    #: 这张子图真的有这个方位的图例（槽尺寸非 0）。
    present: bool = True


@dataclass(frozen=True, slots=True)
class _Sheet:
    """一个子图规范化后的表：15 个列宽 + 18 个行高（panel 在 (10, 8)）。"""

    widths: tuple[Unit, ...]
    heights: tuple[Unit, ...]
    #: 有图例的方位 → 槽位（从 `plot_gtable()` 的 layout 里抓的 `guide-box-*`）。
    guides: tuple[_GuideSlot, ...] = ()
    #: 这张格子是 `guide_area()`：`guides="collect"` 时图例放进它的 panel 格。
    guide_area: bool = False


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


def _slot_cm(values: Any, index: int, ctx: UnitContext, *, axis: str) -> float:
    """表里第 `index` 个槽位（1 起）的 cm 尺寸。"""
    return _cm(Unit((values[index - 1],)), ctx, axis=axis)


def _guide_slots(table: GTable, ctx: UnitContext) -> tuple[_GuideSlot, ...]:
    """从 `plot_gtable()` 的表里抓 `guide-box-*` 槽位（只看真的有尺寸的方位）。

    `inside` 与 panel 同格，不是外侧图例盒，不参与 collect 的外侧槽位。
    """
    out: list[_GuideSlot] = []
    for row in table.layout:
        if not row.name.startswith("guide-box-"):
            continue
        side = row.name[len("guide-box-") :]
        if side in ("left", "right"):
            present = _slot_cm(table.widths, row.l, ctx, axis="x") > 1e-12
            index = row.l
            gap = row.l + (1 if side == "left" else -1)
        elif side in ("top", "bottom"):
            present = _slot_cm(table.heights, row.t, ctx, axis="y") > 1e-12
            index = row.t
            gap = row.t + (1 if side == "top" else -1)
        else:
            continue
        out.append(_GuideSlot(side=side, index=index, gap=gap, present=present))
    return tuple(out)


def _mapped_index(index: int, lo: int, hi: int, offset: int) -> int:
    """原始槽位索引 → 坍缩 panel 块 / 补零之后的 18×15 索引（1 起）。"""
    if index < lo:
        mapped = index
    elif index <= hi:
        mapped = lo
    else:
        mapped = index - (hi - lo)
    return mapped + offset


def _sheet_from_table(
    table: GTable,
    *,
    metrics: Any,
    clear_guides: bool = False,
) -> _Sheet:
    """把 `plot_gtable()` 的表压成 18×15（panel 块坍缩 + 补 0 strip 行 / 列）。

    `clear_guides=True` 是 `guides="collect"` 的子图：把 `guide-box-*` 槽位与
    相邻的 `legend.box.spacing` 槽清零（patchwork `add_guides(collect = TRUE)`
    的等价物），图例本身由组合层统一提上去。
    """
    ctx = _ctx(metrics)
    bounds = _panel_bounds(table.layout)
    if bounds is None:
        raise ComposeError("子图 gtable 里找不到 panel（plot_gtable() 的产物才有）")
    p_t, p_l, p_b, p_r = bounds
    widths = [Unit((element,)) for element in table.widths]
    heights = [Unit((element,)) for element in table.heights]
    slots = _guide_slots(table, ctx)
    if clear_guides:
        zero = _zero_unit()
        for slot in slots:
            if not slot.present:
                continue
            if slot.side in ("left", "right"):
                widths[slot.index - 1] = zero
                widths[slot.gap - 1] = zero
            else:
                heights[slot.index - 1] = zero
                heights[slot.gap - 1] = zero
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
    mapped = tuple(
        _GuideSlot(
            side=slot.side,
            index=_mapped_index(
                slot.index,
                p_l if slot.side in ("left", "right") else p_t,
                p_r if slot.side in ("left", "right") else p_b,
                left if slot.side in ("left", "right") else top,
            ),
            gap=_mapped_index(
                slot.gap,
                p_l if slot.side in ("left", "right") else p_t,
                p_r if slot.side in ("left", "right") else p_b,
                left if slot.side in ("left", "right") else top,
            ),
            present=slot.present,
        )
        for slot in slots
        if slot.side in ("left", "right", "top", "bottom")
    )
    return _Sheet(
        widths=tuple([zero] * left + widths + [zero] * right),
        heights=tuple([zero] * top + heights + [zero] * bottom),
        guides=mapped,
    )


def _spacer_sheet(*, guide_area: bool = False) -> _Sheet:
    zero = _zero_unit()
    widths = [zero] * TABLE_COLS
    heights = [zero] * TABLE_ROWS
    widths[PANEL_COL - 1] = unit(1.0, "null")
    heights[PANEL_ROW - 1] = unit(1.0, "null")
    return _Sheet(widths=tuple(widths), heights=tuple(heights), guide_area=guide_area)


def _layout_metrics(metrics: Any) -> Any:
    from ggcore.plot_gtable import layout_metrics

    return layout_metrics(metrics)


def _build_theme(build: Any) -> Any:
    """`PlotBuild` → 解析后的主题（与 `scene._theme_of()` 同一口径）。"""
    return resolve_theme(build.theme if isinstance(build.theme, Theme) else Theme(), build.metrics)


def _prepare_build(plot: Any, metrics: Any) -> Any:
    build = build_plot(plot)
    return build if build.metrics is metrics else replace(build, metrics=metrics)


def _sheet_plan(
    plot: Any,
    metrics: Any,
    *,
    parent_guides: str,
) -> tuple[_Sheet, tuple[_CollectedGuide, ...]]:
    """任意可组合对象 → 18×15 子表 + 这一层要收集的图例。

    嵌套 `Patchwork` 的图例在它自己的层里处理（patchwork 的
    `plot_table.patchwork()` 会把 `guides` 继续往下传、内层自己 attach），
    所以这里只对 `ggplot` 子图收集。
    """
    if isinstance(plot, Spacer):
        return _spacer_sheet(), ()
    if isinstance(plot, GuideArea):
        return _spacer_sheet(guide_area=True), ()
    if isinstance(plot, Patchwork):
        inner = _build_units(plot, metrics=metrics, parent_guides=parent_guides)
        return _sheet_from_table(inner.table(), metrics=metrics), ()
    from ggcore.plot import ggplot

    if not isinstance(plot, ggplot):
        raise ComposeError(f"{type(plot).__name__} 不能作为组合子图")
    collect = parent_guides == "collect"
    build = _prepare_build(plot, metrics)
    table = plot_gtable(build, metrics=metrics)
    sheet = _sheet_from_table(table, metrics=metrics, clear_guides=collect)
    if not collect:
        return sheet, ()
    return sheet, _collect_guides(build, _build_theme(build), metrics)


def _sheet(plot: Any, metrics: Any) -> _Sheet:
    """任意可组合对象 → 18×15 子表（不收集图例；内部 / 测试用）。"""
    sheet, _entries = _sheet_plan(plot, metrics, parent_guides="auto")
    return sheet


# ---------------------------------------------------------------------------
# 图例：收集 / 去重 / 顶层组装
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _CollectedGuide:
    """一张被提到顶层的图例：渲染它的 `build` / 主题 + 结构指纹。

    `legend` 是在**子图自己的** position / 主题下算好的版式 —— 与 patchwork
    先渲染 guide grob、再拼进顶层 guide-box 的顺序一致；顶层只决定盒的排布。
    """

    build: Any
    theme: Any
    guide_build: GuideBuild
    legend: Any
    side: str
    key: tuple[Any, ...]


def _stable(value: Any) -> str:
    """`repr` 的稳定化：去掉对象地址（`AUTO` 哨兵 / 函数默认值的 `0x...`）。"""
    return re.sub(r"0x[0-9a-fA-F]+", "0x", repr(value))


def _guide_fingerprint(guide_build: GuideBuild, theme: Any) -> tuple[Any, ...]:
    """同结构图例的去重 key（patchwork `collapse_guides()` 的结构比较对等物）。

    patchwork 把 guide grob 去掉名字、绝对化单位后 `all.equal()`；这里比
    「美学 + guide 定义 + 标题 + 键/断点 + 影响图例外观的 theme 元素」。主题不同
    的图例因此**不合并**（与 patchwork 的 grob 比较一致）。
    """
    keys = tuple(
        (
            key.label,
            _stable(key.value),
            tuple(sorted((name, _stable(value)) for name, value in key.values.items())),
        )
        for key in guide_build.keys
    )
    theme_names = sorted(name for name in theme.elements if name.startswith(("legend.", "guide.")))
    return (
        guide_build.aesthetics,
        guide_build.kind,
        guide_build.title,
        keys,
        guide_build.limits,
        _stable(guide_build.guide),
        tuple((name, _stable(theme.elements[name])) for name in theme_names),
    )


def _collect_guides(build: Any, theme: Any, metrics: Any) -> tuple[_CollectedGuide, ...]:
    """一张子图的全部图例（`add_guides(collect = TRUE)` 收集的那些）。"""
    position = _legend_position(theme)
    if position in (None, "none"):
        return ()
    out: list[_CollectedGuide] = []
    for guide in build_guides(build):
        side = str(guide.position or position)
        out.append(
            _CollectedGuide(
                build=build,
                theme=theme,
                guide_build=guide,
                legend=legend_layout(guide, theme, side, metrics=metrics),
                side=side,
                key=_guide_fingerprint(guide, theme),
            )
        )
    return tuple(out)


def _top_theme(patchwork: Patchwork, metrics: Any) -> Any:
    """组合的**注释主题**（patchwork 的 `theme_get() + x$annotation$theme`）。

    默认 `Theme()`；`Patchwork + theme(...)` 覆盖。它只决定收集后的 guide-box
    怎么排（`legend.position` / `legend.box` / spacing / justification），不改变
    各子图自己的主题。
    """
    base = Theme()
    if patchwork.annotation_theme is not None:
        base = merge_theme(base, patchwork.annotation_theme)
    return resolve_theme(base, metrics)


def _top_legend_position(theme: Any) -> str:
    value = theme.get("legend.position")
    if value is None:
        return "right"
    if isinstance(value, str):
        return value
    warnings.warn(
        "guides='collect' 时 legend.position 只能是 right / left / top / bottom / none，"
        "数值位置改用 'right'（与 patchwork 的 warning 一致）",
        stacklevel=4,
    )
    return "right"


def _box_just(theme: Any) -> tuple[float, float]:
    """`legend.justification` 的 `(xjust, yjust)`（patchwork `package_box()`）。"""
    value = theme.get("legend.justification")
    if isinstance(value, str):
        mapping = {
            "left": (0.0, 0.5),
            "right": (1.0, 0.5),
            "top": (0.5, 1.0),
            "bottom": (0.5, 0.0),
            "center": (0.5, 0.5),
            "centre": (0.5, 0.5),
            "topleft": (0.0, 1.0),
            "topright": (1.0, 1.0),
            "bottomleft": (0.0, 0.0),
            "bottomright": (1.0, 0.0),
        }
        return mapping.get(value.lower(), (0.5, 0.5))
    try:
        items = [float(item) for item in value]  # type: ignore[union-attr]
    except (TypeError, ValueError):
        return (0.5, 0.5)
    if len(items) == 1:
        return (items[0], items[0])
    if len(items) >= 2:
        return (items[0], items[1])
    return (0.5, 0.5)


@dataclass(frozen=True, slots=True)
class _GuidePlan:
    """collect 之后的顶层 guide 盒：图例 + 盒版式 + 大表里的落点。"""

    entries: tuple[_CollectedGuide, ...]
    position: str
    layout: Any
    #: 大表坐标（1 起，闭区间）。非 `guide_area` 时是单列 / 单行的一段。
    area: tuple[int, int, int, int]
    guide_area: bool
    theme: Any


def _cell_box(sizes: Any, area: tuple[int, int, int, int]) -> Box:
    """大表单元格（1 起、闭区间）的页面矩形（cm，y 向上）。"""
    t, left, b, right = area
    widths = sizes.widths_cm
    heights = sizes.heights_cm
    x = sum(widths[: left - 1])
    width = sum(widths[left - 1 : right])
    y = sum(heights) - sum(heights[:b])
    height = sum(heights[t - 1 : b])
    return Box(x, y, width, height)


def _guide_plan_grobs(plan: _GuidePlan, sizes: Any, metrics: Any) -> list[Any]:
    """把顶层 guide 盒画在页面 / 块坐标里（每条图例一个 `g_tree`）。"""
    from ggcore.grobs import g_tree, viewport

    cell = _cell_box(sizes, plan.area)
    box = plan.layout
    xjust, yjust = _box_just(plan.theme)
    origin_x = cell.x_cm + xjust * (cell.width_cm - float(box.width_cm))
    origin_y = cell.y_cm + yjust * (cell.height_cm - float(box.height_cm))
    out: list[Any] = []
    for index, (entry, placement) in enumerate(zip(plan.entries, box.boxes, strict=True)):
        children = entry.guide_build.guide.gengrob(
            entry.guide_build,
            entry.build,
            guide_theme(entry.theme, entry.guide_build.guide),
            entry.legend,
            metrics=metrics,
            name=f"guide-{index}",
        )
        if not children:
            continue
        out.append(
            g_tree(
                *children,
                name=f"guide-{index}",
                vp=viewport(
                    f"guide-{index}",
                    x=unit(origin_x + placement.x_cm, "cm"),
                    y=unit(origin_y + placement.y_cm, "cm"),
                    width=unit(placement.width_cm, "cm"),
                    height=unit(placement.height_cm, "cm"),
                    just=("left", "bottom"),
                    clip="off",
                    gp={"fontsize": 12.0, "fontfamily": ""},
                ),
            )
        )
    return out


def _effective_guides(patchwork: Patchwork, parent_guides: str) -> str:
    """这一层实际用的 guides 模式（patchwork `build_patchwork()` 的传递规则）。

    外层 `collect` 会把 `collect` 往下传，但显式 `guides="keep"` 的层保留自己
    的图例；本层 `guides="collect"` 总是 collect。
    """
    mode = patchwork.layout.guides or "auto"
    if parent_guides == "collect" and mode != "keep":
        return "collect"
    return mode


# ---------------------------------------------------------------------------
# 布局网格
# ---------------------------------------------------------------------------


def _wrap_dims(count: int, nrow: int | None, ncol: int | None) -> tuple[int, int]:
    """`ggplot2::wrap_dims()`：`nrow` / `ncol` 缺省时按 `n2mfrow()`。

    `n2mfrow()` 不是「近方形」：`n <= 3` 固定 **一行**（`1×2` / `1×3`），其余
    `ncol = ceiling(sqrt(n))`、`nrow = ceiling(n / ncol)`。实测（R 4.5.3）：

    | n | 2 | 3 | 4 | 5..6 | 7..9 | 10..12 | 13..16 |
    | --- | --- | --- | --- | --- | --- | --- | --- |
    | nrow × ncol | 1×2 | 1×3 | 2×2 | 2×3 | 3×3 | 3×4 | 4×4 |

    早期版本用 `nrow = ceil(sqrt(n))` 近似，`p1 + p2` 会变成上下两行（patchwork
    是并排一行）；审计缺口 1 修的就是这条。
    """
    if ncol is None and nrow is None:
        if count <= 3:
            nrow, ncol = 1, count
        else:
            ncol = math.ceil(math.sqrt(count))
            nrow = math.ceil(count / ncol)
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
    #: 这一层是否 `guides="collect"`（子图渲染时不再画自己的图例）。
    collect: bool = False
    #: collect 后的顶层 guide 盒（没有图例 / 不在四侧时是 None）。
    guide: _GuidePlan | None = None

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


def _build_units(patchwork: Patchwork, *, metrics: Any, parent_guides: str = "auto") -> _Units:
    metrics = _layout_metrics(metrics)
    ctx = _ctx(metrics)
    plots = tuple(patchwork.plots)
    mode = _effective_guides(patchwork, parent_guides)
    collect = mode == "collect"
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
    plans = [
        _sheet_plan(plot, metrics, parent_guides="collect" if collect else "auto") for plot in plots
    ]
    sheets = [sheet for sheet, _entries in plans]
    collected = [entry for _sheet, entries in plans for entry in entries]

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

    guide = None
    if collect and collected:
        guide = _plan_guide(
            patchwork,
            _dedupe_guides(collected),
            sheets=sheets,
            areas=areas,
            plots=plots,
            columns=columns,
            rows=rows,
            nrow=nrow,
            ncol=ncol,
            metrics=metrics,
        )
    return _Units(
        widths=unit_c(*columns),
        heights=unit_c(*rows),
        areas=tuple(areas),
        plots=plots,
        nrow=nrow,
        ncol=ncol,
        collect=collect,
        guide=guide,
    )


def _dedupe_guides(
    collected: Sequence[_CollectedGuide],
) -> tuple[_CollectedGuide, ...]:
    """同结构图例只留第一张（patchwork `collapse_guides()` 的顺序语义）。"""
    seen: set[tuple[Any, ...]] = set()
    out: list[_CollectedGuide] = []
    for entry in collected:
        if entry.key in seen:
            continue
        seen.add(entry.key)
        out.append(entry)
    return tuple(out)


def _plan_guide(
    patchwork: Patchwork,
    entries: tuple[_CollectedGuide, ...],
    *,
    sheets: Sequence[_Sheet],
    areas: Sequence[tuple[int, int, int, int]],
    plots: Sequence[Any],
    columns: list[Unit],
    rows: list[Unit],
    nrow: int,
    ncol: int,
    metrics: Any,
) -> _GuidePlan | None:
    """顶层 guide 盒：尺寸写回大表向量，或占用 `guide_area()` 那一格。

    口径照 patchwork `attach_guides()`：

    - 有 `panel-guide_area` 格 → 图例盒放进那一格，不额外占行列；
    - 否则按住 `legend.position` 在整表最外（最右 / 最左子图块的 guide-box
      槽位）加「间距 + 盒」列 / 行，`t..b` / `l..r` 跨 panel 行 / 列。
    """
    theme = _top_theme(patchwork, metrics)
    position = _top_legend_position(theme)
    if position not in ("right", "left", "top", "bottom"):
        # `none` / `inside`：patchwork 的 `attach_guides()` 同样不加到外侧。
        return None
    layout = legend_box_layout([entry.legend for entry in entries], position, theme)
    spacing = _box_spacing_cm(theme)

    guide_areas = [index for index, plot in enumerate(plots) if isinstance(plot, GuideArea)]
    if len(guide_areas) > 1:
        warnings.warn(
            "组合里有多个 guide_area()，只用第一个（与 patchwork 的 warning 一致）",
            stacklevel=5,
        )
    for index in guide_areas[:1]:
        area = areas[index]
        t, left = area[0], area[1]
        row = (t - 1) * TABLE_ROWS + PANEL_ROW
        col = (left - 1) * TABLE_COLS + PANEL_COL
        return _GuidePlan(
            entries=entries,
            position=position,
            layout=layout,
            area=(row, col, row, col),
            guide_area=True,
            theme=theme,
        )

    slots = [slot for sheet in sheets for slot in sheet.guides if slot.side == position]
    # 兜底值与 `plot_gtable()` 的 18×15 槽位一致（所有子表都有这四个槽，
    # 正常路径一定拿得到 `slots[0]`）。
    default = {"right": 12, "left": 4, "top": 6, "bottom": 14}[position]
    index = slots[0].index if slots else default
    gap = slots[0].gap if slots else default + (-1 if position in ("right", "bottom") else 1)

    if position in ("right", "left"):
        col = index + (ncol - 1) * TABLE_COLS if position == "right" else index
        gap_col = gap + (ncol - 1) * TABLE_COLS if position == "right" else gap
        columns[col - 1] = unit(float(layout.width_cm), "cm")
        columns[gap_col - 1] = unit(spacing, "cm")
        top = PANEL_ROW
        bottom = (nrow - 1) * TABLE_ROWS + PANEL_ROW
        return _GuidePlan(
            entries=entries,
            position=position,
            layout=layout,
            area=(top, col, bottom, col),
            guide_area=False,
            theme=theme,
        )
    row = index + (nrow - 1) * TABLE_ROWS if position == "bottom" else index
    gap_row = gap + (nrow - 1) * TABLE_ROWS if position == "bottom" else gap
    rows[row - 1] = unit(float(layout.height_cm), "cm")
    rows[gap_row - 1] = unit(spacing, "cm")
    left = PANEL_COL
    right = (ncol - 1) * TABLE_COLS + PANEL_COL
    return _GuidePlan(
        entries=entries,
        position=position,
        layout=layout,
        area=(row, left, row, right),
        guide_area=False,
        theme=theme,
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
    """一个子图块在页面上的矩形（cm，y 从下往上；design 的 `t` 从**上**往下）。"""
    t, left, _b, _r = area
    widths = sizes.widths_cm
    heights = sizes.heights_cm
    col0 = (left - 1) * TABLE_COLS
    row0 = (t - 1) * TABLE_ROWS
    width = sum(widths[col0 : col0 + TABLE_COLS])
    height = sum(heights[row0 : row0 + TABLE_ROWS])
    x = sum(widths[:col0])
    # 行号从上往下、页面坐标从下往上：块底 = 总高 - 该块上方 + 自身高度。
    y = sum(heights) - sum(heights[: row0 + TABLE_ROWS])
    return Box(x, y, width, height)


def _panel_box(sizes: Any, area: tuple[int, int, int, int]) -> Box:
    """块内 panel 槽位的页面矩形（cm，y 从下往上）。"""
    t, left, _b, _r = area
    widths = sizes.widths_cm
    heights = sizes.heights_cm
    index_col = (left - 1) * TABLE_COLS + (PANEL_COL - 1)
    row0 = (t - 1) * TABLE_ROWS
    index_row = row0 + (PANEL_ROW - 1)
    y = sum(heights) - sum(heights[: index_row + 1])
    return Box(sum(widths[:index_col]), y, widths[index_col], heights[index_row])


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
                collect=units.collect,
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
    if units.guide is not None:
        guide_grobs = _guide_plan_grobs(units.guide, sizes, metrics)
        if guide_grobs:
            from ggcore.grobs import g_tree

            # 覆盖整页的一条记录：`_guide_plan_grobs()` 给的是页面 cm 坐标，
            # 记录的单元格视口原点正好是页面左下 (0, 0)。
            layout.append(
                Placement(
                    t=1,
                    l=1,
                    b=units.nrow * TABLE_ROWS,
                    r=units.ncol * TABLE_COLS,
                    z=1000.0,
                    clip="off",
                    name="collected-guide-box",
                )
            )
            grobs.append(g_tree(*guide_grobs, name="collected-guide-box"))
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
    collect: bool = False,
) -> Any:
    """一个子图块的渲染树：坐标为块内 cm，块视口负责在父容器里定位。"""
    from ggcore.grobs import g_tree, viewport
    from ggcore.units import unit

    # `_inner_grobs()` 用**块内相对坐标**（父容器左下为原点），入参是同一父容器
    # 的页面坐标。
    relative_panel = Box(
        panel.x_cm - block.x_cm,
        panel.y_cm - block.y_cm,
        panel.width_cm,
        panel.height_cm,
    )
    inner, page_width, page_height = _inner_grobs(
        plot, block=block, panel=relative_panel, metrics=metrics, collect=collect
    )
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
    plot: Any, *, block: Box, panel: Box, metrics: Any, collect: bool = False
) -> tuple[list[Any], float, float]:
    """块内的渲染树 + 这张子图实际使用的页面尺寸（cm）。

    页面尺寸**就是块尺寸**（不是「自身固定槽位 + 目标 panel」）：块宽 = 同列
    统一槽位和 + panel 列宽，子图自身的槽位可能更窄。把表级 panel 矩形（块内
    相对坐标）交给 `plot_layout(panel_box=…)`，panel 就落在表级位置，多出来的
    槽位差额被 `plot_layout()` 反推进 `inner` / margin（patchwork
    `set_border_sizes()` 把子表四条边拉伸到 `table_dims()` 的 max 的等价物）。

    早期版本按「自身固定槽位 + 目标 panel」定页面尺寸、页面贴块左边，结果
    panel 落在子图自己的 `left` / `bottom`，同列槽位不同时 x / y 会错开（审计
    缺口 2）。
    """
    if isinstance(plot, (Spacer, GuideArea)):
        return [], block.width_cm, block.height_cm
    if isinstance(plot, Patchwork):
        return _nested_grobs(
            plot,
            block=block,
            panel=panel,
            metrics=metrics,
            parent_guides="collect" if collect else "auto",
        )
    build = build_plot(plot)
    if build.metrics is not metrics:
        build = replace(build, metrics=metrics)
    layout = scene_layout(
        build,
        width_in=block.width_cm / CM_PER_INCH,
        height_in=block.height_cm / CM_PER_INCH,
        metrics=metrics,
        panel_box=Box(panel.x_cm, panel.y_cm, panel.width_cm, panel.height_cm),
        draw_guides=not collect,
    )
    return page_grobs(build, layout, metrics), block.width_cm, block.height_cm


def _nested_grobs(
    patchwork: Patchwork,
    *,
    block: Box,
    panel: Box,
    metrics: Any,
    parent_guides: str = "auto",
) -> tuple[list[Any], float, float]:
    """嵌套组合：内层自己的 panel 分配重映射到块内的表级 panel 矩形。"""
    units = _build_units(patchwork, metrics=metrics, parent_guides=parent_guides)
    ctx = _ctx(metrics)
    natural = (
        GTable(widths=units.widths, heights=units.heights)
        .layout_spec()
        .resolve(block.width_cm, block.height_cm, ctx=ctx)
    )
    page_width = block.width_cm
    page_height = block.height_cm
    sizes = _remap_panel(units, natural, panel, block)
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
                collect=units.collect,
            )
        )
    if units.guide is not None:
        out.extend(_guide_plan_grobs(units.guide, sizes, metrics))
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


def _remap_panel(units: _Units, sizes: Any, panel: Box, block: Box) -> Any:
    """把内层的 panel 行 / 列重映射到块内的目标矩形（缩放 + 两侧槽位补差）。

    差额补到最外侧列 / 行（`plot.margin` 槽位），与 patchwork `set_border_sizes()`
    把子表四条边拉伸到统一尺寸同一个意思；内层自己的 panel 分配比例保留。
    """
    from dataclasses import replace as _replace

    widths = list(sizes.widths_cm)
    heights = list(sizes.heights_cm)
    cols = _panel_columns(units)
    rows = _panel_rows(units)
    # 内层的「panel 块」= 从第一个 panel 列到最后一个 panel 列（含中间的轴 /
    # spacing），与 patchwork `simplify_gt.gtable_patchwork` 把 panel 块压成一列
    # 的语义一致：整块拉伸到外层 slot，块内比例不变。
    col_block = range(cols[0], cols[-1] + 1)
    row_block = range(rows[0], rows[-1] + 1)
    old_w = sum(widths[index] for index in col_block)
    old_h = sum(heights[index] for index in row_block)
    if old_w > 0:
        scale = panel.width_cm / old_w
        for index in col_block:
            widths[index] *= scale
    if old_h > 0:
        scale = panel.height_cm / old_h
        for index in row_block:
            heights[index] *= scale
    # 左侧 / 右侧槽位补到目标原点与块边界；行号从上往下，所以顶部差额落在
    # heights[0]、底部差额落在 heights[-1]。
    left_gap = panel.x_cm - sum(widths[: cols[0]])
    right_gap = (block.width_cm - panel.right) - sum(widths[cols[-1] + 1 :])
    top_gap = (block.height_cm - panel.top) - sum(heights[: rows[0]])
    bottom_gap = panel.y_cm - sum(heights[rows[-1] + 1 :])
    widths[0] += left_gap
    widths[-1] += right_gap
    heights[0] += top_gap
    heights[-1] += bottom_gap
    return _replace(sizes, widths_cm=tuple(widths), heights_cm=tuple(heights))

"""`plot_gtable()`：ggplot2 `ggplotGrob()` 的对等物（SIL-999）。

`ggcore.gtable` 只是「一张表」；要合并多张图（M3-1）还需要**整张 plot 的
unit-based 表**：标题 / 副标题 / 注脚 / tag / 四条轴 / xlab / ylab / guide-box /
panel / strip / background / `plot.margin` 各就各位，面板用 `null` 权重。
这就是上游 `ggplot_gtable()` 的产物，也是 `patchwork` / `cowplot` 合并时真正
拿来 `unit.pmax()` 的东西。本模块把 `plot_layout()` 已经算好的 cm 尺寸装进
同一张命名 gtable。

## 结构

单面板（`facet_null`）是 R `FacetNull$draw_panels()` 的 3×3 表，再由
`Facet$draw_labels()` 加两行两列 → **5×5 基础表**；叠加图例 / 标题 / tag /
margin 后是 **16×13**：

| 行 | 内容 | 列 | 内容 |
| --- | --- | --- | --- |
| 1 | `plot.margin` 上 | 1 | `plot.margin` 左 |
| 2 | `tag`（`plot.tag.location = "margin"`） | 2 | `tag` |
| 3 | `title` | 3 | `guide-box-left` |
| 4 | `subtitle` | 4 | 空（spacer） |
| 5 | `guide-box-top` | 5 | `ylab-l` |
| 6 | 空（spacer） | 6 | `axis-l` |
| 7 | `xlab-t` | 7 | `panel` |
| 8 | `axis-t` | 8 | `axis-r` |
| 9 | `panel` | 9 | `ylab-r` |
| 10 | `axis-b` | 10 | 空（spacer） |
| 11 | `xlab-b` | 11 | `guide-box-right` |
| 12 | 空（spacer） | 12 | 空（spacer） |
| 13 | `guide-box-bottom` | 13 | `plot.margin` 右 |
| 14 | `caption` | | |
| 15 | 空（spacer） | | |
| 16 | `plot.margin` 下 | | |

分面时按 R 的 `attach_axes()` / `attach_strips()` 展开：

- `facet_wrap`：**每个面板列**一组 `axis-l` / `panel` / `axis-r`，**每个面板行**
  一组 `axis-t` / `panel` / `axis-b`；组间才是 `panel.spacing`；strip 每个面板
  行 / 列一条。名字 `axis-l-<row>-<col>` / `axis-t-<col>-<row>`。
- `facet_grid`：每侧**一条**轴 / strip（`seam_table()`），名字只带另一维的编号
  （`axis-l-<row>` / `axis-t-<col>`）。

展开后的面板 / strip 行列权重直接取 `FacetTable.width_weights` /
`height_weights`，`respect` 也照传（`coord_fixed(ratio = 2)`：行 `2null`、
列 `1null`、`respect = TRUE`，与 R 一致）。多行 / 多列的实测：`wrap_ncol1`
22×13、`wrap_2x2` 22×17、`grid_1x2` 17×15、`grid_2x2` 19×16。

## 表里放的是什么

gtable 的 grob 在 gg4py 里可以是任意对象。这里放三类**语义槽位**，组合层
（SIL-1001 起）按名字取尺寸 / 内容即可，不需要重算版式：

- :class:`PanelSlot`：一个面板（带它的 `panel` 号与在 `FacetTable` 里的 t/l/b/r）；
- :class:`StripSlot`：一条 strip；
- :class:`PlotCell`：其余槽位（background / 轴 / 标题 / 图例盒 / spacer），
  `element` 是主题元素或 `LegendBoxLayout`。

## 单位与 `metrics`

- panel 行列是 `null`；固定尺寸（轴、strip、间距、margin、图例键）用 cm，
  全部来自 `plot_layout()`；
- **文字行 / 列**保留成文字度量单位：轴标题（xlab / ylab）与 title / subtitle /
  caption 用 `strheight`（R 的 `1grobheight`；`amount` 按构建时 `metrics` 校准到
  目标 cm，表按 `UnitContext(fontsize=12)` 定义）；图例盒宽度用
  `cm + strwidth(最宽标签)`（R 的 guide-box 是嵌套 gtable）。
- 因此 `UnitContext` 没有 `metrics` 时 `resolve()` **一律**抛 `UnitError`
  （不静默 0，也不回退到占位度量算出一个看起来正常的表）；构建与解析必须用
  **同一个** `metrics`。

**不改单图渲染路径**：`scene_from_build()` 仍走 `PlotLayout` 的绝对 cm 矩形，
`plot_gtable()` 是并行的新导出（与上游 `ggplotGrob()` 并列于绘制之外的位置
一致）。已知差异（free scales 的逐面板轴尺寸、`strip.placement = "outside"`、
stretchy legend key、`plot.tag.location` 的数值位置）记在 `docs/notes/gtable.md`。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from ggcore import plotmath
from ggcore.axis import margin_sides_cm, text_width_cm
from ggcore.axis_guide import guide_for
from ggcore.build import PlotBuild, build_plot
from ggcore.geom.scene import (
    DEFAULT_HEIGHT_IN,
    DEFAULT_WIDTH_IN,
    PlotLayout,
    _axis_title_text,
    _draw_axes,
    _guide_title,
    _tag_position,
    layout_metrics,
    plot_layout,
)
from ggcore.gtable import (
    GTable,
    Placement,
    gtable_add_cols,
    gtable_add_grob,
    gtable_add_padding,
    gtable_add_rows,
)
from ggcore.theme import ElementRect, ElementText, ResolvedTheme, Theme, resolve_theme
from ggcore.units import CM_PER_INCH, Unit, UnitContext, unit, unit_c

__all__ = ["PanelSlot", "PlotCell", "StripSlot", "plot_gtable"]

_CM = "cm"
_NULL = "null"


@dataclass(frozen=True, slots=True)
class PlotCell:
    """整页表里的一个非面板槽位（轴 / 标题 / 图例盒 / background / spacer）。

    `kind` 是稳定的语义标签：`"background"` / `"axis"` / `"axis-title"` /
    `"title"` / `"subtitle"` / `"caption"` / `"tag"` / `"guide-box"` /
    `"spacer"`。`element` 放主题元素（`element_text` / `element_rect` …）或
    `LegendBoxLayout`；`side` 给出轴 / 图例盒的方位。
    """

    name: str
    kind: str
    element: Any = None
    side: str | None = None
    text: str | None = None


@dataclass(frozen=True, slots=True)
class PanelSlot:
    """一个面板槽位：`panel` 号 + 它在 `FacetTable` 里的 1 起单元格位置。"""

    name: str
    panel: int
    table_t: int
    table_l: int
    table_b: int
    table_r: int


@dataclass(frozen=True, slots=True)
class StripSlot:
    """一条 strip 槽位。"""

    name: str
    panel: int
    side: str
    text: str


def plot_gtable(
    plot: Any,
    *,
    metrics: Any = None,
    width_in: float = DEFAULT_WIDTH_IN,
    height_in: float = DEFAULT_HEIGHT_IN,
) -> GTable:
    """`ggplotGrob()` 的对等物：整张 plot 的 unit-based 版式表。

    `plot` 是 `ggplot` 或已经构建好的 `PlotBuild`。`metrics` 缺省时与
    `plot_layout()` 用同一个占位度量；图例标签的宽度仍以 `strwidth` 留在表里
    （见模块文档的「单位与 metrics」）。

    `width_in` / `height_in` 只用来解析 `coord_fixed` 这类**面板比例**与图例盒的
    stretchy 尺寸；表本身是 unit 的（面板 `null`、其余 cm），与页面尺寸无关，
    `GTable.resolve(实际的宽, 高)` 才落到具体 cm。
    """
    build = plot if isinstance(plot, PlotBuild) else build_plot(plot)
    resolved = layout_metrics(metrics)
    if build.metrics is not resolved:
        build = replace(build, metrics=resolved)
    layout = plot_layout(build, width_in=width_in, height_in=height_in, metrics=resolved)
    theme = resolve_theme(build.theme if isinstance(build.theme, Theme) else Theme(), build.metrics)
    kind = str(getattr(build.facet, "kind", "null") or "null")
    table = (
        _single_panel_sheet(build, theme, layout)
        if kind == "null"
        else _facet_sheet(build, theme, layout)
    )
    table = _add_legend_boxes(table, theme, layout, resolved)
    table = _add_title_rows(table, theme, layout, resolved)
    table = _add_tag(table, theme, layout)
    table = _add_plot_margin(table, theme)
    return _add_background(table, theme)


# ---------------------------------------------------------------------------
# 基础表：单面板骨架 / 分面展开
# ---------------------------------------------------------------------------


def _cm(value: float) -> Unit:
    return unit(float(value), _CM)


def _text_height(target_cm: float, text: str | None, metrics: Any) -> Unit:
    """把一段文字的行高 / 列宽（cm）表达成 `strheight` 单位。

    R 的轴标题 / 标题行是 `1grobheight`（文字 grob 高），这里保留同一种
    「随字体度量变」的单位：表按 `UnitContext(fontsize=12)` 定义，解析时
    `amount * strheight(text, 12)` 就是目标 cm（`amount` 用构建时的 `metrics`
    校准）。**没有 `metrics` 时 `resolve()` 按现有约定抛 `UnitError`**，不会
    静默用占位值算出一个看起来正常的表。

    目标尺寸为 0（没有该标题 / 元素是 blank）时仍保留一个 0 的 `strheight`
    单位：这一行本身是文字行，度量缺席时就该报错。
    """
    probe = text if text else "M"
    unit_cm = float(metrics.strheight(probe, fontsize=12.0, cex=1.0)) * CM_PER_INCH
    if target_cm <= 0 or unit_cm <= 0:
        return unit(0.0, "strheight", data=probe)
    return unit(float(target_cm) / unit_cm, "strheight", data=probe)


def _panel_frames(table: GTable) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """面板 grob 的行 / 列范围（`(t, b)` / `(l, r)`），按位置排序。

    对齐 R 的 `panel_rows()` / `panel_cols()`：只看 `^panel` 名字。
    """
    panels = [row for row in table.layout if row.name.startswith("panel")]
    rows = sorted({(row.t, row.b) for row in panels})
    cols = sorted({(row.l, row.r) for row in panels})
    return rows, cols


def _weave_rows(
    table: GTable,
    grobs: Sequence[Sequence[Any]],
    shift: int,
    sizes: Sequence[Unit],
    name: str,
    *,
    z: float = 1.0,
) -> GTable:
    """R `weave_tables_row()`：给**每个**面板行插一行，并跨所有面板列放 grob。

    `shift = -1` 插在面板行上方（axis-t / top strip），`shift = 0` 插在下方
    （axis-b / bottom strip）。
    """
    rows, cols = _panel_frames(table)
    positions = [top for top, _ in rows]
    columns = [left for left, _ in cols]
    for index in range(len(positions) - 1, -1, -1):
        row_ind = positions[index] + shift
        table = gtable_add_rows(table, sizes[index], pos=row_ind)
        names = [f"{name}-{col + 1}-{index + 1}" for col in range(len(columns))]
        table = gtable_add_grob(
            table, list(grobs[index]), t=row_ind + 1, l=columns, z=z, clip="off", name=names
        )
    return table


def _weave_cols(
    table: GTable,
    grobs: Sequence[Sequence[Any]],
    shift: int,
    sizes: Sequence[Unit],
    name: str,
    *,
    z: float = 1.0,
) -> GTable:
    """R `weave_tables_col()`：给每个面板列插一列（`shift = 0` 右侧 / `-1` 左侧）。"""
    rows, cols = _panel_frames(table)
    positions = [left for left, _ in cols]
    row_positions = [top for top, _ in rows]
    for index in range(len(positions) - 1, -1, -1):
        col_ind = positions[index] + shift
        table = gtable_add_cols(table, sizes[index], pos=col_ind)
        names = [f"{name}-{row + 1}-{index + 1}" for row in range(len(row_positions))]
        table = gtable_add_grob(
            table, list(grobs[index]), t=row_positions, l=col_ind + 1, z=z, clip="off", name=names
        )
    return table


def _seam_rows(
    table: GTable,
    grobs: Sequence[Any],
    *,
    side: str,
    size: Unit,
    name: str,
    z: float = 1.0,
) -> GTable:
    """R `seam_table()` 的行版本：整行一条（`facet_grid` 的轴 / strip）。"""
    rows, cols = _panel_frames(table)
    position = rows[0][0] - 1 if side == "top" else rows[-1][1]
    table = gtable_add_rows(table, size, pos=position)
    columns = [left for left, _ in cols]
    names = [f"{name}-{index + 1}" for index in range(len(columns))]
    return gtable_add_grob(
        table, list(grobs), t=position + 1, l=columns, z=z, clip="off", name=names
    )


def _seam_cols(
    table: GTable,
    grobs: Sequence[Any],
    *,
    side: str,
    size: Unit,
    name: str,
    z: float = 1.0,
) -> GTable:
    """R `seam_table()` 的列版本：整列一条。"""
    rows, cols = _panel_frames(table)
    position = cols[0][0] - 1 if side == "left" else cols[-1][1]
    table = gtable_add_cols(table, size, pos=position)
    row_positions = [top for top, _ in rows]
    names = [f"{name}-{index + 1}" for index in range(len(row_positions))]
    return gtable_add_grob(
        table, list(grobs), t=row_positions, l=position + 1, z=z, clip="off", name=names
    )


def _single_panel_sheet(build: PlotBuild, theme: ResolvedTheme, layout: PlotLayout) -> GTable:
    """单面板：R `FacetNull$draw_panels()` 的 3×3 表（`draw_labels()` 再加两行两列）。"""
    table_src = layout.facet_table
    aspect = 1.0
    respect = False
    if table_src is not None:
        aspect = float(table_src.height_weights[0]) if table_src.height_weights else 1.0
        respect = bool(table_src.respect)
    table = GTable(
        widths=unit_c(_cm(layout.y_axis_cm), unit(1.0, _NULL), _cm(layout.y_axis_right_cm)),
        heights=unit_c(_cm(layout.x_axis_top_cm), unit(aspect, _NULL), _cm(layout.x_axis_cm)),
        respect=respect,
        name="layout",
    )
    # 列优先，z / 名字照 R 的 gtable_matrix：spacer 四角 + 四条轴。
    items = (
        (1, 1, 5.0, "spacer", None),
        (2, 1, 7.0, "axis-l", "left"),
        (3, 1, 3.0, "spacer", None),
        (1, 2, 6.0, "axis-t", "top"),
        (2, 2, 1.0, "panel", None),
        (3, 2, 9.0, "axis-b", "bottom"),
        (1, 3, 4.0, "spacer", None),
        (2, 3, 8.0, "axis-r", "right"),
        (3, 3, 2.0, "spacer", None),
    )
    grobs: list[Any] = []
    placements: list[Placement] = []
    for top, left, z, kind, side in items:
        if kind == "panel":
            grobs.append(PanelSlot(kind, 1, top, left, top, left))
        elif kind.startswith("axis"):
            grobs.append(PlotCell(kind, "axis", side=side))
        else:
            grobs.append(PlotCell(kind, "spacer"))
        placements.append(Placement(t=top, l=left, b=top, r=left, z=z, clip="off", name=kind))
    table = replace(table, grobs=tuple(grobs), layout=tuple(placements))

    x_title = _guide_title(guide_for(build, "x"), _axis_title_text(build, "x"))
    y_title = _guide_title(guide_for(build, "y"), _axis_title_text(build, "y"))
    return _add_panel_labels(
        table,
        layout,
        build.metrics,
        title_top=x_title,
        title_bottom=x_title,
        title_left=y_title,
    )


def _add_panel_labels(
    table: GTable,
    layout: PlotLayout,
    metrics: Any,
    *,
    title_top: str | None,
    title_bottom: str | None,
    title_left: str | None,
) -> GTable:
    """R `Facet$draw_labels()`：xlab-t / xlab-b 行 + ylab-l / ylab-r 列。"""
    _rows, cols = _panel_frames(table)
    left, right = cols[0][0], cols[-1][1]
    table = gtable_add_rows(table, _text_height(layout.x_title_top_cm, title_top, metrics), pos=0)
    table = gtable_add_grob(
        table,
        PlotCell("xlab-t", "axis-title", text=title_top, side="top"),
        t=1,
        l=left,
        r=right,
        name="xlab-t",
        clip="off",
    )
    table = gtable_add_rows(table, _text_height(layout.x_title_cm, title_bottom, metrics), pos=-1)
    table = gtable_add_grob(
        table,
        PlotCell("xlab-b", "axis-title", text=title_bottom, side="bottom"),
        t=-1,
        b=-1,
        l=left,
        r=right,
        name="xlab-b",
        clip="off",
    )
    rows, _cols = _panel_frames(table)
    top, bottom = rows[0][0], rows[-1][1]
    table = gtable_add_cols(table, _text_height(layout.y_title_cm, title_left, metrics), pos=0)
    table = gtable_add_grob(
        table,
        PlotCell("ylab-l", "axis-title", text=title_left, side="left"),
        t=top,
        b=bottom,
        l=1,
        name="ylab-l",
        clip="off",
    )
    table = gtable_add_cols(table, _text_height(layout.y_title_right_cm, None, metrics), pos=-1)
    return gtable_add_grob(
        table,
        PlotCell("ylab-r", "axis-title", side="right"),
        t=top,
        b=bottom,
        l=-1,
        r=-1,
        name="ylab-r",
        clip="off",
    )


def _facet_sheet(build: PlotBuild, theme: ResolvedTheme, layout: PlotLayout) -> GTable:
    """分面：R `Facet$init_gtable()` + `attach_axes()` + `attach_strips()`。"""
    ftable = layout.facet_table
    if ftable is None:  # pragma: no cover - `plot_layout()` 总会给出
        raise ValueError("plot_gtable() 需要 plot_layout() 解析出的 facet 表")
    flayout = ftable.layout
    nrow, ncol = flayout.nrow, flayout.ncol
    facet = build.facet
    kind = str(getattr(facet, "kind", "wrap") or "wrap")
    spacing_x = _cm(_spacing_cm(theme, "panel.spacing.x"))
    spacing_y = _cm(_spacing_cm(theme, "panel.spacing.y"))

    widths: list[Unit] = []
    for col in range(1, ncol + 1):
        if col > 1:
            widths.append(spacing_x)
        weight = ftable.width_weights[col - 1] if ftable.width_weights else 1.0
        widths.append(unit(float(weight), _NULL))
    heights: list[Unit] = []
    for row in range(1, nrow + 1):
        if row > 1:
            heights.append(spacing_y)
        weight = ftable.height_weights[row - 1] if ftable.height_weights else 1.0
        heights.append(unit(float(weight), _NULL))
    table = GTable(
        widths=unit_c(*widths),
        heights=unit_c(*heights),
        respect=bool(ftable.respect),
        name="layout",
    )

    panels_at: dict[tuple[int, int], int] = {}
    for panel in flayout.panel_ids:
        panels_at[(int(flayout.row_of(panel)), int(flayout.col_of(panel)))] = int(panel)
    grobs: list[Any] = []
    placements: list[Placement] = []
    for col in range(1, ncol + 1):
        for row in range(1, nrow + 1):
            top, left = 2 * row - 1, 2 * col - 1
            name = f"panel-{col}-{row}"
            panel = panels_at.get((row, col))
            grobs.append(
                PanelSlot(name, panel, top, left, top, left)
                if panel is not None
                else PlotCell(name, "spacer")
            )
            placements.append(Placement(t=top, l=left, b=top, r=left, z=1.0, clip="off", name=name))
    table = replace(table, grobs=tuple(grobs), layout=tuple(placements))

    # ---- 轴（R `attach_axes()`）------------------------------------------
    extents = {
        "top": float(layout.x_axis_top_cm),
        "bottom": float(layout.x_axis_cm),
        "left": float(layout.y_axis_cm),
        "right": float(layout.y_axis_right_cm),
    }

    draw_x, draw_y = _draw_axes(build)

    def axis_row_size(side: str, row: int) -> float:
        """`axis-t` / `axis-b` 的带高：只有外边缘那一行满高（`axes = "margins"`）。

        R 的 `attach_axes()` 先把 `bottom[-dim[1], ] <- zeroGrob()`（`top` 对称），
        `measure_axes()` 再把空洞相邻的带清零：ragged 时**内部带是字面量 `0cm`**，
        空洞只挪 grob、不给内部带高度。`axes = "all_x"` 时每行都画，才逐行满高。
        """
        active = draw_x or (row == 1 if side == "top" else row == nrow)
        return extents[side] if active else 0.0

    def axis_col_size(side: str, col: int) -> float:
        """`axis-l` / `axis-r` 的带宽：只有外边缘那一列满高（`axes = "margins"`）。"""
        active = draw_y or (col == 1 if side == "left" else col == ncol)
        return extents[side] if active else 0.0

    def axis_cell(side: str, name: str) -> PlotCell:
        return PlotCell(name, "axis", side=side)

    if kind == "grid":
        # `facet_grid`：每侧一整条（`seam_table()`），名字只带另一维编号。
        table = _seam_rows(
            table,
            [axis_cell("top", f"axis-t-{col}") for col in range(1, ncol + 1)],
            side="top",
            size=_cm(axis_row_size("top", 1)),
            name="axis-t",
            z=3.0,
        )
        table = _seam_cols(
            table,
            [axis_cell("right", f"axis-r-{row}") for row in range(1, nrow + 1)],
            side="right",
            size=_cm(axis_col_size("right", ncol)),
            name="axis-r",
            z=3.0,
        )
        table = _seam_rows(
            table,
            [axis_cell("bottom", f"axis-b-{col}") for col in range(1, ncol + 1)],
            side="bottom",
            size=_cm(axis_row_size("bottom", nrow)),
            name="axis-b",
            z=3.0,
        )
        table = _seam_cols(
            table,
            [axis_cell("left", f"axis-l-{row}") for row in range(1, nrow + 1)],
            side="left",
            size=_cm(axis_col_size("left", 1)),
            name="axis-l",
            z=3.0,
        )
    else:
        # `facet_wrap`：每面板列 / 行一组轴（`weave_tables_*`）。
        table = _weave_rows(
            table,
            [
                [axis_cell("top", f"axis-t-{col}-{row}") for col in range(1, ncol + 1)]
                for row in range(1, nrow + 1)
            ],
            shift=-1,
            sizes=[_cm(axis_row_size("top", row)) for row in range(1, nrow + 1)],
            name="axis-t",
            z=3.0,
        )
        table = _weave_cols(
            table,
            [
                [axis_cell("right", f"axis-r-{row}-{col}") for row in range(1, nrow + 1)]
                for col in range(1, ncol + 1)
            ],
            shift=0,
            sizes=[_cm(axis_col_size("right", col)) for col in range(1, ncol + 1)],
            name="axis-r",
            z=3.0,
        )
        table = _weave_rows(
            table,
            [
                [axis_cell("bottom", f"axis-b-{col}-{row}") for col in range(1, ncol + 1)]
                for row in range(1, nrow + 1)
            ],
            shift=0,
            sizes=[_cm(axis_row_size("bottom", row)) for row in range(1, nrow + 1)],
            name="axis-b",
            z=3.0,
        )
        table = _weave_cols(
            table,
            [
                [axis_cell("left", f"axis-l-{row}-{col}") for row in range(1, nrow + 1)]
                for col in range(1, ncol + 1)
            ],
            shift=-1,
            sizes=[_cm(axis_col_size("left", col)) for col in range(1, ncol + 1)],
            name="axis-l",
            z=3.0,
        )

    # ---- strip（R `attach_strips()`）-------------------------------------
    sides = {strip.side for strip in ftable.strips}

    def strip_text(row: int, col: int) -> str | None:
        panel = panels_at.get((row, col))
        if panel is None:
            return None
        return next((strip.text for strip in ftable.strips if strip.panel == panel), None)

    if kind == "grid":
        if "top" in sides or "bottom" in sides:
            side = "bottom" if "bottom" in sides else "top"
            table = _seam_rows(
                table,
                [
                    PlotCell(f"strip-{side[0]}-{col}", "strip", text=strip_text(1, col), side=side)
                    for col in range(1, ncol + 1)
                ],
                side=side,
                size=_cm(ftable.strip_height_cm),
                name=f"strip-{side[0]}",
                z=2.0,
            )
        if "right" in sides or "left" in sides:
            side = "left" if "left" in sides else "right"
            table = _seam_cols(
                table,
                [
                    PlotCell(f"strip-{side[0]}-{row}", "strip", text=strip_text(row, 1), side=side)
                    for row in range(1, nrow + 1)
                ],
                side=side,
                size=_cm(ftable.strip_width_cm),
                name=f"strip-{side[0]}",
                z=2.0,
            )
    else:
        if "top" in sides or "bottom" in sides:
            side = "bottom" if "bottom" in sides else "top"
            table = _weave_rows(
                table,
                [
                    [
                        PlotCell(
                            f"strip-{side[0]}-{col}-{row}",
                            "strip",
                            text=strip_text(row, col),
                            side=side,
                        )
                        for col in range(1, ncol + 1)
                    ]
                    for row in range(1, nrow + 1)
                ],
                shift=-1 if side == "top" else 0,
                sizes=[_cm(ftable.strip_height_cm) for _ in range(nrow)],
                name=f"strip-{side[0]}",
                z=2.0,
            )
        if "right" in sides or "left" in sides:
            side = "left" if "left" in sides else "right"
            table = _weave_cols(
                table,
                [
                    [
                        PlotCell(
                            f"strip-{side[0]}-{row}-{col}",
                            "strip",
                            text=strip_text(row, col),
                            side=side,
                        )
                        for row in range(1, nrow + 1)
                    ]
                    for col in range(1, ncol + 1)
                ],
                shift=-1 if side == "left" else 0,
                sizes=[_cm(ftable.strip_width_cm) for _ in range(ncol)],
                name=f"strip-{side[0]}",
                z=2.0,
            )

    x_title = _guide_title(guide_for(build, "x"), _axis_title_text(build, "x"))
    y_title = _guide_title(guide_for(build, "y"), _axis_title_text(build, "y"))
    return _add_panel_labels(
        table,
        layout,
        build.metrics,
        title_top=x_title,
        title_bottom=x_title,
        title_left=y_title,
    )


def _spacing_cm(theme: ResolvedTheme, name: str) -> float:
    from ggcore.units import convert_width

    value = theme.get(name)
    if value is None:
        return 0.0
    if isinstance(value, Unit):
        return float(np.asarray(convert_width(value, "cm", ctx=UnitContext())).sum())
    return float(value)


# ---------------------------------------------------------------------------
# 外层：图例 / 标题 / tag / margin / background
# ---------------------------------------------------------------------------


def _legend_boxes(layout: PlotLayout) -> dict[str, Any]:
    """`side → guide-box 布局`（`plot_layout()` 已经算好的盒子）。"""
    return {
        str(side): box
        for side, box in zip(layout.legend_box_sides, layout.legend_box_layouts, strict=True)
        if str(side) != "inside"
    }


def _legend_box_width(
    box: Any, side: str, layout: PlotLayout, theme: ResolvedTheme, metrics: Any
) -> Unit:
    """guide-box 的宽度单位：固定部分用 cm，标签宽度用 `strwidth`。

    R 的 `guide-box` 是嵌套 gtable，`gtable_width()` 里就含标签的 `stringWidth`。
    这里把最宽标签的宽度留给 `strwidth`，其余（键、间距、margin）落成 cm：
    同一 metrics 下两者相加就是 `legend_box_layout()` 的 `width_cm`；没有
    metrics 时 `resolve()` 会按现有约定抛 `UnitError`，而不是静默给 0。
    """
    element = theme.get("legend.text")
    if not isinstance(element, ElementText):
        return _cm(box.width_cm)
    size = float(element.size or 0.0)
    if size <= 0:
        return _cm(box.width_cm)
    indices = [index for index, value in enumerate(layout.legend_box_sides) if str(value) == side]
    widest = 0.0
    widest_text: str | None = None
    for index in indices:
        if index >= len(layout.legend_layouts):
            continue
        for cell in layout.legend_layouts[index].keys:
            label = cell.key.label
            if not label or plotmath.is_math(label):
                continue
            width = text_width_cm(label, size, metrics, element.family or "")
            if width > widest:
                widest, widest_text = width, label
    if widest_text is None or widest <= 0 or widest >= float(box.width_cm):
        return _cm(box.width_cm)
    return _cm(float(box.width_cm) - widest) + unit(size / 12.0, "strwidth", data=widest_text)


def _add_legend_boxes(
    table: GTable, theme: ResolvedTheme, layout: PlotLayout, metrics: Any
) -> GTable:
    """R `table_add_legends()`：四个方位各加「间距 + 盒宽」列/行，再放 inside。"""
    boxes = _legend_boxes(layout)
    spacing = float(layout.legend_box_spacing_cm)

    rows, cols = _panel_frames(table)
    top, bottom = rows[0][0], rows[-1][1]

    right = boxes.get("right")
    table = gtable_add_cols(table, _cm(spacing if right is not None else 0.0), pos=-1)
    table = gtable_add_cols(
        table,
        _legend_box_width(right, "right", layout, theme, metrics)
        if right is not None
        else _cm(0.0),
        pos=-1,
    )
    table = gtable_add_grob(
        table,
        PlotCell("guide-box-right", "guide-box", element=right, side="right"),
        t=top,
        b=bottom,
        l=-1,
        r=-1,
        name="guide-box-right",
        clip="off",
    )
    left = boxes.get("left")
    table = gtable_add_cols(table, _cm(spacing if left is not None else 0.0), pos=0)
    table = gtable_add_cols(
        table,
        _legend_box_width(left, "left", layout, theme, metrics) if left is not None else _cm(0.0),
        pos=0,
    )
    table = gtable_add_grob(
        table,
        PlotCell("guide-box-left", "guide-box", element=left, side="left"),
        t=top,
        b=bottom,
        l=1,
        r=1,
        name="guide-box-left",
        clip="off",
    )

    rows, cols = _panel_frames(table)
    top, bottom = rows[0][0], rows[-1][1]
    left_col, right_col = cols[0][0], cols[-1][1]
    below = boxes.get("bottom")
    table = gtable_add_rows(table, _cm(spacing if below is not None else 0.0), pos=-1)
    table = gtable_add_rows(table, _cm(below.height_cm if below is not None else 0.0), pos=-1)
    table = gtable_add_grob(
        table,
        PlotCell("guide-box-bottom", "guide-box", element=below, side="bottom"),
        t=-1,
        b=-1,
        l=left_col,
        r=right_col,
        name="guide-box-bottom",
        clip="off",
    )

    rows, cols = _panel_frames(table)
    top, bottom = rows[0][0], rows[-1][1]
    left_col, right_col = cols[0][0], cols[-1][1]
    above = boxes.get("top")
    table = gtable_add_rows(table, _cm(spacing if above is not None else 0.0), pos=0)
    table = gtable_add_rows(table, _cm(above.height_cm if above is not None else 0.0), pos=0)
    table = gtable_add_grob(
        table,
        PlotCell("guide-box-top", "guide-box", element=above, side="top"),
        t=1,
        b=1,
        l=left_col,
        r=right_col,
        name="guide-box-top",
        clip="off",
    )

    rows, cols = _panel_frames(table)
    top, bottom = rows[0][0], rows[-1][1]
    left_col, right_col = cols[0][0], cols[-1][1]
    return gtable_add_grob(
        table,
        PlotCell("guide-box-inside", "guide-box", side="inside"),
        t=top,
        b=bottom,
        l=left_col,
        r=right_col,
        name="guide-box-inside",
        clip="off",
    )


def _plot_extent(table: GTable) -> tuple[int, int]:
    """R 的 `plot_extent()`：所有 `guide-box-*` 槽位的列范围。

    `plot.title.position = "plot"` / `plot.caption.position = "plot"` 时 R 的
    title / caption 跨的就是这一段（`guide-box-left` 的 l 到 `guide-box-right`
    的 r），不是整张表 —— 4.0.3 实测：13 列的表里是 3..11。
    """
    boxes = [row for row in table.layout if row.name.startswith("guide-box-")]
    if not boxes:
        return 1, table.ncol
    return min(row.l for row in boxes), max(row.r for row in boxes)


def _add_title_rows(
    table: GTable, theme: ResolvedTheme, layout: PlotLayout, metrics: Any
) -> GTable:
    """R `ggplot_gtable()` 的 title / subtitle / caption 三行。"""
    _rows, cols = _panel_frames(table)
    plot_left, plot_right = _plot_extent(table)
    if theme.get("plot.title.position") == "plot":
        title_left, title_right = plot_left, plot_right
    else:
        title_left, title_right = cols[0][0], cols[-1][1]
    if theme.get("plot.caption.position") == "plot":
        caption_left, caption_right = plot_left, plot_right
    else:
        caption_left, caption_right = cols[0][0], cols[-1][1]

    table = gtable_add_rows(
        table, _text_height(layout.subtitle_cm, layout.subtitle_text, metrics), pos=0
    )
    table = gtable_add_grob(
        table,
        PlotCell("subtitle", "subtitle", text=layout.subtitle_text),
        t=1,
        b=1,
        l=title_left,
        r=title_right,
        name="subtitle",
        clip="off",
    )
    table = gtable_add_rows(table, _text_height(layout.title_cm, layout.title_text, metrics), pos=0)
    table = gtable_add_grob(
        table,
        PlotCell("title", "title", text=layout.title_text),
        t=1,
        b=1,
        l=title_left,
        r=title_right,
        name="title",
        clip="off",
    )
    table = gtable_add_rows(
        table, _text_height(layout.caption_cm, layout.caption_text, metrics), pos=-1
    )
    return gtable_add_grob(
        table,
        PlotCell("caption", "caption", text=layout.caption_text),
        t=-1,
        b=-1,
        l=caption_left,
        r=caption_right,
        name="caption",
        clip="off",
    )


def _replace_first(units: Unit, value: Unit) -> Unit:
    return unit_c(value, units[1:])


def _replace_last(units: Unit, value: Unit) -> Unit:
    return unit_c(units[:-1], value)


def _add_tag(table: GTable, theme: ResolvedTheme, layout: PlotLayout) -> GTable:
    """R `table_add_tag()`：四边 0pt padding + margin 单元格扩到 tag 尺寸。"""
    table = gtable_add_padding(table, unit(0.0, "points"))
    if layout.tag is None or layout.tag_text is None:
        return table
    width = float(layout.tag_width_cm)
    height = float(layout.tag_height_cm)
    if width <= 0 or height <= 0:
        return table
    position = _tag_position(theme)
    numeric = not isinstance(position[0], bool)
    location = str(theme.get("plot.tag.location") or ("plot" if numeric else "margin"))
    if location == "margin" and not numeric:
        top, left, right, bottom = position  # type: ignore[misc]
        if top:
            table = replace(table, heights=_replace_first(table.heights, _cm(height)))
        if bottom:
            table = replace(table, heights=_replace_last(table.heights, _cm(height)))
        if left:
            table = replace(table, widths=_replace_first(table.widths, _cm(width)))
        if right:
            table = replace(table, widths=_replace_last(table.widths, _cm(width)))
        t, left_col, b, right_col = 1, 1, table.nrow, table.ncol
        if top:
            b = t
        if bottom:
            t = b
        if left:
            right_col = left_col
        if right:
            left_col = right_col
    elif location == "panel":
        rows, cols = _panel_frames(table)
        t, left_col = rows[0][0], cols[0][0]
        b, right_col = rows[-1][1], cols[-1][1]
    else:
        t, left_col, b, right_col = 1, 1, table.nrow, table.ncol
    return gtable_add_grob(
        table,
        PlotCell("tag", "tag", element=layout.tag_element, text=layout.tag_text),
        t=t,
        l=left_col,
        b=b,
        r=right_col,
        name="tag",
        clip="off",
    )


def _add_plot_margin(table: GTable, theme: ResolvedTheme) -> GTable:
    top, right, bottom, left = margin_sides_cm(theme.get("plot.margin"))
    return gtable_add_padding(table, unit_c(_cm(top), _cm(right), _cm(bottom), _cm(left)))


def _add_background(table: GTable, theme: ResolvedTheme) -> GTable:
    element = theme.get("plot.background")
    if not isinstance(element, ElementRect):
        return table
    table = gtable_add_grob(
        table,
        PlotCell("background", "background", element=element),
        t=1,
        l=1,
        b=-1,
        r=-1,
        z=-math.inf,
        name="background",
        clip="on",
    )
    # R 把 background 的记录挪到 layout / grobs 的第一条。
    layout = (table.layout[-1], *table.layout[:-1])
    grobs = (table.grobs[-1], *table.grobs[:-1])
    return replace(table, layout=layout, grobs=grobs)

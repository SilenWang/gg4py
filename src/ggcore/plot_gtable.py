"""`plot_gtable()`：ggplot2 `ggplotGrob()` 的对等物（SIL-999）。

`ggcore.gtable` 只是「一张表」；要合并多张图（M3-1）还需要**整张 plot 的
unit-based 表**：标题 / 副标题 / 注脚 / tag / 四条轴 / xlab / ylab / guide-box /
panel / strip / background / `plot.margin` 各就各位，面板用 `null` 权重。
这就是上游 `ggplot_gtable()` 的产物，也是 `patchwork` / `cowplot` 合并时真正
拿来 `unit.pmax()` 的东西。本模块把 `plot_layout()` 已经算好的 cm 尺寸装进
同一张命名 gtable。

## 结构：照抄 R 4.0.3 的 16×13 骨架

单面板图的 `ggplotGrob()` 固定是 **16 行 × 13 列**（`tests/fixtures/
guide_r_reference.json` 的 `structure` 与 `tools/refs/plot_gtable_ref.R` 的实测
一致）。行列语义与 layout 名称逐条对齐：

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

分面时 R 把中间的「3 行 × 3 列」（axis-t / panel / axis-b 与 axis-l / panel /
axis-r）**展开**成逐面板的网格：行 = `axis-t` + `FacetTable` 的行 + `axis-b`，
列 = 每个面板列前插 `axis-l`、后插 `axis-r`。本模块照同一规则展开，于是

- `facet_wrap(~g)` 两列：17 × 17（R 实测）；
- `facet_grid(g ~ .)` 两行：18 × 14（R 实测）。

展开后的面板 / strip 行列权重直接取 `FacetTable.width_weights` /
`height_weights`，`respect` 也照传（`coord_fixed(ratio = 2)`：行 `2null`、
列 `1null`、`respect = TRUE`，与 R 一致）。

## 表里放的是什么

gtable 的 grob 在 gg4py 里可以是任意对象。这里放三类**语义槽位**，组合层
（SIL-1001 起）按名字取尺寸 / 内容即可，不需要重算版式：

- :class:`PanelSlot`：一个面板（带它的 `panel` 号与在 `FacetTable` 里的 t/l/b/r）；
- :class:`StripSlot`：一条 strip；
- :class:`PlotCell`：其余槽位（background / 轴 / 标题 / 图例盒 / spacer），
  `element` 是主题元素或 `LegendBoxLayout`。

**不改单图渲染路径**：`scene_from_build()` 仍走 `PlotLayout` 的绝对 cm 矩形，
`plot_gtable()` 是并行的新导出（与上游 `ggplotGrob()` 并列于绘制之外的位置
一致）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ggcore.axis import margin_sides_cm
from ggcore.build import PlotBuild, build_plot
from ggcore.geom.scene import (
    DEFAULT_HEIGHT_IN,
    DEFAULT_WIDTH_IN,
    PlotLayout,
    layout_metrics,
    plot_layout,
)
from ggcore.gtable import GTable, gtable, gtable_add_grob
from ggcore.theme import ResolvedTheme, Theme, resolve_theme
from ggcore.units import Unit, UnitContext, convert_height, convert_width, unit, unit_c

__all__ = ["PanelSlot", "PlotCell", "StripSlot", "plot_gtable"]

#: 单面板骨架的行数 / 列数（R 4.0.3 的 `ggplotGrob()`）。
SKELETON_ROWS = 16
SKELETON_COLS = 13

#: 骨架里「面板区」占的行（axis-t / panel / axis-b）与列（axis-l / panel / axis-r）。
_PANEL_ROWS = (8, 9, 10)
_PANEL_COLS = (6, 7, 8)

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
    `plot_layout()` 用同一个占位度量（表里不含 `strwidth` / `strheight` 单位，
    所以没有字体度量也能给出稳定的行列）。

    `width_in` / `height_in` 只用来解析 `coord_fixed` 这类**面板比例**与图例盒的
    stretchy 尺寸；表本身是 unit 的（面板 `null`、其余 cm），与页面尺寸无关，
    `GTable.resolve(实际的宽, 高)` 才落到具体 cm。
    """
    build = plot if isinstance(plot, PlotBuild) else build_plot(plot)
    resolved = layout_metrics(metrics)
    layout = plot_layout(build, width_in=width_in, height_in=height_in, metrics=resolved)
    theme = resolve_theme(build.theme if isinstance(build.theme, Theme) else Theme(), build.metrics)
    return _assemble(build, layout, theme, resolved)


# ---------------------------------------------------------------------------
# 装配
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Rows:
    """展开后的行：单位向量 + 行列映射（块内 1 起）。"""

    units: tuple[Unit, ...]
    facet_row: dict[int, int]
    axis_top: int
    axis_bottom: int
    panel_rows: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _Cols:
    """展开后的列：单位向量 + 面板列 / 轴列的块内位置。"""

    units: tuple[Unit, ...]
    facet_col: dict[int, int]
    axis_left: dict[int, int]
    axis_right: dict[int, int]
    panel_cols: tuple[int, ...]
    first_panel: int
    last_panel: int


def _cm(value: float) -> Unit:
    return unit(float(value), _CM)


def _null(weight: float = 1.0) -> Unit:
    return unit(float(weight), _NULL)


def _fixed_cm(target: Unit, ctx: UnitContext, *, width: bool) -> float:
    convert = convert_width if width else convert_height
    value = convert(target, _CM, ctx=ctx)
    return float(np.asarray(value, dtype=float).reshape(-1)[0])


def _unit_at(target: Unit, index: int) -> Unit:
    """`Unit` 的第 `index` 个元素（0 起）单独成单位。"""
    return Unit((target[index],))


def _expand_rows(table: Any, ctx: UnitContext) -> _Rows:
    """`axis-t` + `FacetTable` 的行 + `axis-b`。"""
    facet_rows = len(table.gtable.heights)
    panel_rows = sorted({t for (_panel, t, _l, _b, _r) in table.panels})
    weights = table.height_weights or tuple(1.0 for _ in range(len(panel_rows)))
    row_weight = dict(zip(panel_rows, weights, strict=True))
    units: list[Unit] = [_null()]
    facet_row: dict[int, int] = {}
    for index in range(1, facet_rows + 1):
        if index in panel_rows:
            units.append(_null(row_weight[index]))
        else:
            units.append(
                _cm(_fixed_cm(_unit_at(table.gtable.heights, index - 1), ctx, width=False))
            )
        facet_row[index] = len(units)
    units.append(_null())
    return _Rows(
        units=tuple(units),
        facet_row=facet_row,
        axis_top=1,
        axis_bottom=len(units),
        panel_rows=tuple(facet_row[index] for index in panel_rows),
    )


def _expand_cols_with_axis(
    table: Any, ctx: UnitContext, axis_left_cm: float, axis_right_cm: float
) -> _Cols:
    """同 :func:`_expand_cols`，但把轴列占位换成实际 cm 宽度。"""
    facet_cols = len(table.gtable.widths)
    panel_cols = sorted({left for (_panel, _t, left, _b, _r) in table.panels})
    strip_cols = {row.l for row in table.gtable.layout if str(row.name).startswith("strip-")}
    weights = table.width_weights or tuple(1.0 for _ in range(len(panel_cols)))
    col_weight = dict(zip(panel_cols, weights, strict=True))
    units: list[Unit] = []
    facet_col: dict[int, int] = {}
    axis_left: dict[int, int] = {}
    axis_right: dict[int, int] = {}
    open_panel: int | None = None

    def close_group() -> None:
        nonlocal open_panel
        if open_panel is None:
            return
        units.append(_cm(0.0))
        axis_right[open_panel] = len(units)
        open_panel = None

    for index in range(1, facet_cols + 1):
        if index in panel_cols:
            close_group()
            units.append(_cm(0.0))
            axis_left[index] = len(units)
            open_panel = index
            units.append(_null(col_weight[index]))
            facet_col[index] = len(units)
            continue
        if index in strip_cols:
            facet_col[index] = len(units) + 1
            units.append(_cm(_fixed_cm(_unit_at(table.gtable.widths, index - 1), ctx, width=True)))
            close_group()
            continue
        close_group()
        facet_col[index] = len(units) + 1
        units.append(_cm(_fixed_cm(_unit_at(table.gtable.widths, index - 1), ctx, width=True)))
    close_group()
    # R 只在最外层给轴带宽度：`scales = "fixed"` 时内轴不画标签，内轴列是 0cm
    # （`facet_wrap` 两列的实测：axis-l-1-1 = 0.3505cm、axis-l-1-2 = 0cm）。
    if axis_left:
        units[min(axis_left.values()) - 1] = _cm(axis_left_cm)
    if axis_right:
        units[max(axis_right.values()) - 1] = _cm(axis_right_cm)
    return _Cols(
        units=tuple(units),
        facet_col=facet_col,
        axis_left=axis_left,
        axis_right=axis_right,
        panel_cols=tuple(facet_col[index] for index in panel_cols),
        first_panel=min(facet_col[index] for index in panel_cols),
        last_panel=max(facet_col[index] for index in panel_cols),
    )


def _assemble(build: PlotBuild, layout: PlotLayout, theme: ResolvedTheme, metrics: Any) -> GTable:
    ctx = UnitContext(metrics=metrics)
    table = layout.facet_table
    if table is None:  # pragma: no cover - `plot_layout()` 总会给出
        table = build.facet_table(metrics=metrics)

    rows = _expand_rows(table, ctx)
    cols = _expand_cols_with_axis(
        table,
        ctx,
        float(layout.y_axis_cm),
        float(layout.y_axis_right_cm),
    )

    guide_extent = _guide_extents(layout)
    spacing = float(layout.legend_box_spacing_cm)
    tag_in_margin = _tag_in_margin(theme)
    has_tag = tag_in_margin and layout.tag_text is not None
    # `PlotLayout.margin_cm` 已经把 `plot.tag` 的尺寸折进 margin（上游
    # `table_add_tag()` 的做法）。整页表把 tag 放在单独的第 2 行 / 第 2 列，
    # 所以这里用**原始** `plot.margin`，否则 tag 尺寸会被算两遍。
    top, right, bottom, left = margin_sides_cm(theme.get("plot.margin"))
    title_cm, subtitle_cm, caption_cm = _text_rows(layout)

    heights: list[Unit] = [
        _cm(top),  # 1 plot.margin
        _cm(layout.tag_height_cm if has_tag else 0.0),  # 2 tag
        _cm(title_cm),  # 3 title
        _cm(subtitle_cm),  # 4 subtitle
        _cm(guide_extent.get("top", 0.0)),  # 5 guide-box-top
        _cm(spacing if "top" in guide_extent else 0.0),  # 6 legend.box.spacing
        _cm(layout.x_title_top_cm),  # 7 xlab-t
    ]
    # 轴行是固定 cm（`x_axis_top_cm` / `x_axis_cm`），不是 null：`_expand_rows`
    # 只负责行列结构，尺寸在这里落到骨架上。
    row_units = list(rows.units)
    row_units[rows.axis_top - 1] = _cm(layout.x_axis_top_cm)
    row_units[rows.axis_bottom - 1] = _cm(layout.x_axis_cm)
    heights.extend(row_units)  # axis-t + facet 行 + axis-b
    heights.extend(
        [
            _cm(layout.x_title_cm),  # xlab-b
            _cm(spacing if "bottom" in guide_extent else 0.0),  # legend.box.spacing
            _cm(guide_extent.get("bottom", 0.0)),  # guide-box-bottom
            _cm(caption_cm),  # caption
            _cm(0.0),  # spacer
            _cm(bottom),  # plot.margin
        ]
    )
    widths: list[Unit] = [
        _cm(left),  # 1 plot.margin
        _cm(layout.tag_width_cm if has_tag else 0.0),  # 2 tag
        _cm(guide_extent.get("left", 0.0)),  # 3 guide-box-left
        _cm(spacing if "left" in guide_extent else 0.0),  # 4 legend.box.spacing
        _cm(layout.y_title_cm),  # 5 ylab-l
    ]
    widths.extend(cols.units)  # axis-l + facet 列 + axis-r
    widths.extend(
        [
            _cm(layout.y_title_right_cm),  # ylab-r
            _cm(spacing if "right" in guide_extent else 0.0),  # legend.box.spacing
            _cm(guide_extent.get("right", 0.0)),  # guide-box-right
            _cm(0.0),  # spacer
            _cm(right),  # plot.margin
        ]
    )

    nrows, ncols = len(heights), len(widths)
    expected_rows = SKELETON_ROWS - len(_PANEL_ROWS) + len(row_units)
    expected_cols = SKELETON_COLS - len(_PANEL_COLS) + len(cols.units)
    if (nrows, ncols) != (expected_rows, expected_cols):  # pragma: no cover - 结构性自检
        raise AssertionError(
            f"整页 gtable 的行列数 {nrows}×{ncols} 与骨架 + 展开不一致："
            f"{expected_rows}×{expected_cols}"
        )

    result = gtable(
        unit_c(*widths),
        unit_c(*heights),
        respect=bool(table.respect),
        name="layout",
    )

    # 块内 1 起 → 整表：骨架前面板区前有 7 行 / 5 列（见模块文档的骨架表）。
    row_shift = _PANEL_ROWS[0] - 1
    col_shift = _PANEL_COLS[0] - 1

    def row(block: int) -> int:
        return block + row_shift

    def col(block: int) -> int:
        return block + col_shift

    multi = len(table.panels) > 1
    #: `(name, grob, t, l, b, r, z)`
    placements: list[tuple[str, Any, int, int, int, int, float]] = []

    placements.append(
        (
            "background",
            PlotCell("background", "background", theme.get("plot.background")),
            1,
            1,
            nrows,
            ncols,
            0.0,
        )
    )

    first_panel_row = row(rows.panel_rows[0])
    last_panel_row = row(rows.panel_rows[-1])
    axis_top_row = row(rows.axis_top)
    axis_bottom_row = row(rows.axis_bottom)
    first_col = col(cols.first_panel)
    last_col = col(cols.last_panel)

    # spacer：R 在 axis / panel 交角处的 4 条零尺寸占位（只在单面板骨架里）。
    for name, top, left, z in (
        ()
        if multi
        else (
            ("spacer", axis_top_row, col(_first_axis_left(cols)), 5.0),
            ("spacer", axis_bottom_row, col(_first_axis_left(cols)), 3.0),
            ("spacer", axis_top_row, col(_first_axis_right(cols)), 4.0),
            ("spacer", axis_bottom_row, col(_first_axis_right(cols)), 2.0),
        )
    ):
        placements.append((name, PlotCell(name, "spacer"), top, left, top, left, z))

    # 面板 / strip。
    table_layout = {placement.name: placement for placement in table.gtable.layout}
    for panel, t, left, b, r in table.panels:
        panel_row, panel_col = table.layout.row_of(panel), table.layout.col_of(panel)
        # R 4.0.3 的 panel 名是 `panel-{col}-{row}`（`facet_wrap` 两列的实测：
        # `panel-1-1` / `panel-2-1`），与 axis 的 `-(row)-(col)` 相反。
        name = f"panel-{panel_col}-{panel_row}" if multi else "panel"
        placements.append(
            (
                name,
                PanelSlot(name, panel, t, left, b, r),
                row(rows.facet_row[t]),
                col(cols.facet_col[left]),
                row(rows.facet_row[b]),
                col(cols.facet_col[r]),
                1.0,
            )
        )
    for strip in table.strips:
        placement = table_layout.get(strip.name)
        if placement is None or getattr(strip, "outside", False):
            continue
        placements.append(
            (
                strip.name,
                StripSlot(strip.name, strip.panel, strip.side, strip.text),
                row(rows.facet_row[placement.t]),
                col(cols.facet_col[placement.l]),
                row(rows.facet_row[placement.b]),
                col(cols.facet_col[placement.r]),
                2.0,
            )
        )

    # 轴：每个面板一组 axis-l / axis-r；axis-t / axis-b 逐个面板列。
    # 命名照 R：`facet_wrap` 用 `axis-l-{row}-{col}`，`facet_grid` 的轴跨整行，
    # 只带行号（`axis-l-{row}`）。
    grid_facet = str(getattr(build.facet, "kind", "null")) == "grid"
    seen_column: set[int] = set()
    for panel, t, left, _b, _r in table.panels:
        panel_row, panel_col = table.layout.row_of(panel), table.layout.col_of(panel)
        if not multi:
            suffix = ""
        elif grid_facet:
            suffix = f"-{panel_row}"
        else:
            suffix = f"-{panel_row}-{panel_col}"
        target_row = row(rows.facet_row[t])
        if left in cols.axis_left:
            placements.append(
                (
                    f"axis-l{suffix}",
                    PlotCell("axis-l", "axis", side="left"),
                    target_row,
                    col(cols.axis_left[left]),
                    target_row,
                    col(cols.axis_left[left]),
                    7.0,
                )
            )
        if left in cols.axis_right:
            placements.append(
                (
                    f"axis-r{suffix}",
                    PlotCell("axis-r", "axis", side="right"),
                    target_row,
                    col(cols.axis_right[left]),
                    target_row,
                    col(cols.axis_right[left]),
                    8.0,
                )
            )
        if left in seen_column:
            continue
        seen_column.add(left)
        block = col(cols.facet_col[left])
        if multi and not grid_facet:
            suffix = f"-{panel_col}-{panel_row}"
        top_name = f"axis-t{suffix}" if multi else "axis-t"
        bottom_name = f"axis-b{suffix}" if multi else "axis-b"
        placements.append(
            (
                top_name,
                PlotCell("axis-t", "axis", side="top"),
                axis_top_row,
                block,
                axis_top_row,
                block,
                6.0,
            )
        )
        placements.append(
            (
                bottom_name,
                PlotCell("axis-b", "axis", side="bottom"),
                axis_bottom_row,
                block,
                axis_bottom_row,
                block,
                9.0,
            )
        )

    xlab_top_row = 7
    xlab_bottom_row = axis_bottom_row + 1
    placements.extend(
        [
            (
                "xlab-t",
                PlotCell("xlab-t", "axis-title", side="top", text=_label(build, "x")),
                xlab_top_row,
                first_col,
                xlab_top_row,
                last_col,
                10.0,
            ),
            (
                "xlab-b",
                PlotCell("xlab-b", "axis-title", side="bottom", text=_label(build, "x")),
                xlab_bottom_row,
                first_col,
                xlab_bottom_row,
                last_col,
                11.0,
            ),
            (
                "ylab-l",
                PlotCell("ylab-l", "axis-title", side="left", text=_label(build, "y")),
                first_panel_row,
                5,
                last_panel_row,
                5,
                12.0,
            ),
            (
                "ylab-r",
                PlotCell("ylab-r", "axis-title", side="right", text=_label(build, "y")),
                first_panel_row,
                ncols - 4,
                last_panel_row,
                ncols - 4,
                13.0,
            ),
        ]
    )

    guide_col = {
        "left": (3, 3),
        "right": (ncols - 2, ncols - 2),
        "top": (first_col, last_col),
        "bottom": (first_col, last_col),
    }
    guide_row = {
        "left": (first_panel_row, last_panel_row),
        "right": (first_panel_row, last_panel_row),
        "top": (5, 5),
        "bottom": (axis_bottom_row + 3, axis_bottom_row + 3),
    }
    guide_z = {"right": 14.0, "left": 15.0, "bottom": 16.0, "top": 17.0}
    boxes = dict(_guide_boxes(layout))
    # R 的 `ggplotGrob()` 总是登记四个方位的 `guide-box-*`（没有图例时是
    # `zeroGrob()`），所以这里也总是放记录：组合层按名字取槽位时不必先判断
    # 图例是否存在。
    for side in ("right", "left", "bottom", "top"):
        box = boxes.get(side)
        row_span, col_span = guide_row[side], guide_col[side]
        placements.append(
            (
                f"guide-box-{side}",
                PlotCell(f"guide-box-{side}", "guide-box", element=box, side=side),
                row_span[0],
                col_span[0],
                row_span[1],
                col_span[1],
                guide_z[side],
            )
        )
    placements.append(
        (
            "guide-box-inside",
            PlotCell("guide-box-inside", "guide-box", side="inside"),
            first_panel_row,
            first_col,
            last_panel_row,
            last_col,
            18.0,
        )
    )

    caption_row = axis_bottom_row + 4
    placements.extend(
        [
            (
                "subtitle",
                PlotCell("subtitle", "subtitle", text=layout.subtitle_text),
                4,
                first_col,
                4,
                last_col,
                19.0,
            ),
            (
                "title",
                PlotCell("title", "title", text=layout.title_text),
                3,
                first_col,
                3,
                last_col,
                20.0,
            ),
            (
                "caption",
                PlotCell("caption", "caption", text=layout.caption_text),
                caption_row,
                first_col,
                caption_row,
                last_col,
                21.0,
            ),
        ]
    )
    if has_tag:
        placements.append(
            (
                "tag",
                PlotCell("tag", "tag", element=layout.tag_element, text=layout.tag_text),
                2,
                2,
                2,
                2,
                22.0,
            )
        )

    for name, grob, t, left, b, r, z in placements:
        result = gtable_add_grob(result, grob, t=t, l=left, b=b, r=r, z=z, name=name, clip="on")
    return result


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _panel_columns(table: Any) -> tuple[int, ...]:
    return tuple(sorted({left for (_panel, _t, left, _b, _r) in table.panels}))


def _first_axis_left(cols: _Cols) -> int:
    return min(cols.axis_left.values(), default=cols.first_panel)


def _first_axis_right(cols: _Cols) -> int:
    return min(cols.axis_right.values(), default=cols.last_panel)


def _label(build: PlotBuild, name: str) -> str | None:
    value = build.labels.get(name)
    return None if value is None else str(value)


def _text_rows(layout: PlotLayout) -> tuple[float, float, float]:
    title = layout.title_cm if layout.title is not None else 0.0
    subtitle = layout.subtitle_cm if layout.subtitle is not None else 0.0
    caption = layout.caption_cm if layout.caption is not None else 0.0
    return float(title), float(subtitle), float(caption)


def _tag_in_margin(theme: ResolvedTheme) -> bool:
    return str(theme.get("plot.tag.location") or "margin") == "margin"


def _guide_boxes(layout: PlotLayout) -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    for side, box in zip(layout.legend_box_sides, layout.legend_box_layouts, strict=True):
        if side == "inside":
            continue
        out.append((str(side), box))
    return out


def _guide_extents(layout: PlotLayout) -> dict[str, float]:
    """每个方位的 `guide-box` 槽位尺寸（不含 `legend.box.spacing`）。

    R 把 `legend.box.spacing` 放在 guide-box **外侧**的独立 spacer 行 / 列里
    （单图有右图例时列 10 = `11points`，列 11 才是 guide-box），所以这里给的
    是盒本身，spacing 由骨架里的 spacer 行 / 列承担。
    """
    extents: dict[str, float] = {}
    for side, box in _guide_boxes(layout):
        if side in ("left", "right"):
            extents[side] = float(box.width_cm)
        else:
            extents[side] = float(box.height_cm)
    return extents

"""`plot_gtable()`（SIL-999）：整页 gtable 的结构与口径。

对拍 R 的那部分在 `tests/test_plot_gtable_r_parity.py`；这里钉住不依赖 R 的
契约：

- 单面板的 16×13 骨架与 `ggplotGrob()` 的 layout 名称 / 行列语义一致；
- 面板行 / 列是 `null`，解析出来的面板区与 `plot_layout()` 的 `panel_area` 相同
  （组合层合并时两套尺寸必须能互相换算）；
- `facet_wrap` / `facet_grid` 的展开行列数（17×17 / 18×14）；
- `coord_fixed` 的 `respect` 与 `null` 权重；
- 图例盒只贡献 guide-box 列，`legend.box.spacing` 落在独立 spacer 行 / 列；
- 表是 unit 的：同一张图在不同页面尺寸下行列单位不变。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from ggcore.build import build_plot
from ggcore.geom.scene import plot_layout
from ggcore.gtable import GTable
from ggcore.plot import (
    aes,
    coord_fixed,
    facet_grid,
    facet_wrap,
    geom_point,
    ggplot,
    labs,
    plot_gtable,
)
from ggcore.units import Unit, UnitContext, convert_height, convert_width
from ggio.frame import from_dict
from ggskia.text import ShaperMetrics

CM_PER_INCH = 2.54
METRICS = ShaperMetrics()
CTX = UnitContext(metrics=METRICS)

DATA = from_dict(
    {
        "x": [1.0, 2.0, 3.0, 4.0, 5.0],
        "y": [2.0, 4.0, 3.0, 5.0, 6.0],
        "g": ["a", "b", "a", "b", "a"],
    }
)

SKELETON_NAMES = {
    "background",
    "panel",
    "spacer",
    "axis-t",
    "axis-b",
    "axis-l",
    "axis-r",
    "xlab-t",
    "xlab-b",
    "ylab-l",
    "ylab-r",
    "guide-box-top",
    "guide-box-right",
    "guide-box-bottom",
    "guide-box-left",
    "guide-box-inside",
    "title",
    "subtitle",
    "caption",
}


def _base() -> ggplot:
    return ggplot(DATA, aes(x="x", y="y")) + geom_point()


def _names(table: GTable) -> set[str]:
    return {placement.name for placement in table.layout}


def _placement(table: GTable, name: str):
    return next(placement for placement in table.layout if placement.name == name)


def _cm(value: Unit | Any, *, width: bool = True) -> float:
    """单位元素 / 单位 → cm（`table.widths[i]` 给的是单个 `UnitElement`）。"""
    target = value if isinstance(value, Unit) else Unit((value,))
    convert = convert_width if width else convert_height
    return float(np.asarray(convert(target, "cm", ctx=CTX), dtype=float).reshape(-1)[0])


def _column_cm(table: GTable, index: int) -> float:
    """第 `index` 列（1 起）的单位 → cm；null 列按 7×7in 解析。"""
    return table.resolve(7 * CM_PER_INCH, 7 * CM_PER_INCH).widths_cm[index - 1]


def test_single_panel_skeleton_is_sixteen_by_thirteen() -> None:
    table = plot_gtable(_base() + labs(x="XX", y="YY"), metrics=METRICS)
    assert isinstance(table, GTable)
    assert (table.nrow, table.ncol) == (16, 13)
    assert _names(table) == SKELETON_NAMES

    background = _placement(table, "background")
    assert (background.t, background.l, background.b, background.r) == (1, 1, 16, 13)

    assert (_placement(table, "panel").t, _placement(table, "panel").l) == (9, 7)
    assert (_placement(table, "axis-b").t, _placement(table, "axis-b").l) == (10, 7)
    assert (_placement(table, "axis-l").t, _placement(table, "axis-l").l) == (9, 6)
    assert (_placement(table, "xlab-b").t, _placement(table, "xlab-b").l) == (11, 7)
    assert (_placement(table, "ylab-l").t, _placement(table, "ylab-l").l) == (9, 5)
    assert _placement(table, "title").t == 3
    assert _placement(table, "caption").t == 14


def test_panel_cell_matches_plot_layout_panel_area() -> None:
    """面板行列是 null；解析出来的尺寸与单图渲染用的 `panel_area` 一致。"""
    plot = _base() + labs(title="T", x="XX", y="YY")
    table = plot_gtable(plot, metrics=METRICS)
    layout = plot_layout(build_plot(plot), metrics=METRICS)
    width_cm = 7.0 * CM_PER_INCH
    height_cm = 7.0 * CM_PER_INCH
    box = table.region_box(9, 7, 9, 7, width_cm=width_cm, height_cm=height_cm)
    assert box.width_cm == pytest.approx(layout.panel_area.width_cm, abs=0.02)
    assert box.height_cm == pytest.approx(layout.panel_area.height_cm, abs=0.02)
    sizes = table.resolve(width_cm, height_cm)
    assert sizes.total_width_cm == pytest.approx(width_cm, abs=1e-9)
    assert sizes.total_height_cm == pytest.approx(height_cm, abs=1e-9)


def test_facet_wrap_expands_like_ggplot_grob() -> None:
    table = plot_gtable(_base() + facet_wrap("g"), metrics=METRICS)
    assert (table.nrow, table.ncol) == (17, 17)
    names = _names(table)
    assert {"panel-1-1", "panel-2-1", "strip-t-1-1", "strip-t-2-1"} <= names
    assert {
        "axis-l-1-1",
        "axis-l-1-2",
        "axis-t-1-1",
        "axis-t-2-1",
        "axis-b-1-1",
        "axis-b-2-1",
    } <= names
    assert "spacer" not in names  # 分面表里 R 不放骨架的 4 条 spacer
    assert str(table.widths).count("1null") == 2  # 两个面板列
    # 内轴不画标签：只有最左一条 axis-l 有宽度，右边那条是 0cm。
    # 列 6 = 第一条 axis-l（面板 1 左侧），列 10 = 面板 2 的 axis-l；都是 0 起索引。
    assert _cm(table.widths[5]) > 0
    assert _cm(table.widths[9]) == pytest.approx(0.0, abs=1e-12)


def test_facet_grid_expands_like_ggplot_grob() -> None:
    table = plot_gtable(_base() + facet_grid("g"), metrics=METRICS)
    assert (table.nrow, table.ncol) == (18, 14)
    names = _names(table)
    assert {"panel-1-1", "panel-1-2", "strip-r-1", "strip-r-2"} <= names
    # grid 的轴跨整行 / 整列，名字只带行号（R 的 `axis-l-1`）。
    assert {"axis-l-1", "axis-l-2", "axis-t-1"} <= names


def test_coord_fixed_sets_respect_and_null_weights() -> None:
    table = plot_gtable(_base() + coord_fixed(ratio=2), metrics=METRICS)
    assert table.respect is True
    assert str(table.heights[8]) == "2null"
    assert str(table.widths[6]) == "1null"


def test_legend_box_gets_its_own_column_and_spacing_stays_outside() -> None:
    plot = ggplot(DATA, aes(x="x", y="y", colour="g")) + geom_point()
    table = plot_gtable(plot, metrics=METRICS)
    layout = plot_layout(build_plot(plot), metrics=METRICS)
    box = layout.legend_box_layouts[layout.legend_box_sides.index("right")]
    spacing = layout.legend_box_spacing_cm
    assert spacing > 0
    # 列 10 是 `legend.box.spacing`，列 11 才是 guide-box-right。
    assert _cm(table.widths[9]) == pytest.approx(spacing, abs=1e-9)
    assert _cm(table.widths[10]) == pytest.approx(box.width_cm, abs=1e-9)


def test_tag_occupies_the_second_row_and_column() -> None:
    table = plot_gtable(_base() + labs(tag="A"), metrics=METRICS)
    tag = _placement(table, "tag")
    assert (tag.t, tag.l, tag.b, tag.r) == (2, 2, 2, 2)
    # tag 的尺寸只算一次：margin 保持原始 5.5pt，tag 单独占第 2 行。
    # 主题的 pt → cm 用 2.54/72.27（与 R 的 `convertWidth` 同源），不是 2.54/72；
    # 5.5pt = 0.1933cm。放宽到 0.01cm 只钉「没有被 tag 尺寸污染」。
    assert _cm(table.heights[0], width=False) == pytest.approx(5.5 * CM_PER_INCH / 72, abs=0.01)
    assert _cm(table.heights[1], width=False) > 0


def test_table_is_device_independent() -> None:
    """整页表是 unit 的：换页面尺寸只改 null 的分配，不改行列单位。"""
    plot = _base() + labs(title="T")
    small = plot_gtable(plot, metrics=METRICS, width_in=4.0, height_in=3.0)
    large = plot_gtable(plot, metrics=METRICS, width_in=10.0, height_in=8.0)
    assert str(small.widths) == str(large.widths)
    assert str(small.heights) == str(large.heights)
    assert small.resolve(4.0 * CM_PER_INCH, 3.0 * CM_PER_INCH).total_width_cm == pytest.approx(
        4.0 * CM_PER_INCH
    )


def test_without_metrics_the_table_is_still_stable() -> None:
    """`metrics=None` 与 `plot_layout()` 用同一个占位度量，不静默给 0。"""
    table = plot_gtable(_base() + labs(title="T", x="XX"), metrics=None)
    assert (table.nrow, table.ncol) == (16, 13)
    sizes = table.resolve(7.0 * CM_PER_INCH, 7.0 * CM_PER_INCH)
    assert sizes.total_width_cm == pytest.approx(7.0 * CM_PER_INCH)
    assert all(value >= 0 for value in sizes.widths_cm)
    assert all(value >= 0 for value in sizes.heights_cm)
    # 有正文的标题 / 轴标题不会变成 0 宽高（占位度量也要给出正的文字尺寸）。
    assert sizes.heights_cm[2] > 0
    assert sizes.heights_cm[10] > 0


def test_accepts_a_build() -> None:
    table = plot_gtable(build_plot(_base()), metrics=METRICS)
    assert (table.nrow, table.ncol) == (16, 13)


def test_resolve_without_metrics_reports_strwidth_error_not_zero() -> None:
    """现有约定：带 `strwidth` 的表没有 metrics 时必须报错，不能静默 0。"""
    from ggcore.gtable import gtable
    from ggcore.units import unit

    table = gtable(unit(1, "strwidth", data="hello"), unit(1, "null"))
    with pytest.raises(Exception, match=r"metrics|strwidth"):
        table.resolve(7.0 * CM_PER_INCH, 7.0 * CM_PER_INCH)

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
from ggcore.theme import theme
from ggcore.units import Unit, UnitContext, UnitError, convert_height, convert_width
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

#: 多行 / 多列分面的 shape：与 `tools/refs/plot_gtable_ref.R` 的 `data` 同一份。
FACET_DATA = from_dict(
    {
        "x": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
        "y": [2.0, 4.0, 3.0, 5.0, 6.0, 3.0, 4.0, 7.0],
        "g": ["a", "b", "a", "b", "a", "b", "a", "b"],
        "h": ["u", "u", "u", "u", "v", "v", "v", "v"],
        "four": ["p", "q", "r", "s", "p", "q", "r", "s"],
        "five": ["p", "q", "r", "s", "t", "p", "q", "r"],
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
    box = table.region_box(9, 7, 9, 7, width_cm=width_cm, height_cm=height_cm, ctx=CTX)
    assert box.width_cm == pytest.approx(layout.panel_area.width_cm, abs=0.02)
    assert box.height_cm == pytest.approx(layout.panel_area.height_cm, abs=0.02)
    sizes = table.resolve(width_cm, height_cm, ctx=CTX)
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


def test_multi_row_and_multi_column_facets_expand_like_r() -> None:
    """审计缺口 1：多行 / 多列分面的展开规则（R 4.0.3 实测的行列数）。"""
    base = ggplot(FACET_DATA, aes(x="x", y="y")) + geom_point()
    cases = {
        "wrap_ncol1": (base + facet_wrap("g", ncol=1), (22, 13)),
        "wrap_2x2": (base + facet_wrap("four"), (22, 17)),
        "grid_1x2": (base + facet_grid(None, "g"), (17, 15)),
        "grid_2x2": (base + facet_grid("h", "g"), (19, 16)),
    }
    for name, (plot, shape) in cases.items():
        table = plot_gtable(plot, metrics=METRICS)
        assert (table.nrow, table.ncol) == shape, name
        names = [item.name for item in table.layout]
        assert len(names) == len(set(names)), f"{name}: 重复的 layout 名 {names}"


def test_multi_row_wrap_has_one_axis_group_per_panel_row() -> None:
    """`facet_wrap(ncol = 1)`：每个面板行一组 axis-t / strip / panel / axis-b。"""
    base = ggplot(FACET_DATA, aes(x="x", y="y")) + geom_point()
    table = plot_gtable(base + facet_wrap("g", ncol=1), metrics=METRICS)
    assert {"axis-t-1-1", "axis-t-1-2", "axis-b-1-1", "axis-b-1-2"} <= _names(table)
    assert (_placement(table, "axis-t-1-2").t, _placement(table, "panel-1-2").t) == (13, 15)


def _box_of(table: GTable, name: str) -> Any:
    """按 layout 名取解析后的单元格框（7×7in）。"""
    boxes = table.boxes(7.0 * CM_PER_INCH, 7.0 * CM_PER_INCH, ctx=CTX)
    for row, box in zip(table.layout, boxes, strict=True):
        if row.name == name:
            return box
    raise KeyError(name)


def test_ragged_wrap_inner_axis_bands_are_zero() -> None:
    """ragged（末行不满）：只有最后一个面板行的 `axis-b` 满高，内部带是 0cm。

    R 的 `attach_axes()` 先 `bottom[-dim[1], ] <- zeroGrob()`，`measure_axes()`
    再把空洞相邻的带清零：空洞只挪 grob，不给内部带高度（审计缺口 1 残留）。
    `dir = "v"` 触发同一处。
    """
    base = ggplot(FACET_DATA, aes(x="x", y="y")) + geom_point()
    for plot in (
        base + facet_wrap("five", ncol=2),  # 3 行 2 列，末行 1 格
        base + facet_wrap("five", ncol=2, dir="v"),
    ):
        table = plot_gtable(plot, metrics=METRICS)
        assert _box_of(table, "axis-b-1-1").height_cm == 0.0
        assert _box_of(table, "axis-b-2-1").height_cm == 0.0
        assert _box_of(table, "axis-b-1-3").height_cm > 0.4
        # `axis-t` 默认只在第一行（`margins`），这里 top 轴本身是 0。
        assert _box_of(table, "axis-t-1-1").height_cm == 0.0


def test_axes_all_with_margins_labels_only_keeps_the_tick() -> None:
    """`axes = "all"` + `axis.labels = "margins"`：内面板只留刻度（R 0.0967cm）。

    R 的 `censor_labels()` 删掉内面板的轴标签，`measure_axes()` 因此在内侧带拿到的
    是 tick 长度；`axis.labels = "all"` 时内侧带才与边缘同高。
    """
    base = ggplot(FACET_DATA, aes(x="x", y="y")) + geom_point()
    table = plot_gtable(
        base + facet_wrap("four", axes="all", axis_labels="margins"), metrics=METRICS
    )
    assert _box_of(table, "axis-b-1-1").height_cm == pytest.approx(0.0967, abs=1e-3)
    assert _box_of(table, "axis-b-1-2").height_cm > 0.4  # 最后一行满高
    assert _box_of(table, "axis-l-1-2").width_cm == pytest.approx(0.0967, abs=1e-3)
    assert _box_of(table, "axis-l-1-1").width_cm > 0.3  # 第一列满高

    labelled = plot_gtable(
        base + facet_wrap("four", axes="all", axis_labels="all"), metrics=METRICS
    )
    assert _box_of(labelled, "axis-b-1-1").height_cm > 0.4
    assert _box_of(labelled, "axis-l-1-2").width_cm > 0.3

    # 单方向 `all_x` / `all_y`：只有该方向的内侧带留刻度，另一方向仍是 margins（0）。
    all_x = plot_gtable(
        base + facet_wrap("four", axes="all_x", axis_labels="margins"), metrics=METRICS
    )
    assert _box_of(all_x, "axis-b-1-1").height_cm == pytest.approx(0.0967, abs=1e-3)
    assert _box_of(all_x, "axis-l-1-2").width_cm == 0.0
    all_y = plot_gtable(
        base + facet_wrap("four", axes="all_y", axis_labels="margins"), metrics=METRICS
    )
    assert _box_of(all_y, "axis-b-1-1").height_cm == 0.0
    assert _box_of(all_y, "axis-l-1-2").width_cm == pytest.approx(0.0967, abs=1e-3)


def test_grid_non_default_axes_is_a_registered_gap() -> None:
    """`facet_grid` 的 `axes=` 非默认值不复刻（已知差异，见 `docs/notes/gtable.md`）。

    R 4.0.3 会给每条内面板行 / 列各插一条轴带（2×2 的 `facet_grid(h ~ g)`：
    `all` = 21×18、`all_x` = 21×16、`all_y` = 19×18）；`plot_gtable()` 在本期
    仍按 `axes = "margins"` 的 19×16 建表。这条测试钉住当前形状，避免以后把
    「结构没展开」误当成「已对拍」。
    """
    base = ggplot(FACET_DATA, aes(x="x", y="y")) + geom_point()
    for kwargs in (
        {"axes": "margins"},
        {"axes": "all"},
        {"axes": "all_x"},
        {"axes": "all_y"},
        {"axes": "all", "axis_labels": "margins"},
    ):
        table = plot_gtable(base + facet_grid("h", "g", **kwargs), metrics=METRICS)
        assert (table.nrow, table.ncol) == (19, 16), kwargs
        names = {item.name for item in table.layout}
        assert {"axis-l-1", "axis-l-2", "axis-t-1", "axis-t-2"} <= names


def test_grid_axes_are_shared_and_named_by_the_other_dimension() -> None:
    """`facet_grid` 每侧一条轴；名字带列号（axis-t）/ 行号（axis-l），不重复。"""
    base = ggplot(FACET_DATA, aes(x="x", y="y")) + geom_point()
    table = plot_gtable(base + facet_grid(None, "g"), metrics=METRICS)
    assert {"axis-l-1", "axis-t-1", "axis-t-2", "axis-b-1", "axis-b-2"} <= _names(table)
    assert "axis-l-2" not in _names(table)  # 只有一行面板


def test_title_plot_position_spans_the_guide_boxes() -> None:
    """`plot.title.position = "plot"`：R 的 title 跨 guide-box-left .. -right（3..11）。"""
    plot = (
        ggplot(FACET_DATA, aes(x="x", y="y", colour="g"))
        + geom_point()
        + labs(title="T", subtitle="S")
        + theme(**{"plot.title.position": "plot"})
    )
    table = plot_gtable(plot, metrics=METRICS)
    title = _placement(table, "title")
    left = _placement(table, "guide-box-left")
    right = _placement(table, "guide-box-right")
    assert (title.l, title.r) == (left.l, right.r)
    assert (title.l, title.r) == (3, 11)


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
    assert small.resolve(
        4.0 * CM_PER_INCH, 3.0 * CM_PER_INCH, ctx=CTX
    ).total_width_cm == pytest.approx(4.0 * CM_PER_INCH)


def test_without_metrics_resolve_raises_unit_error() -> None:
    """文字尺寸以 `strheight` / `strwidth` 留在表里：没有 metrics 时按约定报错。

    验收条文要求「无 metrics 时按现有方式报错，不静默 0」——轴标题 / 标题行
    是 `strheight`、图例标签宽度是 `strwidth`，两者都走 `units` 的
    `UnitError` 路径；不回退到占位度量算出一个看起来正常的表。
    """
    table = plot_gtable(_base() + labs(title="T", x="XX"), metrics=None)
    assert (table.nrow, table.ncol) == (16, 13)
    with pytest.raises(UnitError, match="strheight"):
        table.resolve(7.0 * CM_PER_INCH, 7.0 * CM_PER_INCH)
    with pytest.raises(UnitError, match="metric"):
        table.resolve(7.0 * CM_PER_INCH, 7.0 * CM_PER_INCH, ctx=UnitContext())
    sizes = table.resolve(7.0 * CM_PER_INCH, 7.0 * CM_PER_INCH, ctx=CTX)
    assert sizes.total_width_cm == pytest.approx(7.0 * CM_PER_INCH)
    # 有正文的标题 / 轴标题不会变成 0 宽高（同一 metrics 下解析回目标尺寸）。
    assert sizes.heights_cm[2] > 0
    assert sizes.heights_cm[10] > 0


def test_legend_width_keeps_strwidth_and_needs_metrics() -> None:
    """含图例的表多留一个 `strwidth`（标签宽度）：无 metrics 时同样报错。"""
    plot = ggplot(FACET_DATA, aes(x="x", y="y", colour="g")) + geom_point()
    table = plot_gtable(plot, metrics=METRICS)
    with pytest.raises(UnitError, match=r"strheight|strwidth"):
        table.resolve(7.0 * CM_PER_INCH, 7.0 * CM_PER_INCH)
    widths = [str(item) for item in table.widths]
    assert any("strwidth" in text for text in widths)
    sizes = table.resolve(7.0 * CM_PER_INCH, 7.0 * CM_PER_INCH, ctx=CTX)
    assert max(sizes.widths_cm) >= 1.0


def test_text_rows_resolve_back_to_the_layout_cm() -> None:
    """`strheight` 校准：同一 metrics 下解析回 `plot_layout()` 的 cm。"""
    plot = _base() + labs(title="T", subtitle="S", caption="C", x="XX", y="YY")
    table = plot_gtable(plot, metrics=METRICS)
    layout = plot_layout(build_plot(plot), metrics=METRICS)
    sizes = table.resolve(7.0 * CM_PER_INCH, 7.0 * CM_PER_INCH, ctx=CTX)
    # 外层行：1 margin / 2 tag / 3 title / 4 subtitle / 5 guide-top / 6 spacing /
    # 7 xlab-t / 8 axis-t / 9 panel / 10 axis-b / 11 xlab-b / 12 spacing /
    # 13 guide-bottom / 14 caption / 15 spacer / 16 margin。
    assert sizes.heights_cm[2] == pytest.approx(layout.title_cm, abs=1e-9)
    assert sizes.heights_cm[3] == pytest.approx(layout.subtitle_cm, abs=1e-9)
    assert sizes.heights_cm[6] == pytest.approx(layout.x_title_top_cm, abs=1e-9)
    assert sizes.heights_cm[10] == pytest.approx(layout.x_title_cm, abs=1e-9)
    assert sizes.heights_cm[13] == pytest.approx(layout.caption_cm, abs=1e-9)
    assert sizes.widths_cm[4] == pytest.approx(layout.y_title_cm, abs=1e-9)


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

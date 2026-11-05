"""主轴（M1-11）：断点 / 标签 / 尺寸 / grob。

断点与标签取自标度（`ggcore.scales`），尺寸取自主题（`ggcore.theme`）；
这里钉住「连续 / 离散 / log10 三条路径落到同一套 npc」以及 theme_void 下
整条轴归零。对拍 R 的数字在 `tests/test_guide_r_parity.py`。
"""

from __future__ import annotations

import numpy as np
import pytest

from ggcore import registry
from ggcore.axis import (
    TEXT_LINE_EM,
    AxisError,
    AxisTicks,
    axis_extent,
    axis_grobs,
    axis_ticks,
    axis_title_extent,
    axis_title_grob,
    text_line_cm,
    text_width_cm,
    tick_length_cm,
)
from ggcore.build import build_plot
from ggcore.data import Column, ColumnTable
from ggcore.gtable import CellBox
from ggcore.plot import aes, ggplot
from ggcore.theme import element_text, resolve_theme, theme_void
from ggcore.theme import theme as make_theme


def amounts(unit: object) -> list[float]:
    """`Unit` 的数值（测试只读断言用）。"""
    return [float(element.amount) for element in unit.elements]


class FakeMetrics:
    """稳定的假度量：每字符 0.5em 宽、0.955em 高（英寸）。"""

    def strwidth(self, text: str, *, fontsize: float, cex: float, font: str = "sans") -> float:
        del font
        return 0.5 * float(fontsize) * float(cex) * len(text) / 72.0

    def strheight(self, text: str, *, fontsize: float, cex: float, font: str = "sans") -> float:
        del text, font
        return 0.955 * float(fontsize) * float(cex) / 72.0


METRICS = FakeMetrics()


def table() -> ColumnTable:
    return ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0, 3.0, 4.0, 5.0]))),
            ("y", Column("float", np.array([10.0, 20.0, 30.0, 40.0, 50.0]))),
            (
                "g",
                Column(
                    "categorical",
                    np.array([0, 1, 2, 0, 1], dtype=np.int32),
                    levels=("a", "b", "c"),
                ),
            ),
        ]
    )


def _panel(plot) -> tuple[object, object]:
    build = build_plot(plot)
    panel = build.panels[0]
    return panel.scales.scale("x"), panel.panel_params


def test_text_helpers_follow_the_0955em_rule() -> None:
    assert text_line_cm(11.0) == pytest.approx(11.0 * TEXT_LINE_EM * 2.54 / 72.0)
    # 有度量时按字体宽度；没有时按 0.6em/字符估。
    assert text_width_cm("abc", 10.0, METRICS) == pytest.approx(0.5 * 10.0 * 3 * 2.54 / 72.0)
    assert text_width_cm("abc", 10.0, None) == pytest.approx(0.6 * 10.0 * 3 * 2.54 / 72.0)
    # 多行取最宽的一行。
    assert text_width_cm("a\nabcd", 10.0, METRICS) == pytest.approx(0.5 * 10.0 * 4 * 2.54 / 72.0)


def test_continuous_ticks_match_the_panel_range() -> None:
    plot = ggplot(table(), aes(x="x", y="y")) + registry.geom_point()
    scale, params = _panel(plot)
    ticks = axis_ticks(scale, params, "bottom")
    assert ticks.labels
    low, high = params.x_range
    for position, label in zip(ticks.positions, ticks.labels, strict=True):
        expected = (float(label) - low) / (high - low)
        assert position == pytest.approx(expected)
        assert 0.0 <= position <= 1.0
    # 标签就是断点在数据空间的值（format_numbers 的口径：整数不带 ".0"）。
    assert all("." not in label for label in ticks.labels)


def test_discrete_ticks_are_centred_on_levels() -> None:
    plot = ggplot(table(), aes(x="g", y="y")) + registry.geom_point()
    scale, params = _panel(plot)
    ticks = axis_ticks(scale, params, "bottom")
    assert ticks.labels == ("a", "b", "c")
    low, high = params.x_range
    for code, position in enumerate(ticks.positions, start=1):
        assert position == pytest.approx((code - low) / (high - low))
    # 离散轴水平居中于 tick：三个水平落在 1/6、1/2、5/6 附近（0..1 面板）。
    assert ticks.positions[1] == pytest.approx(0.5)


def test_log10_ticks_are_in_transformed_space() -> None:
    """断点已经是 log10 空间的值，位置按面板范围直接换算（不回头做 log）。"""
    plot = ggplot(table(), aes(x="x", y="y")) + registry.geom_point() + registry.scale_x_log10()
    scale, params = _panel(plot)
    ticks = axis_ticks(scale, params, "bottom")
    # 标度自己的断点 / 标签：轴只是把它们搬成 npc + 文本。
    breaks = [value for value in scale.breaks() if value is not None]
    labels = [label for label in scale.labels() if label is not None]
    assert list(ticks.labels) == labels
    low, high = params.x_range
    for position, value in zip(ticks.positions, breaks, strict=True):
        assert position == pytest.approx((float(value) - low) / (high - low))
    # 位置确实落在 0..1（log10 空间的断点没有再加一次 log）。
    assert all(0.0 <= position <= 1.0 for position in ticks.positions)


def test_axis_extent_reads_theme_units() -> None:
    theme = resolve_theme(registry.theme_grey())
    plot = ggplot(table(), aes(x="x", y="y")) + registry.geom_point()
    scale, params = _panel(plot)
    ticks = axis_ticks(scale, params, "bottom")
    tick = tick_length_cm(theme, "bottom")
    assert tick == pytest.approx(2.75 / 72.27 * 2.54)  # axis.ticks.length = 2.75pt
    extent = axis_extent(theme, ticks, metrics=METRICS)
    # 刻度 + 行高（8.8pt × 0.955em）+ 上 margin（2.2pt；R 的 pt = 1/72.27in）。
    expected = tick + text_line_cm(8.8) + 2.2 / 72.27 * 2.54
    assert extent == pytest.approx(expected)
    blank = resolve_theme(theme_void())
    assert axis_extent(blank, ticks, metrics=METRICS) == 0.0


def test_axis_title_extent_and_rotation() -> None:
    theme = resolve_theme(registry.theme_grey())
    margin = 2.75 / 72.27 * 2.54
    assert axis_title_extent(theme, "bottom", "X", metrics=METRICS) == pytest.approx(
        text_line_cm(11.0) + margin
    )
    # y 轴标题旋转 90°：外向尺寸是行高。
    assert axis_title_extent(theme, "left", "Y", metrics=METRICS) == pytest.approx(
        text_line_cm(11.0) + margin
    )
    assert axis_title_extent(theme, "left", None, metrics=METRICS) == 0.0


def test_axis_grobs_put_ticks_and_labels_outside_the_panel() -> None:
    theme = resolve_theme(registry.theme_grey())
    ticks = AxisTicks("bottom", (0.0, 1.0), ("1", "5"))
    box = CellBox(1, 1, 1, 1, 2.0, 3.0, 4.0, 5.0)
    grobs = axis_grobs(theme, ticks, box, metrics=METRICS)
    kinds = [type(grob).__name__ for grob in grobs]
    assert kinds[0] == "SegmentsGrob"
    assert kinds[1:] == ["TextGrob", "TextGrob"]
    # 刻度从面板底边向下画 axis.ticks.length。
    tick_grob = grobs[0]
    tick = tick_length_cm(theme, "bottom")
    assert amounts(tick_grob.y0) == pytest.approx([3.0, 3.0])
    assert amounts(tick_grob.y1) == pytest.approx([3.0 - tick, 3.0 - tick])
    assert amounts(tick_grob.x0) == pytest.approx([2.0, 6.0])
    # 标签在刻度下方、以 tick 为中心（hjust=0.5）。
    assert grobs[1].hjust == pytest.approx(0.5)
    assert grobs[1].vjust == pytest.approx(1.0)
    assert amounts(grobs[1].x) == pytest.approx([2.0])
    assert amounts(grobs[2].x) == pytest.approx([6.0])

    left = axis_grobs(theme, AxisTicks("left", (0.0, 1.0), ("1", "5")), box, metrics=METRICS)
    assert amounts(left[0].x0) == pytest.approx([2.0, 2.0])
    # 左轴文字还要让出 axis.text.y 的右 margin（2.2pt）。
    assert amounts(left[1].x) == pytest.approx([2.0 - tick - 2.2 / 72.27 * 2.54])
    assert left[1].hjust == pytest.approx(1.0)


def test_rotated_axis_labels_are_named_as_unimplemented() -> None:
    rotated = resolve_theme(make_theme(complete=False, **{"axis.text.x": element_text(angle=45)}))
    with pytest.raises(AxisError, match="angle=45"):
        axis_grobs(rotated, AxisTicks("bottom", (0.5,), ("1",)), CellBox(1, 1, 1, 1, 0, 0, 1, 1))


def test_axis_title_grob_anchor() -> None:
    theme = resolve_theme(registry.theme_grey())
    box = CellBox(1, 1, 1, 1, 2.0, 3.0, 4.0, 5.0)
    grob = axis_title_grob(theme, "bottom", "X", box, labels_extent_cm=0.5, metrics=METRICS)
    assert grob is not None
    assert amounts(grob.x) == pytest.approx([4.0])
    # 轴标题在轴文字下方：面板底 - 轴文字占位 - title margin(t)。
    margin = 2.75 / 72.27 * 2.54
    assert amounts(grob.y) == pytest.approx([3.0 - 0.5 - margin])
    left = axis_title_grob(theme, "left", "Y", box, labels_extent_cm=0.4, metrics=METRICS)
    assert left is not None and left.rot == pytest.approx(90.0)
    assert amounts(left.x) == pytest.approx([2.0 - 0.4 - margin])
    assert amounts(left.y) == pytest.approx([5.5])


def test_axis_ticks_reject_bad_arguments() -> None:
    # M2-1 起 top / right 是次轴的正式位置，不再报错。
    assert AxisTicks("top", (0.5,), ("a",)).side == "top"
    assert AxisTicks("right", (0.5,), ("a",)).side == "right"
    with pytest.raises(AxisError):
        AxisTicks("middle", (), ())
    with pytest.raises(AxisError, match="必须等长"):
        AxisTicks("bottom", (0.1, 0.2), ("a",))


def test_secondary_axis_title_is_hidden_for_waiver_and_derived_for_dup_axis() -> None:
    """SIL-759：`sec_axis()` 缺省（R waiver）不显示标题；`dup_axis()`（derive）沿用主轴。"""
    from ggcore.axis import DERIVE, dup_axis, sec_axis
    from ggcore.geom.scene import _secondary_title, plot_layout

    def layout_and_scale(secondary):
        build = build_plot(
            ggplot(table(), aes(x="x", y="y"))
            + registry.geom_point()
            + registry.scale_x_continuous(**{"sec.axis": secondary})
            + registry.labs(x="primary")
        )
        return build, plot_layout(build)

    # R 4.0.3 实测：sec_axis() 的 name 缺省是 waiver() → zeroGrob，顶部没有 xlab-t。
    build, layout = layout_and_scale(sec_axis(lambda value: value * 2))
    assert _secondary_title(build, "x", build.scales.scale("x")) is None
    assert layout.x_title_top_cm == 0.0

    # 显式 NULL 同义。
    build, layout = layout_and_scale(sec_axis(lambda value: value * 2, name=None))
    assert _secondary_title(build, "x", build.scales.scale("x")) is None
    assert layout.x_title_top_cm == 0.0

    # 给名字才画标题（R：1grobheight 的 xlab-t）。
    build, layout = layout_and_scale(sec_axis(lambda value: value * 2, name="double"))
    assert _secondary_title(build, "x", build.scales.scale("x")) == "double"
    assert layout.x_title_top_cm > 0.0

    # dup_axis() 的 name = derive()：沿用主轴标题。
    build, layout = layout_and_scale(dup_axis(name=DERIVE))
    assert _secondary_title(build, "x", build.scales.scale("x")) == "primary"
    assert layout.x_title_top_cm > 0.0


def test_polar_axis_row_reserves_the_theta_label_row() -> None:
    """polar 的 `axis-b` 行：刻度 + theta 标签行（不是 cartesian 的整行高度）。

    `numeric-polar` 快照：R 的 `axis-b` 是 6.94pt（刻度 2.75 + 标签行 4.19），
    少了这一行面板会大 6.77pt，同心圆全部错位。轴文字 blank 时只剩刻度。
    """
    from ggcore.axis import polar_axis_row_cm

    theme = resolve_theme(registry.theme_grey())
    tick = tick_length_cm(theme, "bottom")
    # 8.8pt 的轴文字：0.22 × 8.8 + 2.2 = 4.136pt（R 实测 4.19pt，差 0.05pt）。
    expected = tick + (0.22 * 8.8 + 2.2) / 72 * 2.54
    assert polar_axis_row_cm(theme) == pytest.approx(expected)
    blank = resolve_theme(theme_void())
    assert polar_axis_row_cm(blank) == pytest.approx(tick_length_cm(blank, "bottom"))


def test_axis_extent_counts_every_line_of_a_multiline_label() -> None:
    """多行轴标签的轴带 = 整块高度（SIL-816 的 outside-justified-labels）。

    行距 = `lineheight × 1.2 × fontsize`（`axis.text.*` 的 lineheight = 0.9），
    块高 = 首行高 + (n-1) 个行距。早先只按单行量，5 行标签的轴带只有一行高，
    面板被撑高、标签压进 strip。
    """
    from ggcore.axis import text_block_cm

    line = text_line_cm(8.8)
    single = text_block_cm("X", 8.8, 0.9)
    five = text_block_cm("X\nX\nX\nX\nX", 8.8, 0.9)
    pitch = 8.8 * 1.2 * 0.9 / 72.0 * 2.54
    assert single == pytest.approx(line)
    assert five == pytest.approx(line + 4 * pitch)
    assert five > 4 * single


class _PolarPanel:
    """极坐标面板的最小替身：只要 `theta_range` / `r_range`（R 的面板范围）。"""

    def __init__(self, theta: tuple[float, float], r: tuple[float, float]) -> None:
        self.theta_range = theta
        self.r_range = r


def test_polar_breaks_use_the_panel_range_not_the_scale_expansion() -> None:
    """极坐标断点走 R 的 `break_info(range)`：两条轴都**不做** 5% 展开。

    `matrix-report-facet-polar-grey` 的同心圆：y 数据 0.25..0.8，R 从面板范围
    得到 0.3 / 0.4 / … / 0.8 六圈（每 0.1）；拿标度自己的 5% 展开范围算只剩
    0.4 / 0.6 / 0.8 三圈，整张图差 8.5%。theta 同理（0.3/0.5/0.7/0.9 而不是
    0.25/0.5/0.75）。
    """
    from ggcore.axis import polar_axis_breaks
    from ggcore.scales import PositionContinuousScale

    y = PositionContinuousScale("y")
    y.train(Column("float", np.array([0.25, 0.8])))
    panel = _PolarPanel((0.15, 0.9), (0.25, 0.8))

    breaks, labels = polar_axis_breaks(y, panel, "r")
    assert breaks == pytest.approx((0.3, 0.4, 0.5, 0.6, 0.7, 0.8))
    assert labels == ("0.3", "0.4", "0.5", "0.6", "0.7", "0.8")
    # 标度自己的口径（expanded_limits 上的 5% 展开）仍然只有三条。
    assert y.breaks() == (None, pytest.approx(0.4), pytest.approx(0.6), pytest.approx(0.8))

    x = PositionContinuousScale("x")
    x.train(Column("float", np.array([0.15, 0.9])))
    breaks_x, _ = polar_axis_breaks(x, panel, "theta")
    assert breaks_x == (None, pytest.approx(0.3), pytest.approx(0.5), pytest.approx(0.7), 0.9)


def test_polar_minor_breaks_keep_major_positions_like_regular_minor_breaks() -> None:
    """`scales::regular_minor_breaks()` 是「每段左端点 + 中点」再补最后一个主断点。

    所以次断点**包含主断点**；`CoordPolar$render_bg()` 直接用这条序列画 theta
    细辐条（主辐条因此被画两遍），不会像 `guide_grid()` 那样 `setdiff`。
    """
    from ggcore.axis import polar_minor_breaks
    from ggcore.scales import PositionContinuousScale

    x = PositionContinuousScale("x")
    x.train(Column("float", np.array([0.15, 0.9])))
    panel = _PolarPanel((0.15, 0.9), (0.25, 0.8))

    values = polar_minor_breaks(x, panel, "theta")
    assert values == pytest.approx((0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9))

    # 显式 minor_breaks 用用户给的那组（只按面板范围过滤）。
    y = PositionContinuousScale("y", {"minor_breaks": (1.25, 2.75, 9.0)})
    y.train(Column("float", np.array([1.0, 3.0])))
    assert polar_minor_breaks(y, _PolarPanel((1.0, 3.0), (1.0, 3.0)), "r") == (1.25, 2.75)

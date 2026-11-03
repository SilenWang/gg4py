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
    axis_line_cm,
    axis_ticks,
    axis_title_extent,
    axis_title_grob,
    break_positions,
    minor_break_positions,
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


def test_break_positions_and_minor_breaks() -> None:
    """主/次断点的面板位置：次断点照 `scales::regular_minor_breaks()`（中点）。"""
    plot = (
        ggplot(table(), aes(x="x", y="y"))
        + registry.geom_point()
        + registry.scale_x_continuous(limits=(0, 6), expand=(0, 0))
    )
    scale, params = _panel(plot)
    majors = break_positions(scale, params, "bottom")
    assert len(majors) == 7  # 0..6
    assert majors[0] == pytest.approx(0.0)
    assert majors[-1] == pytest.approx(1.0)
    minors = minor_break_positions(scale, params, "bottom")
    assert minors == pytest.approx([(2 * index + 1) / 12 for index in range(6)])


def test_break_positions_ignore_labels_while_ticks_do_not() -> None:
    """`labels` 只影响刻度文字：空标签的断点不画文字，但网格线照画（R 的 guide_grid 用
    `mapped_breaks()`，不看 `labels`）。"""
    labelled = (
        ggplot(table(), aes(x="x", y="y"))
        + registry.geom_point()
        + registry.scale_x_continuous(limits=(0, 6), expand=(0, 0))
    )
    blank = (
        ggplot(table(), aes(x="x", y="y"))
        + registry.geom_point()
        + registry.scale_x_continuous(
            limits=(0, 6), expand=(0, 0), labels=("", "1", "", "3", "", "5", "")
        )
    )
    labelled_scale, labelled_params = _panel(labelled)
    blank_scale, blank_params = _panel(blank)
    assert len(axis_ticks(labelled_scale, labelled_params, "bottom").labels) == 7
    ticks = axis_ticks(blank_scale, blank_params, "bottom")
    assert ticks.labels == ("1", "3", "5")
    assert len(ticks.positions) == 3
    # 断点本身一个不少：网格线还是 7 条主线 + 6 条次线。
    assert break_positions(blank_scale, blank_params, "bottom") == pytest.approx(
        [index / 6 for index in range(7)]
    )
    assert len(minor_break_positions(blank_scale, blank_params, "bottom")) == 6


def test_minor_breaks_are_empty_for_discrete_and_single_break() -> None:
    discrete = ggplot(table(), aes(x="g", y="y")) + registry.geom_point()
    scale, params = _panel(discrete)
    assert minor_break_positions(scale, params, "bottom") == ()
    # 只有一个断点 → 没有区间，也就没有次断点。
    single = (
        ggplot(table(), aes(x="x", y="y"))
        + registry.geom_point()
        + registry.scale_x_continuous(limits=(2, 2.5), breaks=(2.2,))
    )
    scale, params = _panel(single)
    assert len(break_positions(scale, params, "bottom")) == 1
    assert minor_break_positions(scale, params, "bottom") == ()


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
    # 刻度 + 行高（8.8pt × lineheight 0.9 = 7.92pt）+ 上 margin（2.2pt）。
    # R 的 `axis-b` 行高实测 12.8708pt（`ggplotGrob()`，见 docs/notes/guide.md）。
    expected = tick + axis_line_cm(theme["axis.text.x.bottom"]) + 2.2 / 72.27 * 2.54
    assert extent == pytest.approx(expected)
    blank = resolve_theme(theme_void())
    assert axis_extent(blank, ticks, metrics=METRICS) == 0.0


def test_axis_extent_reads_the_position_specific_element() -> None:
    """`axis.text.y.left` 而不是 `axis.text.y`：`theme_minimal()` 只覆盖位置专属元素。

    上游的 guide 用 `theme_suffix` 取 `axis.text.y.left`；`theme_minimal()`
    把 y 轴标签的右 margin 从 2.2pt 换成 `0.45 × 11 = 4.95pt`，读父元素就丢了。
    """
    minimal = resolve_theme(registry.theme_minimal())
    assert minimal["axis.text.y.left"].margin.r is not None
    plot = ggplot(table(), aes(x="x", y="y")) + registry.geom_point()
    scale, params = _panel(plot)
    ticks = axis_ticks(scale, params, "left")
    grey = axis_extent(resolve_theme(registry.theme_grey()), ticks, metrics=METRICS)
    extent = axis_extent(minimal, ticks, metrics=METRICS)
    # theme_minimal 把 y 标签的右 margin 从 2.2 换成 `0.45 × 11 = 4.95pt`，同时
    # 抹掉 2.75pt 的刻度线——两项正好抵消，R 的参考图里面板位置与 theme_grey 相同。
    # 读父元素 `axis.text.y`（仍是 2.2）就会少算 2.75pt。
    assert extent == pytest.approx(grey)
    assert amounts(minimal["axis.text.y"].margin.r) == pytest.approx([2.2])
    assert amounts(minimal["axis.text.y.left"].margin.r) == pytest.approx([4.95])


def test_axis_title_extent_and_rotation() -> None:
    theme = resolve_theme(registry.theme_grey())
    margin = 2.75 / 72.27 * 2.54
    line = axis_line_cm(theme["axis.title.x.bottom"])
    assert line == pytest.approx(11.0 * 0.9 / 72.0 * 2.54)
    assert axis_title_extent(theme, "bottom", "X", metrics=METRICS) == pytest.approx(line + margin)
    # y 轴标题旋转 90°：外向尺寸是行高。
    assert axis_title_extent(theme, "left", "Y", metrics=METRICS) == pytest.approx(line + margin)
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
    with pytest.raises(AxisError):
        AxisTicks("top", (), ())
    with pytest.raises(AxisError, match="必须等长"):
        AxisTicks("bottom", (0.1, 0.2), ("a",))

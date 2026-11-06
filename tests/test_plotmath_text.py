"""plotmath 接进文本层（SIL-855）：strip 的 `label_parsed` 与轴标签的 `label_math()`。

上游两条快照的卡点相同：一段 plotmath 要拆成多段落字（底数与上标各自字号 /
基线抬升）。本文件钉住四件事：

- `plotmath.MathText` 是 `str` 子类，解析不了的串回退普通文本（同 `parse_safe()`）；
- 一段 plotmath 的**行盒**口径（R 的 `stringHeight()`）：8.8pt 的 `10^2` 是
  10.64pt（基线以上 0.999em、以下 0.21em），轴带 / strip 的行高按它量；
- 落字：一个标签 → 多个 IR text 节点（不新增 IR 字段），字号 8.8 / 6.16，上标
  比底数高 0.502em×字号；
- 两条上游 case 的版面数字（`guides-with-minor-ticks` 的 axis-b 行、负刻度不占
  轴带；`parsed-facet-labels` 的 strip 行高）。
"""

from __future__ import annotations

import numpy as np
import pytest

from ggcore import plotmath
from ggcore.axis import text_block_cm, text_width_cm
from ggcore.axis_guide import AxisGuide, axis_guide_extent, axis_guide_ticks
from ggcore.build import build_plot
from ggcore.data import Column, ColumnTable
from ggcore.geom.scene import _theme_of, scene_from_plot
from ggcore.ir.nodes import NodeKind
from ggcore.plot import (
    aes,
    facet_wrap,
    geom_point,
    ggplot,
    label_math,
    label_parsed,
    scale_x_continuous,
)
from ggcore.theme import resolve_theme, theme, theme_grey
from ggcore.units import unit

SIZE = {"width_in": 10.0, "height_in": 8.0}
GREY = resolve_theme(theme_grey())


def table() -> ColumnTable:
    return ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0, 3.0]))),
            ("y", Column("float", np.array([10.0, 20.0, 30.0]))),
            (
                "f",
                Column(
                    "categorical", np.array([0, 0, 0], dtype=np.int32), levels=("alpha ^ beta",)
                ),
            ),
        ]
    )


def _measure(text: str, size_pt: float) -> float:
    """每字符 0.6em 的占位度量（只验结构，不验字面）。"""
    return 0.6 * float(size_pt) * len(text)


def _text_nodes(scene) -> list:
    out: list = []

    def walk(node) -> None:
        if node.kind is NodeKind.TEXT:
            out.append(node)
        for child in node.children:
            walk(child)

    walk(scene.root)
    return out


# ---------------------------------------------------------------------------
# 标记与回退
# ---------------------------------------------------------------------------


def test_wrap_marks_parseable_text_and_falls_back_to_plain() -> None:
    marked = plotmath.wrap("alpha ^ beta")
    assert isinstance(marked, plotmath.MathText)
    assert plotmath.is_math(marked)
    # 解析不了的串原样返回普通 str（R 的 `parse_safe()` 同一口径），不抛异常。
    fallback = plotmath.wrap("a $ b")
    assert not plotmath.is_math(fallback)
    assert fallback == "a $ b"
    # `str` 子类：整条流水线照旧当字符串用。
    assert isinstance(marked, str)
    assert marked == "alpha ^ beta"


def test_script_extent_matches_the_upstream_box_height() -> None:
    """8.8pt 的 `10^2` 行盒 10.64pt（上游 axis-b 行 12.84pt − 2.2pt margin）。"""
    label = plotmath.layout("10^2", fontsize=8.8, measure=_measure)
    assert label.ascent_em == pytest.approx(plotmath.SCRIPT_SHIFT_EM + 0.7 * plotmath.ASCENT_EM)
    assert label.height_em == pytest.approx(label.ascent_em + plotmath.DESCENT_EM)
    assert label.height_em * 8.8 == pytest.approx(10.64, abs=0.02)
    # 纯文本的行高仍是 0.8945em（`TEXT_LINE_EM`），两者不能混。
    assert plotmath.layout("10", fontsize=8.8, measure=_measure).height_em < label.height_em


# ---------------------------------------------------------------------------
# `label_parsed` / `label_math()`
# ---------------------------------------------------------------------------


def test_label_parsed_returns_plotmath_labels() -> None:
    labels = label_parsed({"f": ["alpha ^ beta", "a $ b"]})
    parsed, plain = labels["f"]
    assert plotmath.is_math(parsed)
    assert not plotmath.is_math(plain)
    # 字符串写法也认（`labeller = "label_parsed"`）。
    assert plotmath.is_math(label_parsed({"f": ["beta[2]"]})["f"][0])


def test_label_math_builds_the_upstream_axis_labels() -> None:
    """`scale_x_continuous(labels = label_math())` 的断点 2..5 → `10^2` … `10^5`。"""
    formatter = label_math()
    labels = formatter([2.0, 3.0, 4.0, 5.0])
    assert [str(item) for item in labels] == ["10^2", "10^3", "10^4", "10^5"]
    assert all(plotmath.is_math(item) for item in labels)
    # 自定义模板 / 回调 / 解析失败的回退。
    assert str(label_math("x[.x]")([1.5])[0]) == "x[1.5]"
    assert str(label_math(lambda value: f"sqrt({value})")([9])[0]) == "sqrt(9)"
    assert not plotmath.is_math(label_math("a $ .x")([1])[0])


# ---------------------------------------------------------------------------
# 量尺寸：strip / 轴带
# ---------------------------------------------------------------------------


def test_math_label_measures_by_runs() -> None:
    class Metrics:
        def strwidth(self, text: str, *, fontsize: float, cex: float, font: str = "sans") -> float:
            del font
            return 0.5 * float(fontsize) * float(cex) * len(text) / 72.0

    plain = "10^2"
    math = plotmath.wrap(plain)
    # 底数 10（8.8pt）+ 上标 2（6.16pt），不是把 "10^2" 当四个字符量。
    expected_pt = 0.5 * 8.8 * 2 + 0.5 * 8.8 * 0.7 * 1
    assert text_width_cm(math, 8.8, Metrics()) * 72.0 / 2.54 == pytest.approx(expected_pt)
    assert text_width_cm(plain, 8.8, Metrics()) * 72.0 / 2.54 == pytest.approx(0.5 * 8.8 * 4)
    # 行高：纯文本 7.87pt，plotmath 10.64pt。
    assert text_block_cm(math, 8.8, metrics=Metrics()) * 72.0 / 2.54 == pytest.approx(
        10.64, abs=0.02
    )
    assert text_block_cm(plain, 8.8, metrics=Metrics()) * 72.0 / 2.54 == pytest.approx(
        7.87, abs=0.02
    )


def test_facet_strip_grows_by_the_superscript() -> None:
    """`labeller = label_parsed` 的 strip 比纯文本 strip 高 2.77pt（8.8pt 字）。"""
    plot = ggplot(table(), aes(x="x", y="y")) + geom_point() + facet_wrap("f") + theme_grey()
    plain = build_plot(plot).facet_table()
    parsed = build_plot(plot + facet_wrap("f", labeller=label_parsed)).facet_table()
    assert parsed.strip_height_cm > plain.strip_height_cm
    delta_pt = (parsed.strip_height_cm - plain.strip_height_cm) * 72.0 / 2.54
    assert delta_pt == pytest.approx((1.209 - 0.8945) * 8.8, abs=0.05)


def test_axis_band_grows_with_the_superscript() -> None:
    """数学标签把 axis-b 行撑高（8.8pt 的 `10^2` 比 `10` 高 2.77pt）。"""
    layout = (
        ggplot(table(), aes(x="x", y="y")) + geom_point() + scale_x_continuous(labels=label_math())
    )
    ticks = _guide_ticks(layout)
    plain = _guide_ticks(
        ggplot(table(), aes(x="x", y="y"))
        + geom_point()
        + scale_x_continuous(labels=lambda values: ["10" for _ in values])
    )
    delta_pt = (
        (
            axis_guide_extent(GREY, ticks, AxisGuide(), side="bottom")
            - axis_guide_extent(GREY, plain, AxisGuide(), side="bottom")
        )
        * 72.0
        / 2.54
    )
    assert delta_pt == pytest.approx((1.209 - 0.8945) * 8.8, abs=0.05)


def test_negative_ticks_do_not_shrink_the_axis_band() -> None:
    """负刻度画进面板内侧，R 的 `measure_grobs()` 仍按 0 占轴带。"""

    def extent(length_pt: float) -> float:
        plot = (
            ggplot(table(), aes(x="x", y="y"))
            + geom_point()
            + theme(**{"axis.ticks.length.x.bottom": unit(length_pt, "pt")})
        )
        build = build_plot(plot)
        resolved = _theme_of(build)
        ticks = axis_guide_ticks(
            build.scales.scale("x"),
            build.panels[0].panel_params,
            "bottom",
            AxisGuide(),
            resolved,
        )
        return axis_guide_extent(resolved, ticks, AxisGuide(), side="bottom")

    assert extent(-2.75) == pytest.approx(extent(0.0))
    assert extent(2.75) > extent(0.0)


def _guide_ticks(plot):
    build = build_plot(plot)
    return axis_guide_ticks(
        build.scales.scale("x"),
        build.panels[0].panel_params,
        "bottom",
        AxisGuide(),
        GREY,
    )


# ---------------------------------------------------------------------------
# 落字：一个标签 → 多个 text 节点
# ---------------------------------------------------------------------------


def test_strip_draws_one_text_node_per_run() -> None:
    plot = (
        ggplot(table(), aes(x="x", y="y"))
        + geom_point()
        + facet_wrap("f", labeller=label_parsed)
        + theme_grey()
    )
    nodes = [node for node in _text_nodes(scene_from_plot(plot, **SIZE)) if node.texts]
    runs = {
        (node.texts[0], round(float(node.params["size"]), 3)): node
        for node in nodes
        if node.texts[0] in ("α", "β")
    }
    assert ("α", 8.8) in runs
    assert ("β", 6.16) in runs
    base, script = runs[("α", 8.8)], runs[("β", 6.16)]
    # 上标沿基线紧跟底数，并且比底数高 0.502em × 字号。
    dx = float(script.bufs["pos"][0, 0]) - float(base.bufs["pos"][0, 0])
    dy = float(base.bufs["pos"][0, 1]) - float(script.bufs["pos"][0, 1])
    assert dx > 0
    assert dy == pytest.approx(plotmath.SCRIPT_SHIFT_EM * 8.8, abs=0.02)


def test_axis_draws_math_labels_as_runs() -> None:
    plot = (
        ggplot(table(), aes(x="x", y="y")) + geom_point() + scale_x_continuous(labels=label_math())
    )
    nodes = _text_nodes(scene_from_plot(plot, **SIZE))
    sizes = {(node.texts[0], round(float(node.params["size"]), 3)) for node in nodes if node.texts}
    # `10` + 上标 `2` / `3` / `4` 两档字号；y 轴（10 / 20 / 30）仍是纯文本。
    assert ("10", 8.8) in sizes
    assert ("2", 6.16) in sizes
    assert ("20", 8.8) in sizes
    assert ("2", 8.8) not in sizes


def test_unparseable_labels_fall_back_to_a_single_node() -> None:
    plot = (
        ggplot(table(), aes(x="x", y="y"))
        + geom_point()
        + scale_x_continuous(labels=label_math("a $ .x"))
    )
    nodes = _text_nodes(scene_from_plot(plot, **SIZE))
    # 每根刻度只有一个 text 节点，字号都是 axis.text 的 8.8pt。
    x_labels = [node for node in nodes if node.texts and node.texts[0].startswith("a $")]
    assert len(x_labels) >= 3
    assert {round(float(node.params["size"]), 3) for node in x_labels} == {8.8}

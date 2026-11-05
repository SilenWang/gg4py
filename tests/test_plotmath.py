"""plotmath（SIL-839）：`geom_text(parse = TRUE)` 的解析与排版。

数字口径来自上游快照 `geom-text/geom-text-with-expressions.svg`：11pt 正文、
上标 0.7 倍字号且基线上抬 0.502em、二元运算符两侧各 0.185em、根号宽 1.0191em。
"""

from __future__ import annotations

import pytest

from ggcore import plotmath


def _measure(text: str, size: float) -> float:
    """每字符 0.6em 的占位度量：只验排版结构。"""
    return 0.6 * size * len(text)


def test_greek_letters_are_mapped_to_unicode() -> None:
    assert plotmath.GREEK["alpha"] == "α"
    assert plotmath.GREEK["omega"] == "ω"
    # 未登记的名字原样保留。
    assert plotmath.SYMBOLS["infinity"] == "∞"


def test_superscript_uses_the_snapshot_cex_and_raise() -> None:
    """`beta^2`：上标 0.7 倍字号、抬 0.502em，紧跟在底数之后。"""
    label = plotmath.layout("beta^2", fontsize=11.0, measure=_measure)

    assert [run.text for run in label.runs] == ["β", "2"]
    base, script = label.runs
    assert (base.cex, base.rise_em) == (1.0, 0.0)
    assert script.cex == pytest.approx(0.7)
    assert script.rise_em == pytest.approx(0.502)
    # 上标紧接底数（`beta` 宽 0.6em）。
    assert script.x_em == pytest.approx(0.6)
    assert label.width_em == pytest.approx(0.6 + 0.6 * 0.7)


def test_binary_operator_leaves_space_on_both_sides() -> None:
    """`alpha + beta`：`+` 两侧各 0.185em（快照里 2.03pt / 11pt）。"""
    label = plotmath.layout("alpha + beta", fontsize=11.0, measure=_measure)
    texts = [run.text for run in label.runs]
    assert texts == ["α", "+", "β"]
    _alpha, plus, beta = label.runs
    assert plus.x_em == pytest.approx(0.6 + 0.185)
    assert beta.x_em == pytest.approx(0.6 + 0.185 + 0.6 + 0.185)


def test_juxtaposition_has_no_space() -> None:
    label = plotmath.layout("gamma * delta", fontsize=11.0, measure=_measure)
    assert [run.text for run in label.runs] == ["γ", "δ"]
    assert label.runs[1].x_em == pytest.approx(0.6)


def test_sqrt_emits_a_five_point_radical() -> None:
    """`sqrt(delta)`：折线 5 个点、被开方内容从 0.5191em 起、横杠盖到 1.0191em。"""
    label = plotmath.layout("sqrt(delta)", fontsize=11.0, measure=_measure)

    assert [run.text for run in label.runs] == ["δ"]
    assert label.runs[0].x_em == pytest.approx(plotmath.RADICAL_BODY_EM)
    assert len(label.rules) == 1
    points = label.rules[0].points
    assert len(points) == 5
    assert points[0][0] == pytest.approx(0.0)
    assert max(x for x, _ in points) == pytest.approx(plotmath.RADICAL_WIDTH_EM)
    assert label.rules[0].lwd == pytest.approx(0.75)
    # 宽度取「根号宽」与「主体 + 内容」的较大者（占位度量里 δ 有 0.6em）。
    assert label.width_em == pytest.approx(
        max(plotmath.RADICAL_WIDTH_EM, plotmath.RADICAL_BODY_EM + 0.6)
    )


def test_whole_snapshot_label_lays_out_in_order() -> None:
    """整条快照标签：`alpha + beta^2` 的段序与总宽。"""
    label = plotmath.layout("alpha + beta^2", fontsize=11.0, measure=_measure)
    assert [run.text for run in label.runs] == ["α", "+", "β", "2"]
    assert label.width_em == pytest.approx(0.6 + 0.185 + 0.6 + 0.185 + 0.6 + 0.6 * 0.7)
    # 上标把标签顶高：0.502 + 0.7 × 0.71 − 0.71 em。
    assert label.extra_ascent_em == pytest.approx(
        0.502 + 0.7 * plotmath.ASCENT_EM - plotmath.ASCENT_EM
    )


def test_unparsable_input_is_detected_for_the_text_fallback() -> None:
    assert plotmath.is_plausible("alpha + beta^2")
    assert not plotmath.is_plausible("alpha +")
    assert not plotmath.is_plausible("sqrt(delta")
    assert not plotmath.is_plausible("a $ b")

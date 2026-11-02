"""文字度量对拍（M1 文字测量）：逐行宽度 / 整块高度 / 行距。

夹具由 `pixi run -e refs refs:text` 生成（svglite 4×3 in，UTF-8）：R 侧
`grid::stringWidth` / `stringHeight`，单位 1/72 in。Python 侧用设备同一份
`ggskia.text.ShaperMetrics` 复量。

两条已知口径（`docs/notes/metrics-ledger.md`）：

- 纯 CJK、Noto Sans 的拉丁/混排：逐条 ≤ 0.5%（实测最大 0.39%）；
- `Noto Sans CJK SC` 族里的**拉丁**字形：R 的 fontconfig 回退到 Noto Sans
  度量（+6.3%），我们按 M0-7 的「第一个 cmap 覆盖的字族」规则留在 CJK 字面。
  这是共享 run 切分规则的既有口径，本测试把它钉成**已知偏差**而不是放宽整条
  门禁——其它组合仍然按 0.5% 判。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ggskia.text import LINE_PITCH, ShaperMetrics

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "text_r_reference.json"

#: 与 R 一致的口径：宽度相对差上限（实测最大 0.39%，留 25% 余量）。
TOLERANCE = 0.005
#: 高度：R 的 bold CJK 实例（fontconfig 合成）比 VF 的 cap 高 1%，单独放宽。
HEIGHT_TOLERANCE = 0.015
#: `Noto Sans CJK SC` 族里拉丁字形的已知回退偏差（实测 6.26%）。
CJK_LATIN_GAP = 0.07

FONT_SUFFIX = {2: "bold", 3: "italic", 4: "bold-italic"}


def _key(sample: dict) -> str:
    suffix = FONT_SUFFIX.get(int(sample["font"]), "")
    return f"{sample['family']}:{suffix}" if suffix else sample["family"]


def _has_latin(text: str) -> bool:
    return any(ord(ch) < 0x2E80 and ch.isalpha() for ch in text)


def _cjk_family_latin(sample: dict) -> bool:
    return sample["family"] == "Noto Sans CJK SC" and _has_latin(sample["text"])


@pytest.fixture(scope="module")
def reference() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def metrics() -> ShaperMetrics:
    return ShaperMetrics()


def test_fixture_was_generated_by_r(reference: dict) -> None:
    assert reference["device"]["kind"] == "svglite"
    assert reference["locale"] == "C.UTF-8"
    assert len(reference["samples"]) >= 18
    assert len(reference["multiline"]) >= 3


@pytest.mark.parametrize("index", range(36))
def test_string_width_matches_r(reference: dict, metrics: ShaperMetrics, index: int) -> None:
    """逐条对拍 `stringWidth`：中文 / 拉丁 / 混排 × 字面 × 字号。"""
    sample = reference["samples"][index]
    measured = (
        metrics.strwidth(sample["text"], fontsize=sample["size"], cex=1.0, font=_key(sample)) * 72.0
    )
    expected = float(sample["width"])
    relative = abs(measured - expected) / expected
    limit = CJK_LATIN_GAP if _cjk_family_latin(sample) else TOLERANCE
    assert relative <= limit, (
        f"{sample['family']} font={sample['font']} {sample['size']}pt "
        f"{sample['text']!r}: ours {measured:.3f} vs R {expected:.3f} "
        f"({relative:.2%} > {limit:.2%})"
    )


@pytest.mark.parametrize("index", range(36))
def test_string_height_matches_r(reference: dict, metrics: ShaperMetrics, index: int) -> None:
    """`stringHeight`：R 的 textGrob 高度是 cap height，不是 ascent + descent。"""
    sample = reference["samples"][index]
    measured = (
        metrics.strheight(sample["text"], fontsize=sample["size"], cex=1.0, font=_key(sample))
        * 72.0
    )
    expected = float(sample["height"])
    assert abs(measured - expected) / expected <= HEIGHT_TOLERANCE, (
        f"{sample['family']} {sample['size']}pt: ours {measured:.3f} vs R {expected:.3f}"
    )


@pytest.mark.parametrize("index", range(3))
def test_multiline_line_widths_match_r(reference: dict, metrics: ShaperMetrics, index: int) -> None:
    """`\\n` 逐行宽度：每一行单独与 `stringWidth` 对拍。"""
    sample = reference["multiline"][index]
    for line, expected_width in zip(sample["lines"], sample["line_widths"], strict=True):
        measured = (
            metrics.strwidth(line, fontsize=sample["size"], cex=1.0, font=_key(sample)) * 72.0
        )
        expected = float(expected_width)
        limit = CJK_LATIN_GAP if _cjk_family_latin({**sample, "text": line}) else TOLERANCE
        assert abs(measured - expected) / expected <= limit, (
            f"{sample['family']} {sample['size']}pt line {line!r}: "
            f"ours {measured:.3f} vs R {expected:.3f}"
        )


@pytest.mark.parametrize("index", range(3))
def test_multiline_block_height_and_pitch_match_r(
    reference: dict, metrics: ShaperMetrics, index: int
) -> None:
    """整块高度 = (n-1) × 行距 + 单行 cap height；行距 = 1.2 × lineheight × fontsize。"""
    sample = reference["multiline"][index]
    measured = (
        metrics.strheight(sample["text"], fontsize=sample["size"], cex=1.0, font=_key(sample))
        * 72.0
    )
    expected = float(sample["height"])
    assert abs(measured - expected) / expected <= TOLERANCE
    pitch = LINE_PITCH * float(sample["size"])
    assert abs(pitch - float(sample["line_pitch"])) / float(sample["line_pitch"]) <= TOLERANCE


def test_width_is_the_widest_line(reference: dict, metrics: ShaperMetrics) -> None:
    """多行宽度取各行的最大值（IR 的 text.width 就是整块宽）。"""
    sample = reference["multiline"][0]
    whole = metrics.strwidth(sample["text"], fontsize=sample["size"], cex=1.0, font=_key(sample))
    per_line = [
        metrics.strwidth(line, fontsize=sample["size"], cex=1.0, font=_key(sample))
        for line in sample["lines"]
    ]
    assert whole == pytest.approx(max(per_line))
    assert whole == pytest.approx(float(sample["width"]) / 72.0, rel=0.07)

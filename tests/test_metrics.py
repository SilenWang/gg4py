"""M0-7：MetricProvider、run 切分、兜底表与字体定位。

HarfBuzz 后端（`ggshape`）只在 dev/服务端环境可用；`ggcore.metrics` 本身仍然是
纯 numpy 包，兜底表可以在没有 HarfBuzz 的环境里工作（Pyodide 早期路径）。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ggcore.metrics import (
    DEFAULT_FONT_STACK,
    RUN_RULES_VERSION,
    TABLE_VERSION,
    FontCatalog,
    FontNotFound,
    MetricProvider,
    TableBackend,
    clusters,
    decode_table,
    encode_table,
    is_supported,
    split_runs,
    table_path,
)
from ggcore.metrics.catalog import MANAGED_FONTS, default_font_dir
from ggshape import HarfBuzzBackend, harfbuzz_provider

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "docs" / "spike" / "corpus" / "labels_200.json"
BUILD_TABLE = REPO / "tools" / "metrics" / "build_table.py"


@pytest.fixture(scope="module")
def catalog() -> FontCatalog:
    return FontCatalog()


@pytest.fixture(scope="module")
def hb(catalog: FontCatalog) -> MetricProvider:
    return harfbuzz_provider(catalog)


@pytest.fixture(scope="module")
def table(catalog: FontCatalog) -> MetricProvider:
    return MetricProvider(TableBackend.from_file(), catalog=catalog)


# --- 字体定位 -------------------------------------------------------------


def test_catalog_uses_conda_prefix_fonts(catalog: FontCatalog) -> None:
    expected = Path(os.environ["CONDA_PREFIX"]) / "fonts"
    assert catalog.root == expected
    for filename in DEFAULT_FONT_STACK:
        assert catalog.path(filename).is_file()
        assert len(catalog.sha256(filename)) == 64


def test_catalog_family_names_are_the_shared_registry(catalog: FontCatalog) -> None:
    assert catalog.family("DejaVuSans.ttf") == "DejaVu Sans"
    assert catalog.family("NotoSansCJKsc-VF.ttf") == "Noto Sans CJK SC"
    assert catalog.family("NotoColorEmoji.ttf") == "Noto Color Emoji"
    # 未登记的文件按主干名兜底，两端至少拿到同一个名字。
    assert catalog.family("SomeFont.ttf") == "SomeFont"


def test_catalog_prefers_explicit_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GG_FONT_DIR", str(tmp_path))
    assert default_font_dir() == tmp_path

    catalog = FontCatalog()  # 走 GG_FONT_DIR
    assert catalog.root == tmp_path
    with pytest.raises(FontNotFound):
        catalog.path("DejaVuSans.ttf")
    assert catalog.exists("DejaVuSans.ttf") is False


def test_catalog_rejects_a_missing_directory() -> None:
    with pytest.raises(FontNotFound):
        FontCatalog(Path("/nonexistent-font-dir"))


def test_metric_provider_rejects_unknown_font(tmp_path: Path) -> None:
    empty = FontCatalog(tmp_path)
    with pytest.raises(LookupError):
        MetricProvider(HarfBuzzBackend(empty), catalog=empty)


# --- 规则与 corpus ---------------------------------------------------------


def test_corpus_font_stack_matches_the_rules() -> None:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    assert tuple(corpus["font_stack"]) == DEFAULT_FONT_STACK


def test_split_runs_falls_back_by_codepoint() -> None:
    def covers(index: int, codepoint: int) -> bool:
        # 主字族只认 ascii，第二字族认 CJK，第三字族认 emoji。
        if index == 0:
            return codepoint < 0x80
        if index == 1:
            return 0x4E00 <= codepoint <= 0x9FFF
        return codepoint >= 0x1F300

    runs = split_runs("a月🌱", covers, 3)
    assert [(run.font_index, run.text) for run in runs] == [(0, "a"), (1, "月"), (2, "🌱")]


def test_split_runs_keeps_glue_codepoints_in_the_current_run() -> None:
    def covers(index: int, codepoint: int) -> bool:
        return index == 0 and codepoint < 0x80

    # VS16 与 ZWJ 不单独起 run：它们跟着前一个字符走。
    runs = split_runs("a\ufe0f\u200db", covers, 1)
    assert [(run.font_index, run.text) for run in runs] == [(0, "a\ufe0f\u200db")]


def test_clusters_group_emoji_sequences() -> None:
    assert clusters("👨\u200d👩\u200d👧\u200d👦") == ("👨\u200d👩\u200d👧\u200d👦",)
    assert clusters("🇨🇳") == ("🇨🇳",)
    assert clusters("🇨🇳🇯🇵") == ("🇨🇳", "🇯🇵")
    assert clusters("1\ufe0f\u20e3") == ("1\ufe0f\u20e3",)
    assert clusters("e\u0301x") == ("e\u0301", "x")


def test_is_supported_rejects_complex_scripts() -> None:
    assert is_supported("Sepal Length 月份 🌱")
    assert not is_supported("العربية")
    assert not is_supported("नमस्ते")
    assert not is_supported("\u1100\u1161\u11a8")  # 朝鲜 jamo


# --- MetricProvider -------------------------------------------------------


def test_advance_matches_run_split(hb: MetricProvider) -> None:
    runs = hb.runs("月份（万元）", 16)
    assert len(runs) == 1
    assert runs[0].font == "NotoSansCJKsc-VF.ttf"
    assert runs[0].family == "Noto Sans CJK SC"
    assert hb.advance("月份（万元）", 16) == pytest.approx(runs[0].width)


def test_advance_splits_latin_cjk_and_emoji_into_three_runs(hb: MetricProvider) -> None:
    runs = hb.runs("Sales 月份 🌱", 16)
    assert [run.font for run in runs] == [
        "DejaVuSans.ttf",
        "NotoSansCJKsc-VF.ttf",
        "DejaVuSans.ttf",
        "NotoColorEmoji.ttf",
    ]
    assert [run.text for run in runs] == ["Sales ", "月份", " ", "🌱"]


def test_advance_scales_linearly_with_font_size(hb: MetricProvider) -> None:
    text = "Sepal Length"
    assert hb.advance(text, 32) == pytest.approx(2 * hb.advance(text, 16), rel=1e-12)


def test_empty_text_measures_zero(hb: MetricProvider) -> None:
    assert hb.advance("", 12) == 0.0
    assert hb.runs("", 12) == ()
    assert hb.strheight("", 12) > 0  # 空标签也要占一行，别塌成 0


def test_strwidth_is_an_alias_of_advance(hb: MetricProvider) -> None:
    assert hb.strwidth("月份", 12) == hb.advance("月份", 12)


def test_strheight_is_ascent_plus_descent(hb: MetricProvider) -> None:
    assert hb.strheight("Sepal", 16) == pytest.approx(hb.ascent(16) + hb.descent(16))
    assert hb.ascent(16) > 0 and hb.descent(16) > 0


def test_font_stack_argument_disables_fallback(hb: MetricProvider) -> None:
    text = "月份"
    full = hb.advance(text, 16)
    primary_only = hb.advance(text, 16, font_stack=("DejaVuSans.ttf",))
    assert primary_only != pytest.approx(full)
    assert hb.runs(text, 16, font_stack=("DejaVuSans.ttf",))[0].font == "DejaVuSans.ttf"


def test_cache_hits_and_evictions(catalog: FontCatalog) -> None:
    provider = MetricProvider(HarfBuzzBackend(catalog), catalog=catalog, cache_size=2)
    provider.advance("Alpha", 16)
    provider.advance("Alpha", 16)
    stats = provider.cache_stats()
    assert stats["misses"] == 1 and stats["hits"] == 1
    assert stats["hit_rate"] == pytest.approx(0.5)

    provider.advance("Beta", 16)
    provider.advance("Gamma", 16)  # 容量 2：最早的 Alpha 被淘汰
    assert provider.cache_stats()["evictions"] == 1
    provider.clear_cache()
    assert provider.cache_stats()["entries"] == 0


def test_invalid_size_is_rejected(hb: MetricProvider) -> None:
    for bad in (0, -1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            hb.advance("A", bad)


# --- 兜底表 ---------------------------------------------------------------


def test_table_header_is_versioned() -> None:
    blob = table_path().read_bytes()
    assert blob.startswith(b"GGMT")
    fonts = decode_table(blob)
    assert {font.filename for font in fonts} == set(DEFAULT_FONT_STACK)
    metadata = json.loads(table_path().with_suffix(".json").read_text(encoding="utf-8"))
    assert metadata["table_version"] == TABLE_VERSION
    assert metadata["run_rules_version"] == RUN_RULES_VERSION
    assert metadata["table_sha256"] == hashlib.sha256(blob).hexdigest()


def test_table_rejects_unknown_versions() -> None:
    blob = bytearray(table_path().read_bytes())
    broken = bytes(blob[:4]) + b"\xff\xff" + bytes(blob[6:])
    with pytest.raises(ValueError, match="version"):
        decode_table(broken)
    with pytest.raises(ValueError, match="not a metrics table"):
        decode_table(b"XXXX" + bytes(blob[4:]))


def test_table_round_trips_its_own_encoding() -> None:
    blob = table_path().read_bytes()
    assert encode_table(decode_table(blob)) == blob


def test_table_is_generated_by_the_committed_script(catalog: FontCatalog) -> None:
    """表必须由 `tools/metrics/build_table.py` 从当前字体与规则生成（同一脚本、同版本）。"""
    metadata = json.loads(table_path().with_suffix(".json").read_text(encoding="utf-8"))
    for font in metadata["fonts"]:
        assert font["sha256"] == catalog.sha256(font["file"]), (
            f"{font['file']} changed; regenerate the metrics table (pixi run metrics:table)"
        )

    proc = subprocess.run(
        [sys.executable, str(BUILD_TABLE), "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_table_and_harfbuzz_agree_on_the_corpus(hb: MetricProvider, table: MetricProvider) -> None:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    worst = 0.0
    for label in corpus["labels"]:
        text = label["text"]
        assert [(r.font, r.text) for r in hb.runs(text, 16)] == [
            (r.font, r.text) for r in table.runs(text, 16)
        ], f"run layout differs for {label['id']}"
        if not is_supported(text):
            continue
        reference = hb.advance(text, 16)
        worst = max(worst, abs(table.advance(text, 16) - reference) / reference)
    # 表不做 kerning：DejaVu 上实测 3.59%，判据 5%（docs/notes/metrics-ledger.md · M0-7）。
    assert worst < 0.05, f"fallback table drifts {worst:.2%} from HarfBuzz"


def test_table_reports_complex_scripts_as_unsupported(table: MetricProvider) -> None:
    assert table.supports("Sepal 月份 🌱")
    assert not table.supports("العربية")


def test_table_backend_needs_a_table(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        TableBackend.from_file(tmp_path / "missing.bin")


def test_managed_fonts_registry_covers_the_stack() -> None:
    assert set(DEFAULT_FONT_STACK) <= set(MANAGED_FONTS)
    assert MANAGED_FONTS["DejaVuSans.ttf"].family == "DejaVu Sans"

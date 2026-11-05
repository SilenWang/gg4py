"""上游快照清单与阈值分档的契约（SIL-745）。"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


SNAPSHOTS = _load("gg_snapshots_for_tests", "tools/upstream/snapshots.py")
TIERS = _load("gg_tiers_for_tests", "tools/cases/snapshot_tiers.py")


def test_manifest_pin_matches_upstream_doc() -> None:
    doc = (ROOT / "docs" / "notes" / "upstream.md").read_text(encoding="utf-8")
    commit = re.search(r"^- commit: ([0-9a-f]{40})$", doc, re.MULTILINE)
    assert commit
    manifest = SNAPSHOTS.load_manifest()
    assert manifest["pin"]["commit"] == commit.group(1)
    assert manifest["pin"]["tag"] == "v4.0.3"


def test_manifest_is_complete_and_deduplicated() -> None:
    manifest = SNAPSHOTS.load_manifest()
    paths = [entry["path"] for entry in manifest["snapshots"]]
    assert len(paths) == len(set(paths))
    # 钉住的 commit 上 `_snaps/**/*.svg` 实际是 311（计划里写的 314，见 snapshot-policy）。
    assert len(paths) == 311
    for entry in manifest["snapshots"]:
        assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]), entry["path"]
        assert entry["bytes"] > 0
        assert entry["path"].endswith(".svg")


def test_every_snapshot_has_a_disposition() -> None:
    rows = SNAPSHOTS.resolve(SNAPSHOTS.load_manifest(), SNAPSHOTS.load_dispositions())
    for row in rows:
        assert not row.get("error"), row["path"]
        if row["case"]:
            continue
        assert re.fullmatch(r"SIL-\d+", row["issue"]), row["path"]
        assert row["reason"].strip(), row["path"]


def test_imported_cases_match_the_upstream_bytes() -> None:
    problems, summary = SNAPSHOTS.check()
    assert not problems, problems
    assert summary["imported"] > 0
    assert summary["imported"] + summary["gaps"] == summary["total"]


def test_every_gap_cluster_declares_an_owner() -> None:
    """SIL-786：每簇必须写 owner = m2-closeout | m3，缺 owner 会让收口无主。"""
    dispositions = SNAPSHOTS.load_dispositions()
    groups = dispositions["groups"]
    for name, group in groups.items():
        assert group.get("owner") in SNAPSHOTS.OWNERS, name
    rows = SNAPSHOTS.resolve(SNAPSHOTS.load_manifest(), dispositions)
    for row in rows:
        if not row["case"]:
            assert row["owner"] in SNAPSHOTS.OWNERS, row["path"]


def test_inventory_burndown_is_generated_from_the_toml() -> None:
    """清单是生成物：台账（含 owner 与 burndown）不允许和 snapshots.toml 漂移。"""
    assert SNAPSHOTS.check_report() == []


def _resolved() -> list[dict]:
    return SNAPSHOTS.resolve(SNAPSHOTS.load_manifest(), SNAPSHOTS.load_dispositions())


def test_inventory_header_equals_the_burndown_sum() -> None:
    """SIL-822：表头（按 owner 合计）= burndown 逐簇相加，提交的清单里就必须成立。"""
    rows = _resolved()
    text = (ROOT / "docs" / "notes" / "snapshot-inventory.md").read_text(encoding="utf-8")
    assert SNAPSHOTS.inventory_drift(text, rows) == []


def test_report_check_reproduces_the_sil822_drift() -> None:
    """把本次漂移原样注入清单：表头 / 逐簇相加 / toml owner 对不上时必须判红。

    复现的是 SIL-822 的两处已知冲突：三个簇在 burndown 表里标 `m2-closeout`
    （逐簇相加 7 / 32），表头却按逐条 owner 写 0 / 39，且 `coord-polar` 的
    group owner 停在 `m2-closeout`。
    """
    rows = _resolved()
    text = SNAPSHOTS.render_inventory(rows, SNAPSHOTS.load_manifest()["pin"])
    assert SNAPSHOTS.inventory_drift(text, rows) == []

    drifted = text
    for cluster in ("coord-polar", "guide-axis", "facet-labels", "geom-hline-vline-abline"):
        drifted = drifted.replace(f"| `{cluster}` | m3 |", f"| `{cluster}` | m2-closeout |")
    assert drifted != text

    problems = SNAPSHOTS.inventory_drift(drifted, rows)
    assert any("表头写" in problem and "逐簇相加" in problem for problem in problems), problems
    assert any(
        "`coord-polar`" in problem and "burndown owner" in problem for problem in problems
    ), problems


def test_group_owner_that_stops_at_m2_closeout_is_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """只改单条 owner、group owner 停在 m2-closeout（本次漂移的来源）→ `snapshots:check` 红。"""
    dispositions = SNAPSHOTS.load_dispositions()
    dispositions["groups"]["coord-polar"]["owner"] = "m2-closeout"
    rows = SNAPSHOTS.resolve(SNAPSHOTS.load_manifest(), dispositions)
    moved = [row["path"] for row in rows if row["cluster"] == "coord-polar" and not row["case"]]
    assert moved
    for path in moved:
        dispositions["snapshots"].setdefault(path, {})["owner"] = "m3"
    monkeypatch.setattr(SNAPSHOTS, "load_dispositions", lambda: dispositions)
    problems, _ = SNAPSHOTS.check()
    assert any("coord-polar" in problem and "m2-closeout" in problem for problem in problems), (
        problems
    )


def test_matrix_ledger_must_match_the_inventory() -> None:
    """`matrix.md` 的上游快照表是第三处口径，与台账不一致时必须红。"""
    rows = _resolved()
    text = (ROOT / "docs" / "cases" / "matrix.md").read_text(encoding="utf-8")
    assert SNAPSHOTS.matrix_drift(text, rows) == []

    summary = SNAPSHOTS.ledger(rows)
    current = (
        f"| {summary['total']} | {summary['imported']} | {summary['gaps']} | "
        f"{summary['by_owner']['m2-closeout']} | {summary['by_owner']['m3']} |"
    )
    planted = (
        f"| {summary['total']} | {summary['imported']} | {summary['gaps']} | 7 | "
        f"{summary['gaps'] - 7} |"
    )
    drifted = text.replace(current, planted)
    assert drifted != text
    assert SNAPSHOTS.matrix_drift(drifted, rows)


def test_large_base_size_outliers_are_admitted_without_widening_bands() -> None:
    """三条大字号快照曾是**实现缺口**，修好 `from_theme()` 后按 2% 档纳管（SIL-792）。

    这条测试守的是反方向：它们必须真的成为 case（不再靠缺口条目躺在台账里），
    也就不能再拿 heavy 档的 2.5% 当退路。
    """
    rows = {
        row["path"]: row
        for row in SNAPSHOTS.resolve(SNAPSHOTS.load_manifest(), SNAPSHOTS.load_dispositions())
    }
    for path, case in (
        ("theme/theme-bw-large.svg", "upstream-theme-bw-large"),
        ("theme/theme-classic-large.svg", "upstream-theme-classic-large"),
        ("theme/theme-linedraw-large.svg", "upstream-theme-linedraw-large"),
    ):
        assert rows[path]["case"] == case, path


def test_band_ceilings_are_monotonic_and_never_below_two_percent() -> None:
    loads = [band[1] for band in TIERS.BANDS]
    assert loads == sorted(loads)
    for _name, _upper, image_cap, mean_cap in TIERS.BANDS:
        assert image_cap >= 0.02
        assert mean_cap >= 0.01
        # 任何一个档位都不许把整体 2% / 1% 口径调松到「没边」。
        assert image_cap <= 0.025


def test_declared_tolerances_fit_their_band() -> None:
    measured = TIERS.rows(with_ink=False)
    assert measured, "docs/cases 下应当有 expected.svg"
    assert TIERS.check(measured) == []


def test_text_load_counts_font_scale() -> None:
    """同一个标签在 33px 下的负载是 11px 的 9 倍——档位必须能区分大字号。"""
    import tempfile

    def svg(font: float) -> Path:
        handle = tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False, encoding="utf-8")
        handle.write(f"<svg><text style='font-size: {font}px'>abc</text></svg>")
        handle.close()
        return Path(handle.name)

    small = svg(11)
    large = svg(33)
    try:
        assert TIERS.text_stats(small) == (1, 3.0)
        assert TIERS.text_stats(large) == (1, pytest.approx(27.0))
        assert TIERS.band_of(3.0)[0] == "text-light"
        assert TIERS.band_of(27.0)[0] == "text-medium"
    finally:
        small.unlink()
        large.unlink()

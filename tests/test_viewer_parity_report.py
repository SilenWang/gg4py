"""SIL-1017：入库 parity 报告的门禁（不启浏览器、不渲染）。

`tools/viewer/parity.py --check-report` 守的是「`docs/notes/viewer-parity.md`
与 `docs/cases` 实测同源」，而不是「parity 全绿」——报告允许写着 19 条失败，
但不允许写错数字。这里用一份三 case 的假清单逐条守住：

- 一致 → 通过；
- 手改结论行的 pass 数、删掉一条失败、改指纹、把原因改成破折号 → 红；
- 清单涨了但报告没重生成（报告只覆盖两条）→ 红；
- `--measure` 层：实测 status 与报告不一致 → 红。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools" / "viewer"))
sys.path.insert(0, str(REPO / "src"))

import parity

CASES = [
    SimpleNamespace(name="alpha-point", family="geom-point"),
    SimpleNamespace(name="beta-bar", family="geom-bar"),
    SimpleNamespace(name="gamma-text", family="text"),
]


def _results() -> list[parity.ParityCase]:
    return [
        parity.ParityCase(
            case="alpha-point",
            family="geom-point",
            status="pass",
            pixel=0.0,
            mean=0.0,
            bbox_delta=0.0,
            centroid_delta=0.0,
            styles_skia=2,
            styles_viewer=2,
        ),
        parity.ParityCase(
            case="beta-bar",
            family="geom-bar",
            status="pass",
            pixel=0.001,
            mean=0.0,
            bbox_delta=0.0,
            centroid_delta=0.01,
            styles_skia=3,
            styles_viewer=3,
        ),
        parity.ParityCase(
            case="gamma-text",
            family="text",
            status="fail",
            pixel=0.012,
            mean=0.002,
            bbox_delta=0.0,
            centroid_delta=0.02,
            styles_skia=2,
            styles_viewer=1,
            detail="像素差超 0.5%",
        ),
    ]


def _report(
    tmp_path: Path,
    *,
    cases: list[SimpleNamespace] | None = None,
    results: list[parity.ParityCase] | None = None,
) -> Path:
    path = tmp_path / "viewer-parity.md"
    path.write_text(
        parity.render_report(
            results if results is not None else _results(),
            now="2026-11-25T00:00:00Z",
            command="pixi run viewer:parity:report",
            cases=cases if cases is not None else CASES,
        ),
        encoding="utf-8",
    )
    return path


def _patch_inventory(monkeypatch, cases: list[SimpleNamespace] | None = None) -> None:
    monkeypatch.setattr(parity, "inventory", lambda: list(cases or CASES))


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"报告里找不到 {old!r}"
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_consistent_report_passes(tmp_path: Path, monkeypatch) -> None:
    _patch_inventory(monkeypatch)
    path = _report(tmp_path)
    assert parity.check_report(path) == []


def test_report_carries_counts_failures_and_reasons(tmp_path: Path, monkeypatch) -> None:
    _patch_inventory(monkeypatch)
    path = _report(tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "- 案例清单：3 条" in text
    assert "- 结论：pass 2 / fail 1 / error 0 / 共 3；" in text
    summary, problems = parity.read_summary(text)
    assert problems == []
    assert summary is not None
    assert summary["counts"] == {"pass": 2, "fail": 1, "error": 0}
    assert [item["case"] for item in summary["failures"]] == ["gamma-text"]
    assert summary["failures"][0]["reason"] == "像素差超 0.5%"
    assert summary["inventory"]["cases"] == 3
    assert summary["inventory"]["sha256"] == parity.inventory_digest(CASES)


def test_tampered_pass_count_fails(tmp_path: Path, monkeypatch) -> None:
    """验收原例：把 pass 数改大（513 → 532 的同一手法）。"""
    _patch_inventory(monkeypatch)
    path = _report(tmp_path)
    _edit(
        path,
        "- 结论：pass 2 / fail 1 / error 0 / 共 3；",
        "- 结论：pass 3 / fail 1 / error 0 / 共 3；",
    )
    problems = parity.check_report(path)
    assert any("pass" in problem and "表格" in problem for problem in problems)
    assert any("自相矛盾" in problem for problem in problems)


def test_tampered_machine_summary_fails(tmp_path: Path, monkeypatch) -> None:
    _patch_inventory(monkeypatch)
    path = _report(tmp_path)
    text = path.read_text(encoding="utf-8")
    summary, _ = parity.read_summary(text)
    assert summary is not None
    summary["counts"]["pass"] = 3
    _edit(
        path,
        json.dumps(parity.read_summary(text)[0], ensure_ascii=False, indent=2),
        json.dumps(summary, ensure_ascii=False, indent=2),
    )
    problems = parity.check_report(path)
    assert any("counts.pass=3" in problem for problem in problems)


def test_dropped_failure_fails(tmp_path: Path, monkeypatch) -> None:
    _patch_inventory(monkeypatch)
    path = _report(tmp_path)
    text = path.read_text(encoding="utf-8")
    summary, _ = parity.read_summary(text)
    assert summary is not None
    summary["failures"] = []
    _edit(
        path,
        json.dumps(parity.read_summary(text)[0], ensure_ascii=False, indent=2),
        json.dumps(summary, ensure_ascii=False, indent=2),
    )
    problems = parity.check_report(path)
    assert any("failures" in problem and "表格" in problem for problem in problems)


def test_tampered_digest_fails(tmp_path: Path, monkeypatch) -> None:
    _patch_inventory(monkeypatch)
    path = _report(tmp_path)
    digest = parity.inventory_digest(CASES)
    _edit(path, f"`sha256:{digest[:16]}`", "`sha256:0000000000000000`")
    problems = parity.check_report(path)
    assert any("清单指纹" in problem for problem in problems)


def test_stale_report_after_new_case_fails(tmp_path: Path, monkeypatch) -> None:
    """SIL-1017 的原始故障：case 涨了，报告还是旧的。"""
    _patch_inventory(monkeypatch)
    path = _report(tmp_path, cases=CASES[:2], results=_results()[:2])
    problems = parity.check_report(path)
    assert any("实测 3 条" in problem or "case 表格" in problem for problem in problems)


def test_missing_failure_reason_fails(tmp_path: Path, monkeypatch) -> None:
    _patch_inventory(monkeypatch)
    path = _report(tmp_path)
    _edit(path, "- 结论：fail；像素差超 0.5%", "- 结论：fail；—")
    problems = parity.check_report(path)
    assert any("没有失败原因" in problem for problem in problems)


def test_sample_command_rejected(tmp_path: Path, monkeypatch) -> None:
    _patch_inventory(monkeypatch)
    path = _report(tmp_path)
    _edit(path, "`pixi run viewer:parity:report`", "`pixi run viewer:parity --sample 12`")
    problems = parity.check_report(path)
    assert any("抽样" in problem for problem in problems)


def test_measure_layer_catches_status_drift(tmp_path: Path, monkeypatch) -> None:
    _patch_inventory(monkeypatch)
    path = _report(tmp_path)
    measured = _results()
    measured[2].status = "pass"
    measured[2].detail = ""
    problems = parity.check_report(path, results=measured)
    assert any("实测 pass" in problem for problem in problems)
    assert any("失败名单" in problem for problem in problems)


def test_main_exit_codes(tmp_path: Path, monkeypatch) -> None:
    _patch_inventory(monkeypatch)
    path = _report(tmp_path)
    assert parity.main(["--check-report", "--report", str(path)]) == 0
    _edit(path, "- 结论：pass 2 /", "- 结论：pass 3 /")
    assert parity.main(["--check-report", "--report", str(path)]) == 1

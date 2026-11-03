"""`api:coverage` 门禁本身（SIL-745）：阈值、缺口归口、快照与 pin、公开入口真的能用。"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

from ggcore import plot, registry
from ggcore.guide import GuideLegend, guide_from_component, guide_geom, guide_merge, guide_train
from ggcore.theme import Theme, element_text, theme_get

ROOT = Path(__file__).resolve().parents[1]


def _gate():
    path = ROOT / "tools" / "gates" / "api_coverage.py"
    spec = importlib.util.spec_from_file_location("api_coverage_gate", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


GATE = _gate()


def _surface_with(*, category: str, exports: list[str]) -> dict:
    return {
        "pin": GATE.PIN,
        "source": "NAMESPACE",
        "threshold": 0.9,
        "categories": {
            category: {"prefix": GATE.KINDS[category], "exclude": [], "exports": exports}
        },
    }


def test_snapshot_pin_matches_upstream_doc() -> None:
    """快照里的 commit 必须与 docs/notes/upstream.md 的 `- commit:` 行一致（X2）。"""
    doc = (ROOT / "docs" / "notes" / "upstream.md").read_text(encoding="utf-8")
    commit = re.search(r"^- commit: ([0-9a-f]{40})$", doc, re.MULTILINE)
    assert commit, "docs/notes/upstream.md 缺少 `- commit:` 行"
    surface = GATE.load_surface()
    assert surface["pin"]["commit"] == commit.group(1)
    assert surface["pin"]["tag"] == "v4.0.3"


def test_every_category_is_above_the_threshold() -> None:
    result = GATE.measure(GATE.load_surface())
    assert result["overall"] >= 0.9
    assert not GATE.failures(result, doc_stale=False), GATE.failures(result, doc_stale=False)
    for row in result["rows"]:
        assert row["coverage"] >= 0.9, (row["kind"], row["coverage"])


def test_every_gap_has_an_issue_home() -> None:
    result = GATE.measure(GATE.load_surface())
    for name in result["gaps"]:
        assert name in GATE.GAPS, name
        issue, reason = GATE.GAPS[name]
        assert re.fullmatch(r"SIL-\d+", issue), (name, issue)
        assert reason.strip()


def test_missing_issue_home_fails_the_gate() -> None:
    """负向对照：没登记归口的缺口必须让门禁红，而不是只少一个百分点。"""
    surface = _surface_with(category="facet", exports=["facet_wrap", "facet_sf_unknown"])
    result = GATE.measure(surface)
    problems = GATE.failures(result, doc_stale=False)
    assert any("facet_sf_unknown" in problem and "归口" in problem for problem in problems)


def test_below_threshold_fails_the_gate() -> None:
    surface = _surface_with(category="facet", exports=["facet_wrap", "facet_nope"])
    result = GATE.measure(surface)
    assert result["rows"][0]["coverage"] == pytest.approx(0.5)
    assert any("facet" in problem for problem in GATE.failures(result, doc_stale=False))


def test_stale_doc_fails_the_check() -> None:
    surface = _surface_with(category="facet", exports=["facet_wrap"])
    result = GATE.measure(surface)
    assert GATE.failures(result, doc_stale=True) == [
        f"{GATE.DOC.relative_to(GATE.ROOT)} 不是最新的（`pixi run api:coverage`）"
    ]


def test_surface_only_exports_are_real_and_called() -> None:
    """只在公开命名空间的导出不是空壳：这里真的调用一遍。"""
    # 全局主题状态：先存旧值，测完还原，避免污染其它用例。
    old = theme_get()
    try:
        returned = plot.theme_set(plot.theme_grey())
        assert returned == old
        assert plot.theme_get() == plot.theme_grey()
        assert isinstance(plot.theme_update(**{"plot.background": None}), Theme)
        assert isinstance(plot.theme_replace(**{"plot.background": None}), Theme)

        sub = plot.theme_sub_axis(text=element_text(size=9))
        assert isinstance(sub, Theme)
        for name in (
            "theme_sub_axis_x",
            "theme_sub_axis_y",
            "theme_sub_axis_top",
            "theme_sub_axis_bottom",
            "theme_sub_axis_left",
            "theme_sub_axis_right",
            "theme_sub_legend",
            "theme_sub_panel",
            "theme_sub_plot",
            "theme_sub_strip",
        ):
            assert isinstance(getattr(plot, name)(), Theme), name
    finally:
        plot.theme_set(old)

    # guide 协议钩子：用真实的 Guide / GuideBuild 调一遍。
    guide = GuideLegend()
    # `guide_train()` 只是 `Guide.train()` 的转发；用一个记录调用的替身断言转发口径。
    calls: list[tuple] = []

    class _Spy(GuideLegend):
        def train(self, build, aesthetic, scale):
            calls.append((build, aesthetic, scale))
            return None

    marker = object()
    assert guide_train(_Spy(), marker, "colour", None) is None
    assert calls == [(marker, "colour", None)]
    merged = guide_merge(GuideLegend(title="a"), GuideLegend(title="b", nrow=2))
    assert merged.title == "b" and merged.nrow == 2
    assert guide_geom(guide, None) is None  # 默认钩子

    assert plot.scale_type((1, 2)) == ("continuous",)
    assert plot.scale_type(("a", "b")) == ("discrete",)


def test_registry_entries_from_the_gate_are_constructible() -> None:
    """新增的两个 guide 名字必须能真的构造出来，不是只占个名字。"""
    assert "colorbar" in registry.registered("guide")
    assert "custom" in registry.registered("guide")
    bar = guide_from_component(registry.construct("guide", "colorbar", nbin=10))
    assert bar.kind == "colourbar"
    assert registry.construct("guide", "custom").name == "custom"


def test_committed_snapshot_is_canonical_json() -> None:
    text = GATE.DATA.read_text(encoding="utf-8")
    assert json.loads(text) == GATE.load_surface()
    assert text.endswith("\n")

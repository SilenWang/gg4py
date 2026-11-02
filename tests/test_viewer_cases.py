"""M1-16：`pixi run viewer:cases` 的端到端契约（真 Chromium + resvg）。

两条真实案例足够守住接线：`geom-col-basic`（矩形）与 `geom-text-cjk`（文字 +
受管字体轮廓）。全量 61 条在 CI 的 `viewer cases (sample)` job 里按族抽样跑。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
VIEWER = REPO / "web" / "viewer"
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools" / "viewer"))


def _module():
    path = REPO / "tools" / "viewer" / "cases.py"
    spec = importlib.util.spec_from_file_location("gg4py_viewer_cases", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_sample_rotates_across_families() -> None:
    module = _module()
    cases = [
        SimpleNamespace(name=f"{family}-{index}", family=family)
        for family in ("geom-point", "geom-bar", "geom-text", "facet")
        for index in range(3)
    ]
    selected = module._select_sample(cases, 8)
    assert len(selected) == 8
    assert len({case.family for case in selected}) == 4
    # 每个族先出一条，再轮到第二轮：前 4 条正好一族一条。
    assert [case.family for case in selected[:4]] == [
        "facet",
        "geom-bar",
        "geom-point",
        "geom-text",
    ]


def test_viewer_cases_runs_two_real_cases(tmp_path: Path) -> None:
    pytest.importorskip("playwright.sync_api")
    if not (VIEWER / "dist" / "main.js").is_file():
        pytest.fail("web/viewer/dist 不存在：先跑 `pixi run viewer:build`")
    module = _module()
    out = tmp_path / "out"
    gallery = tmp_path / "gallery.html"
    code = module.main(
        [
            "--case",
            "geom-col-basic",
            "--case",
            "geom-text-cjk",
            "--out",
            str(out),
            "--gallery",
            str(gallery),
            "--min-pass",
            "2",
        ]
    )
    if code == 2:
        pytest.skip("没有可用 Chromium（先跑 `pixi run viewer:browsers`）")
    assert code == 0

    payload = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert payload["counts"]["pass"] == 2
    assert payload["counts"]["fail"] == 0
    assert payload["wasm_requests"] == []
    names = {case["case"] for case in payload["cases"]}
    assert names == {"geom-col-basic", "geom-text-cjk"}

    page = gallery.read_text(encoding="utf-8")
    assert "geom-col-basic" in page
    assert "geom-text-cjk" in page
    assert "index.html?scene=gallery/geom-col-basic.ggir.cbor" in page
    assert "零 wasm：是" in (out / "report.md").read_text(encoding="utf-8")

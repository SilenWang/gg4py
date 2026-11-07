"""M1-16：`pixi run viewer:cases` 的端到端契约（真 Chromium + resvg）。

两条真实案例足够守住接线：`geom-col-basic`（矩形）与 `geom-text-cjk`（文字 +
受管字体轮廓）。CI 的 `viewer cases (sample)` job 按「风险组全量 + 族轮转」抽样
（SIL-867：`geom-raster` 全族与 `band` 声明过的 case 不再被抽样漏掉）。
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import urllib.parse
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


def test_sample_always_covers_raster_and_report_band() -> None:
    """SIL-867：12 条轮转名额被大族吃满，风险组必须无条件进样本。

    之前族轮转按族名字母序走，`geom-raster`（第 9 个族）与 `matrix` 族里排最后的
    `matrix-report-*` 永远轮不到：13 条 raster 红与 report 档的容差接线在 CI 里
    完全看不见。
    """
    module = _module()
    cases = (
        [SimpleNamespace(name=f"guide-{index}", family="guide", band=None) for index in range(6)]
        + [
            SimpleNamespace(name=f"upstream-geom-raster-{index}", family="geom-raster", band=None)
            for index in range(3)
        ]
        + [SimpleNamespace(name="matrix-report-facet-polar-grey", family="matrix", band="report")]
    )
    selected = module._select_sample(cases, 2)
    names = [case.name for case in selected]
    assert {"upstream-geom-raster-0", "upstream-geom-raster-1", "upstream-geom-raster-2"} <= set(
        names
    )
    assert "matrix-report-facet-polar-grey" in names
    # 风险组是**额外**的名额：轮转仍然只取 limit 条（4 + 2）。
    assert len(selected) == 6


def test_viewer_cases_runs_two_real_cases(tmp_path: Path) -> None:
    pytest.importorskip("playwright.sync_api")
    if not (VIEWER / "dist" / "main.js").is_file():
        pytest.fail("web/viewer/dist 不存在：先跑 `pixi run viewer:build`")
    module = _module()
    out = tmp_path / "out"
    # gallery.html 按契约放在 `<viewer>/dist/` 下：卡片链 `../index.html`、资产落在
    # `<viewer>/gallery/`（用 tmp 的 viewer 根，不写仓库）。
    viewer = tmp_path / "viewer"
    gallery = viewer / "dist" / "gallery.html"
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
    assert "../index.html?scene=gallery/geom-col-basic.ggir.cbor" in page
    assert "零 wasm：是" in (out / "report.md").read_text(encoding="utf-8")


def test_gallery_card_links_resolve_to_real_files(tmp_path: Path) -> None:
    """卡片链接按 URL 解析后，index.html / scene / 缩略图都真的存在（不是字符串比对）。"""
    module = _module()
    viewer = tmp_path / "viewer"
    gallery = viewer / "dist" / "gallery.html"
    viewer.mkdir(parents=True)
    (viewer / "index.html").write_text("<!doctype html><title>viewer</title>", encoding="utf-8")
    thumb = tmp_path / "thumb.png"
    thumb.write_bytes(b"\x89PNG\r\n\x1a\n")
    ir_file = tmp_path / "geom-col-basic.ggir.cbor"
    ir_file.write_bytes(b"\xa0")
    result = module.Result(
        case="geom-col-basic",
        family="geom-col",
        status=module.PASS,
        elements=3,
        thumbnail=str(thumb),
        ir_path=str(ir_file),
    )
    module.write_gallery([result], gallery, tmp_path / "out", "now")
    page = gallery.read_text(encoding="utf-8")

    hrefs = re.findall(r'<a href="([^"]+)"', page)
    srcs = re.findall(r'<img src="([^"]+)"', page)
    assert len(hrefs) == 1 and len(srcs) == 1
    index_path, _, query = hrefs[0].partition("?")
    # 1) ../index.html 从 dist/ 解析到 viewer 根目录的入口页。
    assert (gallery.parent / index_path).resolve().is_file()
    # 2) scene 参数相对 viewer 根目录（index.html 所在目录）解析 → 真实文件。
    scene = urllib.parse.parse_qs(query)["scene"][0]
    scene_file = (viewer / scene).resolve()
    assert scene_file.is_file()
    assert scene_file.suffixes[-2:] == [".ggir", ".cbor"]
    # 3) 缩略图相对 gallery.html 解析 → 真实文件。
    assert (gallery.parent / srcs[0]).resolve().is_file()


def _gallery_check_module():
    path = REPO / "tools" / "viewer" / "gallery_check.py"
    spec = importlib.util.spec_from_file_location("gg4py_gallery_check", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_gallery_check_requests_every_link_and_matches_cases(tmp_path: Path) -> None:
    """SIL-828：链接逐条走 HTTP（含 viewer 的 scene fetch），卡片与 case 台账对齐。"""
    cases = _module()
    checker = _gallery_check_module()
    viewer = tmp_path / "viewer"
    gallery = viewer / "dist" / "gallery.html"
    viewer.mkdir(parents=True)
    (viewer / "index.html").write_text("<!doctype html><title>viewer</title>", encoding="utf-8")
    thumb = tmp_path / "thumb.png"
    thumb.write_bytes(b"\x89PNG\r\n\x1a\n")
    ir_file = tmp_path / "geom-col-basic.ggir.cbor"
    ir_file.write_bytes(b"\xa0")
    result = cases.Result(
        case="geom-col-basic",
        family="geom-col",
        status=cases.PASS,
        elements=3,
        thumbnail=str(thumb),
        ir_path=str(ir_file),
    )
    cases.write_gallery([result], gallery, tmp_path / "out", "now")

    report = checker.check_gallery(gallery, viewer, 5.0, case_names={"geom-col-basic"})
    assert report.cards == 1
    assert len(report.links) == 3  # href + viewer 随后 fetch 的 scene + 缩略图
    assert [item.url for item in report.links if item.kind == "scene"] == [
        "scene=gallery/geom-col-basic.ggir.cbor"
    ]
    assert report.failed == []
    assert report.missing_cases == [] and report.stale_cards == []

    # 删掉缩略图：HTTP 200 之外还要发现「文件不存在」，并把它报成失败。
    (viewer / "gallery" / "geom-col-basic.png").unlink()
    broken = checker.check_gallery(gallery, viewer, 5.0, case_names={"geom-col-basic"})
    assert len(broken.failed) == 1
    assert broken.failed[0].status == 404
    assert broken.failed[0].url.endswith("geom-col-basic.png")

    # 卡片指向已删掉的 case：链接可能仍 200，但台账对不上。
    stale = checker.check_gallery(gallery, viewer, 5.0, case_names={"other-case"})
    assert stale.stale_cards == ["geom-col-basic"]
    assert stale.missing_cases == ["other-case"]

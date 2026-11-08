"""SIL-893：静态 gallery（`viewer:gallery`）与本地服务（`viewer:serve`）。

验收要求「不装 Playwright / Chromium 也能浏览画廊」，所以这一组测试**不许**碰
Playwright（`pixi run check` 里 `viewer:browsers` 之外还会有没有浏览器的 runner）。
四条断言各自对应一处容易退化的地方：

1. 卡片数 = 合法 case 数，且缩略图是 `docs/cases/<case>/expected.svg` 的逐字节复制；
2. 卡片状态是 `static`，不是 `pass`——静态参考图不能被看成「验证过了」；
3. `gallery:check` 认识 `.svg` 缩略图（两条产线共用同一份卡片契约）；
4. `viewer:serve` 真的把 gallery.html 与 `.ggir.cbor` 发出去（含 content-type）。
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import threading
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load(relative: str, name: str):
    path = REPO / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _copy_case(name: str, root: Path) -> Path:
    source = REPO / "docs" / "cases" / name
    target = root / name
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
    return target


def test_gallery_build_writes_static_cards(tmp_path: Path) -> None:
    gallery_build = _load("tools/viewer/gallery_build.py", "gg4py_gallery_build")

    root = tmp_path / "cases"
    case_dir = _copy_case("coord-equal", root)
    viewer = tmp_path / "viewer"
    (viewer / "dist").mkdir(parents=True)
    # `viewer:build` 的产物：卡片点开后的 viewer 要用它，gallery 生成时只校验存在。
    (viewer / "dist" / "main.js").write_text("export {};\n", encoding="utf-8")
    gallery = viewer / "dist" / "gallery.html"

    code = gallery_build.main(["--root", str(root), "--gallery", str(gallery)])
    assert code == 0

    page = gallery.read_text(encoding="utf-8")
    assert '<article class="card static">' in page
    assert "未做像素验证" in page  # 卡片/说明里明说这不是验证结论
    assert "index.html?scene=gallery/coord-equal.ggir.cbor" in page
    assert page.count("<h2>coord-equal</h2>") == 1

    # 缩略图 = 仓内参考图逐字节复制（不是 Chromium 截图、不是重新光栅化）。
    thumb = viewer / "gallery" / "coord-equal.svg"
    assert thumb.read_bytes() == (case_dir / "expected.svg").read_bytes()
    # IR 非空：viewer 打开卡片时 fetch 的就是它。
    cbor = viewer / "gallery" / "coord-equal.ggir.cbor"
    assert cbor.stat().st_size > 0


def test_gallery_check_accepts_static_thumbnails(tmp_path: Path) -> None:
    """两条产线共用的卡片契约：`gallery:check` 认 `.png` 也认 `.svg` 缩略图。"""
    gallery_build = _load("tools/viewer/gallery_build.py", "gg4py_gallery_build_check")
    checker = _load("tools/viewer/gallery_check.py", "gg4py_gallery_check_static")

    root = tmp_path / "cases"
    _copy_case("coord-equal", root)
    viewer = tmp_path / "viewer"
    (viewer / "dist").mkdir(parents=True)
    (viewer / "dist" / "main.js").write_text("export {};\n", encoding="utf-8")
    (viewer / "index.html").write_text("<!doctype html><title>viewer</title>", encoding="utf-8")
    gallery = viewer / "dist" / "gallery.html"
    assert gallery_build.main(["--root", str(root), "--gallery", str(gallery)]) == 0

    report = checker.check_gallery(gallery, viewer, 5.0, case_names={"coord-equal"})
    assert report.cards == 1
    assert report.failed == []
    assert report.missing_cases == [] and report.stale_cards == []
    # href + viewer 随后 fetch 的 scene + 缩略图：三个真实请求，全部 200。
    assert len([item for item in report.links if item.ok]) == len(report.links) == 3
    assert any(item.url.endswith("coord-equal.svg") for item in report.links)


def test_viewer_serve_serves_gallery_and_cbor(tmp_path: Path) -> None:
    serve = _load("tools/viewer/serve.py", "gg4py_viewer_serve")

    root = tmp_path / "viewer"
    (root / "dist").mkdir(parents=True)
    (root / "gallery").mkdir()
    (root / "index.html").write_text("<!doctype html><title>viewer</title>", encoding="utf-8")
    (root / "dist" / "gallery.html").write_text("<!doctype html><title>g</title>", encoding="utf-8")
    (root / "gallery" / "coord-equal.ggir.cbor").write_bytes(b"\xa0")

    server = serve.make_server("127.0.0.1", 0, root)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        with urllib.request.urlopen(f"{base}/dist/gallery.html", timeout=5) as response:
            assert response.status == 200
            assert b"<title>g</title>" in response.read()
        with urllib.request.urlopen(f"{base}/gallery/coord-equal.ggir.cbor", timeout=5) as response:
            assert response.status == 200
            # 容器里的 mimetypes 不认识 .cbor；服务端要显式给类型。
            assert response.headers.get_content_type() == "application/cbor"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

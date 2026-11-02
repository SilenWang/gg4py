"""M1-13：浏览器查看器（IR → DOM SVG）的端到端契约。

真 Chromium（Playwright）打开 `web/viewer/index.html`，加载一张 2×2 分面 + 图例
的 `.ggir.cbor`，断言四件事：

1. **渲染完整**：SVG 里 `<rect>` / `<path>` / `<text>` 的数量与 IR 图元行数（这张
   图上等于节点数）逐一对上；
2. **图例开关**：点图例 key → 那一组节点带上 `data-hidden="true"` 并真的不可见，
   再点回来恢复；
3. **hover**：指到面板里的点上 → tooltip 出现，文本含 geom 层名与数据行号；
4. **零 wasm**：整页没有 `.wasm` 请求。

外加一条解码侧契约：字段坏掉的 IR 要在页面上报错，并指出节点 id。

浏览器不在时 `pytest.skip`（本机先跑 `pixi run viewer:browsers`；CI 由
`pixi run check` 装好）。页面走 `http.server`：`file://` 下浏览器会拦 ES module。
"""

from __future__ import annotations

import functools
import http.server
import json
import sys
import threading
import time
from collections import Counter
from pathlib import Path

import cbor2
import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
VIEWER = REPO / "web" / "viewer"
sys.path.insert(0, str(REPO / "tools" / "viewer"))
sys.path.insert(0, str(REPO / "tools" / "cases"))

import matrix as case_matrix
import playwright_env
from facet_legend import facet_legend_scene

from ggcore import ir
from ggcore.plotspec import build_scene, load_plot
from ggdiff.image import load_image
from ggdiff.raster import rasterize_svg
from ggskia import device_for
from ggskia.text import ShaperMetrics

# 浏览器目录、LD_LIBRARY_PATH、fontconfig（见 tools/viewer/playwright_env.py）。
playwright_env.configure()

sync_api = pytest.importorskip("playwright.sync_api")

#: IR kind → 查看器产出的 SVG 标签（`web/viewer/src/render.ts` 的映射）。
TAG_BY_KIND = {
    "rect": "rect",
    "circle": "circle",
    "points": "path",
    "segments": "path",
    "lines": "path",
    "polyline": "path",
    "polygon": "path",
    "path": "path",
    "xspline": "path",
    "bezier": "path",
    "curve": "path",
    "text": "text",
    "raster": "image",
}

#: 每行出一个元素的 kind：其余点 / 折线 / 曲线型原语一个节点一个元素
#: （`points` 的 10k 个字符合成一条 `<path>`，`id` 分组折在同一个 `d` 里）。
PER_ROW = frozenset({"rect", "circle", "text", "raster"})


def node_rows(node: ir.Node) -> int:
    """一个节点带几行几何（text 看 texts，其余看第一个缓冲）。"""
    if node.kind.value == "text":
        return len(node.texts)
    for buf in node.bufs.values():
        return int(buf.shape[0])
    return 0


def expected_tags(scene: ir.Scene) -> Counter[str]:
    counts: Counter[str] = Counter()
    for node in ir.walk(scene.root):
        tag = TAG_BY_KIND.get(node.kind.value)
        if tag is not None:
            counts[tag] += node_rows(node) if node.kind.value in PER_ROW else 1
    return counts


def node_counts(scene: ir.Scene, *kinds: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for node in ir.walk(scene.root):
        if node.kind.value in kinds:
            counts[node.kind.value] += 1
    return counts


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        del format, args


@pytest.fixture(scope="module")
def viewer_url() -> str:
    handler = functools.partial(_QuietHandler, directory=str(VIEWER))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


@pytest.fixture(scope="module")
def session(viewer_url: str):
    if not (VIEWER / "dist" / "main.js").is_file():
        pytest.fail("web/viewer/dist 不存在：先跑 `pixi run viewer:build`")
    requests: list[str] = []
    playwright = sync_api.sync_playwright().start()
    try:
        browser = playwright.chromium.launch()
    except sync_api.Error as error:  # pragma: no cover - 只在没装浏览器时命中
        playwright.stop()
        pytest.skip(f"没有可用 Chromium（先跑 `pixi run viewer:browsers`）：{error}")
    page = browser.new_page()
    page.on("request", lambda request: requests.append(request.url))
    page.goto(f"{viewer_url}/index.html")
    page.wait_for_selector("#file")
    try:
        yield page, requests
    finally:
        browser.close()
        playwright.stop()


@pytest.fixture(scope="module")
def scene() -> ir.Scene:
    return facet_legend_scene()


@pytest.fixture(scope="module")
def scene_file(scene: ir.Scene, tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("viewer") / "facet-legend.ggir.cbor"
    path.write_bytes(ir.encode(scene))
    return path


def load_scene(page, path: Path) -> str:
    page.set_input_files("#file", str(path))
    page.wait_for_selector("#status[data-state='ok']", timeout=15_000)
    return page.inner_text("#status")


def svg_tags(page) -> Counter[str]:
    tags = page.eval_on_selector_all(
        "svg.gg-svg [data-row]", "elements => elements.map(e => e.localName)"
    )
    return Counter(tags)


def test_ir_fixture_has_the_expected_structure(scene: ir.Scene) -> None:
    """夹具本身：4 个面板 + 3 个图例 key（否则后面的断言测不到东西）。"""
    names = [
        node.params["name"]
        for node in ir.walk(scene.root)
        if node.kind.value == "viewport" and node.params["name"]
    ]
    panels = {name for name in names if name.startswith("panel-")}
    keys = {name for name in names if name.endswith(("-key-0", "-key-1", "-key-2"))}
    assert panels == {"panel-1", "panel-2", "panel-3", "panel-4"}
    assert len(keys) == 3


def test_viewer_renders_every_ir_primitive(session, scene: ir.Scene, scene_file: Path) -> None:
    page, _ = session
    status = load_scene(page, scene_file)
    assert "个 IR 节点" in status

    actual = svg_tags(page)
    expected = expected_tags(scene)
    assert actual == expected, f"数量对不上：SVG={dict(actual)} IR={dict(expected)}"

    # 这张图上每个节点只有一行，所以「元素数 == IR 节点数」逐类成立。
    counts = node_counts(scene, "rect", "text", "points", "segments")
    assert actual["rect"] == counts["rect"]
    assert actual["text"] == counts["text"]
    assert actual["path"] == counts["points"] + counts["segments"]

    state = page.evaluate("() => window.ggViewer.state()")
    assert state["leaves"] == sum(expected.values())
    assert state["legends"] == 3


def test_legend_key_toggles_its_node_group(session, scene_file: Path) -> None:
    page, _ = session
    load_scene(page, scene_file)
    key = page.locator('[data-legend-key="guide-0-key-0"]')
    assert key.count() == 1
    glyph = key.locator("[data-row]")
    assert glyph.count() >= 1
    assert glyph.first.is_visible()

    key.click()
    assert key.get_attribute("data-hidden") == "true"
    assert glyph.first.get_attribute("data-hidden") == "true"
    assert not glyph.first.is_visible()
    # 同一个 guide 里与这个 key 同一行的标签也一起隐藏（IR 没有 key→label 的归属字段）。
    hidden_texts = page.eval_on_selector_all(
        "svg.gg-svg text[data-hidden='true']", "elements => elements.map(e => e.textContent)"
    )
    assert hidden_texts == ["a"]

    key.click()
    assert key.get_attribute("data-hidden") == "false"
    assert glyph.first.is_visible()


def test_hover_shows_geom_layer_and_data_row(session, scene_file: Path) -> None:
    page, _ = session
    load_scene(page, scene_file)
    point = page.locator('[data-kind="points"][data-vp="panel-1"]').first
    assert point.count() == 1
    point.hover()
    tooltip = page.locator("#tooltip")
    tooltip.wait_for(state="visible")
    text = tooltip.inner_text()
    assert "panel-1" in text
    assert "point 层" in text  # geom 层名（IR v0 没层名字段，按图元推断）
    assert "数据行 1/" in text


def ten_thousand_point_scene() -> ir.Scene:
    """一个 `points` 节点、10000 行：验证 bulk 缓冲在 DOM 里仍是 1 个元素。"""
    count = 10_000
    x = np.linspace(10.0, 310.0, count)
    y = 120.0 + 80.0 * np.sin(np.linspace(0.0, 20.0, count))
    node = ir.Node(
        ir.NodeKind.POINTS,
        ir.Gpar(col=(30, 30, 30, 255)),
        params={"pch": 19, "size": 2.0},
        bufs={"points": ir.f32(np.column_stack([x, y]))},
    )
    root = ir.Node(
        ir.NodeKind.VIEWPORT,
        params={"name": "panel-1", "clip": False},
        children=(node,),
    )
    return ir.Scene(root=root, size=(320.0, 240.0))


def test_10k_points_render_as_one_path(session, tmp_path: Path) -> None:
    """10k 行 points → 1 个 `<path>`（不是 10000 个），DOM 总数保持两位数。"""
    page, _ = session
    path = tmp_path / "10k-points.ggir.cbor"
    path.write_bytes(ir.encode(ten_thousand_point_scene()))

    started = time.perf_counter()
    load_scene(page, path)
    elapsed_ms = (time.perf_counter() - started) * 1000

    elements = page.locator('svg.gg-svg [data-kind="points"]').count()
    assert elements == 1
    # 整页 DOM（不是只看 SVG 内）：SIL-710 建议 2 —— bulk 口径要连页壳一起数。
    dom = page.evaluate("() => document.querySelectorAll('*').length")
    assert dom < 100

    element = page.locator('svg.gg-svg path[data-kind="points"]')
    assert element.get_attribute("data-row") == "0"
    assert element.get_attribute("data-rows") == "0-9999"
    subpaths = element.evaluate("el => (el.getAttribute('d').match(/M/g) || []).length")
    assert subpaths == 10_000

    # hover 跟着到节点粒度：显示整段行范围，而不是假装命中第 1 行。
    element.dispatch_event("mouseover", {"bubbles": True, "clientX": 100, "clientY": 100})
    tooltip = page.locator("#tooltip")
    tooltip.wait_for(state="visible")
    assert "数据行 1–10000" in tooltip.inner_text()
    print(f"10k points: 图元={elements} DOM={dom} 子路径={subpaths} 加载={elapsed_ms:.0f}ms")


def test_page_never_requests_wasm(session) -> None:
    _, requests = session
    assert requests, "页面没发出任何请求？"
    assert [url for url in requests if ".wasm" in url] == []


def nested_clip_scene() -> ir.Scene:
    """两层嵌套视口：祖先有非 identity 变换，`clip_rect` 仍然是页面绝对坐标。"""
    inner = ir.Node(
        ir.NodeKind.VIEWPORT,
        params={"name": "inner", "clip": True, "transform": (0.5, 0.0, 0.0, 0.5, 10.0, 20.0)},
        bufs={"clip_rect": ir.f32([[100.0, 50.0, 300.0, 250.0]])},
        children=(
            ir.Node(
                ir.NodeKind.RECT,
                ir.Gpar(fill=(200, 30, 30, 255)),
                bufs={"rect": ir.f32([[0.0, 0.0, 100.0, 100.0]])},
            ),
        ),
    )
    outer = ir.Node(
        ir.NodeKind.VIEWPORT,
        params={"name": "outer", "clip": True, "transform": (1.0, 0.0, 0.0, 1.0, 10.0, 20.0)},
        bufs={"clip_rect": ir.f32([[10.0, 20.0, 210.0, 220.0]])},
        children=(inner,),
    )
    root = ir.Node(
        ir.NodeKind.VIEWPORT,
        params={"name": "page", "clip": False},
        children=(outer,),
    )
    return ir.Scene(root=root, size=(320.0, 240.0))


def test_viewport_clip_rect_is_page_absolute(session, tmp_path: Path) -> None:
    """`clip_rect` 不跟 `transform` 走（`docs/notes/ir.md` §4）：嵌套时也不乘祖先变换。"""
    page, _ = session
    path = tmp_path / "nested-clip.ggir.cbor"
    path.write_bytes(ir.encode(nested_clip_scene()))
    load_scene(page, path)
    got = page.evaluate(
        """() => Array.from(document.querySelectorAll("g.ir-clip-frame")).map(frame => {
              const id = frame.getAttribute("clip-path").slice(5, -1);
              const rect = document.getElementById(id).querySelector("rect");
              const x = Number(rect.getAttribute("x"));
              const y = Number(rect.getAttribute("y"));
              const w = Number(rect.getAttribute("width"));
              const h = Number(rect.getAttribute("height"));
              return [x, y, x + w, y + h];
            })"""
    )
    assert sorted(got) == [[10, 20, 210, 220], [100, 50, 300, 250]]


def test_broken_ir_reports_the_node_id(session, scene: ir.Scene, tmp_path: Path) -> None:
    page, _ = session
    envelope = cbor2.loads(ir.encode(scene))
    broken_id = _drop_text_size(envelope["scene"]["root"], "0")
    assert broken_id is not None
    path = tmp_path / "broken.ggir.cbor"
    path.write_bytes(cbor2.dumps(envelope, canonical=True))

    page.set_input_files("#file", str(path))
    page.wait_for_selector("#status[data-state='error']", timeout=15_000)
    message = page.inner_text("#status")
    assert f"节点 {broken_id}" in message
    assert "size" in message


def _drop_text_size(node: dict, path: str) -> str | None:
    """删掉第一个 text 节点的 `size` 参数，返回它的节点 id。"""
    if node["kind"] == "text":
        del node["params"]["size"]
        return path
    for index, child in enumerate(node.get("children", [])):
        found = _drop_text_size(child, f"{path}/{index}")
        if found is not None:
            return found
    return None


# ---------------------------------------------------------------------------
# M1-16：真实 case 覆盖、alpha 叠加、批量 runner
# ---------------------------------------------------------------------------

CASES = REPO / "docs" / "cases"


def _case_kinds() -> dict[str, str]:
    """61 条三文件 case 里出现的 IR kind → 第一张用到它的 case 名。"""
    first: dict[str, str] = {}
    metrics = ShaperMetrics()
    for case in case_matrix.discover(CASES):
        if not case.valid:
            continue
        scene = build_scene(load_plot(case.directory), metrics=metrics)
        for node in ir.walk(scene.root):
            first.setdefault(node.kind.value, case.name)
    return first


CASE_KINDS = _case_kinds()


def test_case_corpus_is_wide_enough() -> None:
    """案例库本身：至少要有这些 kind，否则下面的参数化会悄悄少测。"""
    assert {
        "viewport",
        "rect",
        "points",
        "text",
        "polygon",
        "polyline",
        "segments",
        "curve",
    } <= set(CASE_KINDS), f"案例库 kind 覆盖变窄：{sorted(CASE_KINDS)}"


@pytest.mark.parametrize("kind,case", sorted(CASE_KINDS.items()))
def test_real_case_renders_every_ir_kind(session, tmp_path: Path, kind: str, case: str) -> None:
    """每种 IR kind 至少有一张**真实 case** 能被查看器加载并产出对应元素。

    这里不手工构造 IR：场景来自 `docs/cases/<case>/plot.py` 的 `build()`，
    走与桌面同一套 `ggcore.plotspec` 管线。
    """
    page, _ = session
    scene = build_scene(load_plot(CASES / case), metrics=ShaperMetrics())
    path = tmp_path / f"{case}.ggir.cbor"
    path.write_bytes(ir.encode(scene))
    load_scene(page, path)

    elements = page.eval_on_selector_all(
        f'svg.gg-svg [data-kind="{kind}"]', "elements => elements.map(e => e.localName)"
    )
    assert elements, f"{case} 的 IR 有 {kind} 节点，但页面上没有对应元素"
    tags = set(elements)
    if kind in TAG_BY_KIND:
        assert tags <= {TAG_BY_KIND[kind]}, f"{kind} 落到了 {tags}"
    else:  # 容器：viewport / gtree / null / zero
        assert tags <= {"g", "clipPath"}, f"{kind} 落到了 {tags}"


def alpha_overlap_scene(alpha: int = 128) -> ir.Scene:
    """一个 points 节点里两个**完全重叠**的半透明点（pch 19）。"""
    node = ir.Node(
        ir.NodeKind.POINTS,
        ir.Gpar(col=(228, 87, 86, alpha), lwd=0.0),
        params={"pch": 19, "size": 12.0},
        bufs={"points": ir.f32([[144.0, 108.0], [144.0, 108.0]])},
    )
    root = ir.Node(
        ir.NodeKind.VIEWPORT,
        params={"name": "panel-1", "clip": False},
        children=(node,),
    )
    return ir.Scene(root=root, size=(288.0, 216.0))


def _center_pixel(svg: str | Path, out: Path, *, zoom: float | None) -> np.ndarray:
    rasterize_svg(svg, out, dpi=144, background="#ffffff", zoom=zoom)
    image = load_image(out)
    return image[image.shape[0] // 2, image.shape[1] // 2]


def test_alpha_points_overlap_matches_desktop(session, tmp_path: Path) -> None:
    """两个重叠的半透明点：viewer 中心像素与桌面同 IR 差 ≤ 4/255（修前差 40+）。

    整节点合成一个 `<path>` 时，半透明重叠只算一层；`gpar.alpha < 1` 或颜色
    alpha < 255 时查看器回退成逐行 `<path>`，每个点单独合成。
    """
    page, _ = session
    scene = alpha_overlap_scene()
    path = tmp_path / "alpha-overlap.ggir.cbor"
    path.write_bytes(ir.encode(scene))
    load_scene(page, path)

    elements = page.locator('svg.gg-svg path[data-kind="points"]')
    assert elements.count() == 2, "半透明点必须逐行一个元素，否则重叠处只合成一次"
    assert elements.first.get_attribute("data-rows") is None

    viewer_svg = tmp_path / "alpha-viewer.svg"
    viewer_svg.write_text(
        page.evaluate("() => document.querySelector('svg.gg-svg').outerHTML"), encoding="utf-8"
    )
    desktop_svg = tmp_path / "alpha-desktop.svg"
    desktop_svg.write_bytes(device_for("svg", *scene.size).render(scene))

    viewer = _center_pixel(viewer_svg, tmp_path / "alpha-viewer.png", zoom=None)
    desktop = _center_pixel(desktop_svg, tmp_path / "alpha-desktop.png", zoom=2)
    difference = int(np.abs(viewer.astype(np.int16) - desktop.astype(np.int16)).max())
    print(
        f"alpha overlap center: viewer={viewer.tolist()} desktop={desktop.tolist()} Δ={difference}"
    )
    assert difference <= 4, f"viewer={viewer.tolist()} desktop={desktop.tolist()}"


def test_opaque_points_stay_one_element(session, tmp_path: Path) -> None:
    """alpha = 1 的节点仍合成单个 `<path>`（bulk 口径不能因为修 alpha 丢掉）。"""
    page, _ = session
    scene = alpha_overlap_scene(alpha=255)
    path = tmp_path / "alpha-opaque.ggir.cbor"
    path.write_bytes(ir.encode(scene))
    load_scene(page, path)
    assert page.locator('svg.gg-svg path[data-kind="points"]').count() == 1


def test_viewer_cases_runner_smoke(tmp_path: Path) -> None:
    """批量 runner 冒烟：分面+图例 / raster / 旋转文字 三条代表 case 全绿。"""
    import os
    import subprocess

    out = tmp_path / "cases"
    names = "facet-wrap-2x2,grob-raster,grob-text-rot"
    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "tools" / "viewer" / "cases.py"),
            "--only",
            names,
            "--out",
            str(out),
        ],
        cwd=REPO,
        env={**os.environ, "PYTHONPATH": "src"},
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    payload = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert {record["name"] for record in payload["cases"]} == set(names.split(","))
    assert all(record["status"] == "pass" for record in payload["cases"])
    assert {record["group"] for record in payload["cases"]} == {"case", "grob"}
    # 三条代表 case 的产物都在：SVG 导出、浏览器截图、桌面 SVG、报告。
    for name in names.split(","):
        assert (out / "svg" / f"{name}.svg").is_file()
        assert (out / "png" / f"{name}.browser.png").is_file()
        assert (out / "desktop" / f"{name}.svg").is_file()
    assert (out / "report.md").is_file()

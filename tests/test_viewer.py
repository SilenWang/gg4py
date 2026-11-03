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
import importlib.util
import re
import shutil
import sys
import threading
import time
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.request import urlopen

import cbor2
import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
VIEWER = REPO / "web" / "viewer"
sys.path.insert(0, str(REPO / "tools" / "viewer"))

import playwright_env
from facet_legend import facet_legend_scene

from ggcore import ir
from ggcore.geom.scene import scene_from_plot
from ggcore.plot import aes, geom_point, ggplot
from ggio.frame import to_column_table

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
    dom = page.evaluate("() => document.querySelectorAll('svg.gg-svg *').length")
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


# ---------------------------------------------------------------------------
# pch 0..25：查看器的路径顶点 / 包围盒与 `ggskia.pch.symbol()` 逐项一致。
# `triangleOps()` 曾把 pch 11 专用的 `0.5 * (TRC2 + TRC0)` 用在 2/6/14/17/24/25
# 上（SIL-718）；这组断言让那种回退直接变红。
# ---------------------------------------------------------------------------

PCH_SIZE = 20.0
PCH_TOLERANCE = 0.01
PCH_SCENE_SIZE = (900.0, 620.0)


def pch_centres() -> list[tuple[float, float]]:
    """26 个 pch 的锚点：7 列 4 行，互不重叠。"""
    return [(120.0 + 120.0 * (pch % 7), 80.0 + 130.0 * (pch // 7)) for pch in range(26)]


def pch_scene() -> ir.Scene:
    """一个 `points` 节点对一个 pch，各一行；节点 id 是 `0/<pch>`。"""
    nodes = tuple(
        ir.Node(
            ir.NodeKind.POINTS,
            ir.Gpar(col=(30, 30, 30, 255)),
            params={"pch": pch, "size": PCH_SIZE},
            bufs={"points": ir.f32([[x, y]])},
        )
        for pch, (x, y) in enumerate(pch_centres())
    )
    root = ir.Node(ir.NodeKind.VIEWPORT, params={"name": "panel-1", "clip": False}, children=nodes)
    return ir.Scene(root=root, size=PCH_SCENE_SIZE)


#: `glyphPath()` 只写绝对 `M` / `L` / `C` / `Z`（`d` 里没有隐式重复命令）。
_PATH_TOKEN = re.compile(r"[MLCZ]|[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")


def viewer_path_vertices(d: str) -> tuple[list[tuple[float, float]], bool]:
    """把查看器的 `d` 拆成顶点；有 `C` 时返回 `curved=True`（圆只比包围盒）。"""
    tokens = _PATH_TOKEN.findall(d)
    points: list[tuple[float, float]] = []
    curved = False
    index = 0
    while index < len(tokens):
        command = tokens[index]
        assert command in {"M", "L", "C", "Z"}, f"未知路径命令 {command!r} in {d!r}"
        index += 1
        if command == "Z":
            continue
        count = 6 if command == "C" else 2
        values = [float(token) for token in tokens[index : index + count]]
        assert len(values) == count, f"{command} 参数不足 in {d!r}"
        index += count
        if command == "C":
            curved = True
        else:
            points.append((values[0], values[1]))
    return points, curved


def skia_symbol_geometry(
    pch: int, size: float
) -> tuple[list[tuple[float, float]], tuple[float, float, float, float], bool]:
    """`ggskia.pch.symbol()` 的顶点 / 紧包围盒；圆的 conic 不算顶点。"""
    import skia

    from ggskia.pch import symbol

    glyph = symbol(pch, size)
    assert glyph is not None, f"pch={pch} 没有几何定义"
    path = glyph.path
    curved = any(
        verb in (skia.Path.Verb.kConic_Verb, skia.Path.Verb.kQuad_Verb, skia.Path.Verb.kCubic_Verb)
        for verb in path.getVerbs()
    )
    bounds = path.computeTightBounds()
    points = [(point.x(), point.y()) for point in path.getPoints()]
    return points, (bounds.left(), bounds.top(), bounds.right(), bounds.bottom()), curved


def assert_glyph_matches(
    pch: int,
    size: float,
    d: str,
    box: tuple[float, float, float, float],
    *,
    origin: tuple[float, float] | None = None,
    label: str,
) -> None:
    """查看器的路径顶点与包围盒对 `ggskia.pch.symbol()` 逐点比对（≤0.01pt）。"""
    expected_points, bounds, curved = skia_symbol_geometry(pch, size)
    got_points, got_curved = viewer_path_vertices(d)
    assert got_curved == curved, f"{label}：曲线/折线类型不一致（{d}）"

    box_x, box_y, box_w, box_h = box
    x0, y0, x1, y1 = bounds
    if origin is None:
        # 真实管线里的视口只做平移；按包围盒中心对齐即可逐点比。
        origin_x = box_x + box_w / 2.0 - (x0 + x1) / 2.0
        origin_y = box_y + box_h / 2.0 - (y0 + y1) / 2.0
    else:
        origin_x, origin_y = origin

    if not curved:
        expected = sorted((origin_x + x, origin_y + y) for x, y in expected_points)
        assert len(got_points) == len(expected), (
            f"{label}：顶点数 {len(got_points)} != {len(expected)}（{d}）"
        )
        for (want_x, want_y), (got_x, got_y) in zip(expected, sorted(got_points), strict=True):
            assert abs(want_x - got_x) <= PCH_TOLERANCE, f"{label}：x {got_x} != {want_x}（{d}）"
            assert abs(want_y - got_y) <= PCH_TOLERANCE, f"{label}：y {got_y} != {want_y}（{d}）"

    want_box = (origin_x + x0, origin_y + y0, x1 - x0, y1 - y0)
    for name, got, want in zip("xywh", (box_x, box_y, box_w, box_h), want_box, strict=True):
        assert abs(got - want) <= PCH_TOLERANCE, f"{label}：包围盒 {name} {got} != {want}（{d}）"


def rendered_glyphs(page, node_ids: list[str]) -> list[dict[str, object] | None]:
    return page.evaluate(
        """(ids) => ids.map(id => {
              const el = document.querySelector(`[data-kind="points"][data-node="${id}"]`);
              if (el === null) return null;
              const box = el.getBBox();
              return {
                d: el.getAttribute("d") || "",
                box: [box.x, box.y, box.width, box.height],
                vp: el.getAttribute("data-vp"),
                visible: el.getBoundingClientRect().width > 0,
              };
            })""",
        node_ids,
    )


def test_every_pch_matches_ggskia_geometry(session, tmp_path: Path) -> None:
    """pch 0..25 逐项对拍：三角形的 bug 会让 2/6/14/17/24/25 红。"""
    page, _ = session
    path = tmp_path / "pch-0-25.ggir.cbor"
    path.write_bytes(ir.encode(pch_scene()))
    load_scene(page, path)

    node_ids = [f"0/{pch}" for pch in range(26)]
    glyphs = rendered_glyphs(page, node_ids)
    for pch, (x, y), glyph in zip(range(26), pch_centres(), glyphs, strict=True):
        assert glyph is not None, f"pch={pch} 没渲染出来"
        assert_glyph_matches(
            pch,
            PCH_SIZE,
            str(glyph["d"]),
            tuple(glyph["box"]),
            origin=(x, y),
            label=f"pch={pch}",
        )


def triangle_legend_scene() -> ir.Scene:
    """真管线：`shape` 映射到两水平（缺省 16 圆 / 17 三角），带 shape 图例。"""
    table = to_column_table(
        {
            "x": [0.25, 0.75],
            "y": [0.3, 0.7],
            "g": ["a", "b"],
        }
    )
    plot = ggplot(table, aes(x="x", y="y", shape="g")) + geom_point(size=17 / 2.845276)
    return scene_from_plot(plot, width_in=4.0, height_in=3.0)


def points_node_records(scene: ir.Scene) -> list[tuple[str, ir.Node, str | None]]:
    """`points` 节点的 (DOM 节点 id, IR 节点, 最近的视口名)。"""
    records: list[tuple[str, ir.Node, str | None]] = []

    def walk(node: ir.Node, prefix: str, viewport: str | None) -> None:
        name = viewport
        if node.kind.value == "viewport" and node.params.get("name"):
            name = str(node.params["name"])
        if node.kind.value == "points":
            records.append((prefix, node, name))
        for index, child in enumerate(node.children):
            walk(child, f"{prefix}/{index}", name)

    walk(scene.root, "0", None)
    return records


def test_triangle_pch_scatter_and_legend_render_in_gallery(session, tmp_path: Path) -> None:
    """真管线（不是合成 IR）出图：三角形散点与图例 key 都按 ggskia 几何落页面。"""
    page, _ = session
    scene = triangle_legend_scene()
    records = points_node_records(scene)
    panel = [record for record in records if record[2] == "panel-1"]
    keys = [record for record in records if (record[2] or "").startswith("guide-0-key-")]

    # 夹具本身：两水平 → 16 圆 / 17 三角；每个节点一行，图例每个 key 一个节点。
    panel_pch = {int(node.params["pch"]) for _, node, _ in panel}
    key_pch = {int(node.params["pch"]) for _, node, _ in keys}
    assert 17 in panel_pch, f"散点没映射到 pch 17：{panel_pch}"
    assert 17 in key_pch, f"图例没映射到 pch 17：{key_pch}"
    assert all(node.bufs["points"].shape[0] == 1 for _, node, _ in records)

    path = tmp_path / "triangle-legend.ggir.cbor"
    path.write_bytes(ir.encode(scene))
    load_scene(page, path)

    node_ids = [node_id for node_id, _, _ in records]
    glyphs = rendered_glyphs(page, node_ids)
    triangles = 0
    for (node_id, node, viewport), glyph in zip(records, glyphs, strict=True):
        pch = int(node.params["pch"])
        size = float(node.params["size"])
        assert glyph is not None, f"{viewport}/{node_id}（pch={pch}）没渲染出来"
        assert glyph["visible"], f"{viewport}/{node_id}（pch={pch}）在页面上不可见"
        assert_glyph_matches(
            pch,
            size,
            str(glyph["d"]),
            tuple(glyph["box"]),
            label=f"{viewport}/{node_id}（pch={pch}）",
        )
        if pch == 17:
            triangles += 1
    # 一层面板 + 一个图例 key，至少两条三角形路径。
    assert triangles >= 2, "三角形散点/图例没有同时出现在 gallery 页面里"


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


def raster_scene() -> ir.Scene:
    """一个 clip + raster blob：覆盖查看器的 `<image>` 与 data URL 路径。"""
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), (220, 30, 30)).save(buffer, format="PNG")
    blobs, blob_id = ir.BlobTable.empty().add(buffer.getvalue(), "image/png")
    clipped = ir.Node(
        ir.NodeKind.CLIP,
        params={"name": "clip", "rule": "winding"},
        bufs={"rect": ir.f32([[10.0, 10.0, 50.0, 50.0]])},
        children=(
            ir.Node(
                ir.NodeKind.RASTER,
                params={"blob": blob_id, "width": 2, "height": 2, "interpolate": False},
                bufs={"rect": ir.f32([[0.0, 0.0, 80.0, 80.0]])},
            ),
        ),
    )
    root = ir.Node(
        ir.NodeKind.VIEWPORT,
        params={"name": "page", "clip": False},
        children=(clipped,),
    )
    return ir.Scene(root=root, size=(120.0, 120.0), blobs=blobs)


def test_raster_blob_is_embedded_as_data_url(session, tmp_path: Path) -> None:
    page, _ = session
    path = tmp_path / "raster.ggir.cbor"
    path.write_bytes(ir.encode(raster_scene()))
    load_scene(page, path)
    image = page.locator('svg.gg-svg image[data-kind="raster"]')
    assert image.count() == 1
    href = image.get_attribute("href") or image.get_attribute("xlink:href")
    assert href is not None and href.startswith("data:image/png;base64,")
    assert page.locator("svg.gg-svg clipPath rect").count() >= 1


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


def _viewer_cases_module():
    """加载 `tools/viewer/cases.py`（gallery 生成器在脚本里，不是包）。"""
    path = REPO / "tools" / "viewer" / "cases.py"
    spec = importlib.util.spec_from_file_location("gg4py_gallery_links", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _CardLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []
        self.srcs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del tag
        values = dict(attrs)
        if values.get("href"):
            self.hrefs.append(str(values["href"]))
        if values.get("src"):
            self.srcs.append(str(values["src"]))


def _http_status(url: str) -> int | str:
    try:
        with urlopen(url, timeout=5) as response:
            return int(response.status)
    except HTTPError as error:
        return int(error.code)
    except URLError as error:  # pragma: no cover - 夹具服务器没起来才会命中
        return f"{type(error).__name__}: {error}"


def test_gallery_card_links_all_return_200(tmp_path: Path) -> None:
    """SIL-722：gallery.html 与 index.html 同目录，每张卡片的链接都必须能打开。

    gallery 之前写在 `dist/` 里，`index.html?scene=...` 被解析成 `dist/index.html`
    （404）。这里按真实目录结构（viewer 根 = index.html 所在目录）生成一张 2 卡的
    gallery，再逐链接 GET：卡片页、scene IR、缩略图都必须是 200。
    """
    module = _viewer_cases_module()
    import io

    from PIL import Image

    root = tmp_path / "viewer"
    (root / "dist").mkdir(parents=True)
    shutil.copyfile(VIEWER / "index.html", root / "index.html")
    (root / "dist" / "main.js").write_text("// stub：本测试只验证静态路径\n", encoding="utf-8")

    source = tmp_path / "source"
    source.mkdir()
    buffer = io.BytesIO()
    Image.new("RGB", (4, 3), (240, 240, 240)).save(buffer, format="PNG")
    results = []
    for name in ("geom-col-basic", "geom-text-cjk"):
        thumbnail = source / f"{name}.png"
        thumbnail.write_bytes(buffer.getvalue())
        ir_file = source / f"{name}.ggir.cbor"
        ir_file.write_bytes(b"\xa0")
        results.append(
            module.Result(
                case=name,
                family="geom-col",
                status=module.PASS,
                elements=3,
                thumbnail=str(thumbnail),
                ir_path=str(ir_file),
            )
        )
    gallery = root / "gallery.html"
    module.write_gallery(results, gallery, tmp_path / "out", now="2026-11-02T00:00:00Z")

    links = _CardLinks()
    links.feed(gallery.read_text(encoding="utf-8"))
    assert len(links.hrefs) == len(results)
    assert len(links.srcs) == len(results)

    handler = functools.partial(_QuietHandler, directory=str(root))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        for href, src in zip(links.hrefs, links.srcs, strict=True):
            card = urljoin(f"{base}/gallery.html", href)
            assert urlsplit(card).path == "/index.html", card
            assert _http_status(card) == 200, card
            scene = parse_qs(urlsplit(card).query)["scene"][0]
            scene_url = urljoin(f"{base}/index.html", scene)
            assert _http_status(scene_url) == 200, scene_url
            thumbnail_url = urljoin(f"{base}/gallery.html", src)
            assert _http_status(thumbnail_url) == 200, thumbnail_url
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)

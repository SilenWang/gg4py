"""M2-9 扩展 API：一个类就能出图，文档示例与浏览器路径都回归。"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, ClassVar

import numpy as np
import pytest

from ggcore import ir, plot, registry
from ggcore.build import build_plot
from ggcore.components import Coord, Theme
from ggcore.coord import CartesianCoord, coord_from_component
from ggcore.data import Column, ColumnTable
from ggcore.layer import Geom, Position
from ggcore.plotspec import build_scene, load_plot
from ggcore.theme import element_rect, resolve_theme
from ggio.frame import to_column_table

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "notes" / "extension.md"
CASE = REPO / "docs" / "cases" / "ext-custom-geom"
VIEWER = REPO / "web" / "viewer"

sys.path.insert(0, str(REPO / "src"))


def _doc_examples() -> list[tuple[str, str]]:
    text = DOC.read_text(encoding="utf-8")
    pattern = re.compile(
        r"<!-- extension-example: ([a-z0-9-]+) -->\s*```python\n(.*?)```",
        re.DOTALL,
    )
    examples = pattern.findall(text)
    assert [name for name, _ in examples] == ["geom", "stat-scale", "guide"]
    return examples


def _purge_new_registrations(before: dict[str, set[str]]) -> None:
    for kind in registry.KINDS:
        for name in registry.registered(kind):
            if name not in before[kind]:
                registry.unregister(kind, name)


@pytest.mark.parametrize(("name", "code"), _doc_examples())
def test_documentation_examples_run(name: str, code: str) -> None:
    """`docs/notes/extension.md` 的三段代码就是 CI 的 doctest。"""
    before = {kind: set(registry.registered(kind)) for kind in registry.KINDS}
    module_name = f"gg4py_extension_doc_{name.replace('-', '_')}"
    module = ModuleType(module_name)
    sys.modules[module_name] = module
    try:
        exec(compile(code, f"docs/notes/extension.md[{name}]", "exec"), module.__dict__)
    finally:
        sys.modules.pop(module_name, None)
        _purge_new_registrations(before)
    assert all(set(registry.registered(kind)) == before[kind] for kind in registry.KINDS)


def _case_plot():
    return load_plot(CASE)


def test_case_scene_has_segments_inside_panel_clip() -> None:
    scene = build_scene(_case_plot())
    nodes = list(ir.walk(scene.root))
    kinds = [node.kind.value for node in nodes]
    assert "segments" in kinds
    # 页面视口 + `panel-clip`：自定义 geom 没有写布局/裁剪代码，clip 由场景装配加。
    assert sum("clip_rect" in node.bufs for node in nodes) >= 2
    segments = next(node for node in nodes if node.kind.value == "segments")
    assert segments.bufs["segments"].shape == (6, 4)


def test_case_renders_through_the_cpython_device() -> None:
    from ggskia import SkiaRasterDevice, SkiaSvgDevice

    scene = build_scene(_case_plot())
    svg = SkiaSvgDevice(*scene.size).render(scene)
    png = SkiaRasterDevice(*scene.size, dpi=72).render(scene)
    assert b"<svg" in svg and len(svg) > 512
    assert png.startswith(b"\x89PNG")
    import skia

    image = skia.Image.MakeFromEncoded(png)
    assert image is not None
    pixels = np.array(image.toarray(), dtype=np.uint8, copy=True)
    ink = int((pixels[:, :, :3] < 250).any(axis=2).sum())
    assert ink > 500


class OffsetGeom(Geom):
    """验证 `setup_data()` 在位置阶段之前运行（派生列进入 `positioned`）。"""

    name = "offset"
    required_aes = ("x", "y")
    default_aes: ClassVar[dict[str, Any]] = {"colour": "black"}

    def setup_data(self, data, params=None):
        del params
        columns = [(name, data.column(name)) for name in data.names]
        return ColumnTable(
            [*columns, ("marker", Column("float", np.full(data.nrows, 7.0)))],
            nrows=data.nrows,
        )

    def draw(self, build, panel, coord, theme, metrics):
        del build, panel, coord, theme, metrics
        raise AssertionError("this test only checks setup_data")


def test_custom_geom_setup_data_runs_before_position() -> None:
    registry.register_geom("offset", OffsetGeom)
    try:
        data = to_column_table({"x": [1.0, 2.0], "y": [3.0, 4.0]})
        layer = plot.ggplot(data, plot.aes(x="x", y="y")) + registry.geom_offset()
        built = build_plot(layer)
        assert "marker" in built.layers[0].positioned
        assert built.layers[0].positioned.column("marker").values.tolist() == [7.0, 7.0]
    finally:
        registry.unregister("geom", "offset")


class ShiftPosition(Position):
    name = "shift"

    def compute_layer(self, data, params=None):
        del params
        return data


class NoopCoord(Coord):
    name = "noop"

    def build_coord(self):
        return CartesianCoord()


class PaperTheme(Theme):
    name = "paper"
    elements: ClassVar[dict[str, Any]] = {"panel.background": element_rect(fill="white")}


def test_position_coord_and_theme_subclasses_register_and_execute() -> None:
    registry.register_position("shift", ShiftPosition)
    registry.register_coord("noop", NoopCoord)
    registry.register_theme("paper", PaperTheme)
    try:
        data = to_column_table({"x": [1.0, 2.0], "y": [3.0, 4.0]})
        p = (
            plot.ggplot(data, plot.aes(x="x", y="y"))
            + plot.geom_point(position="shift")
            + registry.coord_noop()
            + registry.theme_paper()
        )
        built = build_plot(p)
        assert built.layers[0].position == "shift"
        assert isinstance(coord_from_component(p.coordinates), CartesianCoord)
        assert registry.theme_paper().name == "paper"
        resolved = resolve_theme(p.theme)
        assert resolved.get("panel.background").fill == "#FFFFFF"
    finally:
        registry.unregister("position", "shift")
        registry.unregister("coord", "noop")
        registry.unregister("theme", "paper")


def _viewer_cases_module():
    path = REPO / "tools" / "viewer" / "cases.py"
    spec = importlib.util.spec_from_file_location("gg4py_viewer_extension_case", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_case_renders_in_the_browser_viewer(tmp_path: Path) -> None:
    pytest.importorskip("playwright.sync_api")
    if not (VIEWER / "dist" / "main.js").is_file():
        pytest.skip("web/viewer/dist 不存在：先跑 `pixi run viewer:build`")
    module = _viewer_cases_module()
    out = tmp_path / "out"
    gallery = tmp_path / "viewer" / "dist" / "gallery.html"
    code = module.main(
        [
            "--case",
            "ext-custom-geom",
            "--out",
            str(out),
            "--gallery",
            str(gallery),
            "--min-pass",
            "1",
            "--no-screenshot",
        ]
    )
    if code == 2:
        pytest.skip("没有可用 Chromium（先跑 `pixi run viewer:browsers`）")
    assert code == 0
    payload = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert payload["counts"]["pass"] == 1
    assert payload["wasm_requests"] == []
    case = payload["cases"][0]
    assert case["case"] == "ext-custom-geom"
    assert case["image_diff_fraction"] < 0.02

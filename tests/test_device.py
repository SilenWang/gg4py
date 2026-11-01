"""设备层（SIL-595 / M0-8）：`ir.Scene` → PNG / SVG / PDF。

三条冒烟验收（issue 的验收 1–3）都在这里，另外守住设备的几条硬约束：

- 单位 pt、页面尺寸与 DPI 是显式参数，设备不替场景改纸；
- 矢量后端的文字一律是轮廓：PDF 里没有 `/Font`、SVG 里没有 `<text>`；
- `pch` 0..25 全部有几何，字符型 pch 走文字；
- 位图 blob 能解码；
- CLI `render --scene … --out x.{png,svg,pdf}` 三路都出图。

像素级回归在 `tests/test_grob_cases.py`（16 张 grob 快照），曲线求值的 R 对拍在
`tests/test_device_r_parity.py`。口径见 `docs/notes/device.md`。
"""

from __future__ import annotations

import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest
import skia

from ggcore import ir
from ggcore.device import DeviceError
from ggcore.grobs import scene, text_grob
from ggcore.ir import Gpar, NodeKind, f32
from ggcore.units import FixedMetrics
from ggcore.viewport import Device, ViewportTree, gpar, viewport
from ggskia import (
    SkiaPdfDevice,
    SkiaRasterDevice,
    SkiaSvgDevice,
    device_for,
)
from ggskia.cli import render as render_cli
from ggskia.pch import SYMBOLS, character_pch

WIDTH_PT = 6 * 72.0
HEIGHT_PT = 4 * 72.0


def smoke_scene(cjk_label: str = "中文标签 · M0-8") -> ir.Scene:
    """手搓图：矩形 + 折线 + 中文标签 + 旋转视口里的文字（验收 4）。

    构造在 `tools/cases/device_cases.py`：PR 里那张 PNG 与这里跑的是同一张图。
    """
    return TOOL.build_scene(cjk_label)


def _load_tool() -> object:
    path = Path(__file__).resolve().parents[1] / "tools" / "cases" / "device_cases.py"
    spec = importlib.util.spec_from_file_location("device_cases_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TOOL = _load_tool()


def png_pixels(data: bytes) -> np.ndarray:
    image = skia.Image.MakeFromEncoded(data)
    assert image is not None
    return np.array(image.toarray(), dtype=np.uint8, copy=True)


def ink(pixels: np.ndarray) -> int:
    """非白像素数（页面白底，任何笔画都算墨）。"""
    return int((pixels[:, :, :3] < 250).any(axis=2).sum())


def point_scene(pch: int, size: float = 40.0, page: tuple[float, float] = (100.0, 100.0)):
    node = ir.Node(
        NodeKind.POINTS,
        gpar=Gpar(col=(0, 0, 0, 255), lwd=1.0),
        params={"pch": pch, "size": size},
        bufs={"points": f32([[50.0, 50.0]])},
    )
    return scene_of(node, page)


def scene_of(node: ir.Node, page: tuple[float, float] = (100.0, 100.0)) -> ir.Scene:
    root = ir.Node(
        NodeKind.VIEWPORT,
        params={"transform": (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)},
        bufs={"clip_rect": f32([[0.0, 0.0, page[0], page[1]]])},
        children=(node,),
    )
    return ir.Scene(root=root, size=page)


# ---------------------------------------------------------------------------
# 三路冒烟（验收 1–4）
# ---------------------------------------------------------------------------


def test_raster_svg_pdf_all_render_the_smoke_scene() -> None:
    ir_scene = smoke_scene()
    png = SkiaRasterDevice(*ir_scene.size, dpi=150).render(ir_scene)
    svg = SkiaSvgDevice(*ir_scene.size).render(ir_scene)
    pdf = SkiaPdfDevice(*ir_scene.size).render(ir_scene)

    assert ink(png_pixels(png)) > 1000
    assert len(pdf) > 1024
    assert pdf.startswith(b"%PDF")
    assert b"/Font" not in pdf
    assert len(svg) > 1024


def test_svg_is_xml_and_has_paths_not_text() -> None:
    svg = SkiaSvgDevice(WIDTH_PT, HEIGHT_PT).render(smoke_scene())
    root = ET.fromstring(svg)  # 可被 XML 解析器解析
    assert root.tag.endswith("svg")
    assert b"<path" in svg
    assert b"<text" not in svg
    assert b"font-family" not in svg


def test_cjk_text_becomes_outlines_in_svg_and_pdf() -> None:
    """中文不是 `<text>`，也不是 UTF-8 原串：两个不同标签必须画出不同的轮廓。"""
    first = smoke_scene("中文标签 · M0-8")
    second = smoke_scene("中文标签 · 换一句")
    svg_first = SkiaSvgDevice(WIDTH_PT, HEIGHT_PT).render(first)
    svg_second = SkiaSvgDevice(WIDTH_PT, HEIGHT_PT).render(second)
    pdf_first = SkiaPdfDevice(WIDTH_PT, HEIGHT_PT).render(first)
    pdf_second = SkiaPdfDevice(WIDTH_PT, HEIGHT_PT).render(second)

    for payload in (svg_first, pdf_first):
        assert "中文标签".encode() not in payload  # 没有原串 = 也没有乱码的可能
    assert svg_first != svg_second
    assert pdf_first != pdf_second
    assert b"/Font" not in pdf_first and b"/Font" not in pdf_second


def test_raster_dpi_is_an_explicit_parameter() -> None:
    ir_scene = smoke_scene()
    for dpi in (72.0, 150.0, 300.0):
        pixels = png_pixels(SkiaRasterDevice(*ir_scene.size, dpi=dpi).render(ir_scene))
        expected = (round(WIDTH_PT / 72 * dpi), round(HEIGHT_PT / 72 * dpi))
        assert (pixels.shape[1], pixels.shape[0]) == expected


def test_device_refuses_a_scene_of_another_size() -> None:
    ir_scene = smoke_scene()
    with pytest.raises(DeviceError, match="页面尺寸不符"):
        SkiaSvgDevice(WIDTH_PT + 1, HEIGHT_PT).render(ir_scene)


def test_lifecycle_is_strict() -> None:
    ir_scene = smoke_scene()
    device = SkiaSvgDevice(*ir_scene.size)
    with pytest.raises(DeviceError, match="open"):
        device.draw_scene(ir_scene)
    device.open()
    with pytest.raises(DeviceError, match="open"):
        device.open()
    device.draw_scene(ir_scene)
    device.close()
    with pytest.raises(DeviceError, match="open"):
        device.close()


def test_device_for_picks_the_backend_from_the_suffix() -> None:
    assert isinstance(device_for("x.png", 100, 100), SkiaRasterDevice)
    assert isinstance(device_for(Path("x.svg"), 100, 100), SkiaSvgDevice)
    assert isinstance(device_for("x.pdf", 100, 100), SkiaPdfDevice)
    with pytest.raises(DeviceError, match="不认识的输出格式"):
        device_for("x.eps", 100, 100)


# ---------------------------------------------------------------------------
# 能力清单：pch 全表 / 位图 blob
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pch", sorted(SYMBOLS))
def test_every_symbol_pch_draws_ink(pch: int) -> None:
    pixels = png_pixels(SkiaRasterDevice(100, 100).render(point_scene(pch)))
    assert ink(pixels) > 20


def test_character_pch_renders_the_character() -> None:
    assert character_pch(65) == "A"
    assert character_pch(-0x4E2D) == "中"
    assert character_pch(26) is None
    assert ink(png_pixels(SkiaRasterDevice(100, 100).render(point_scene(65)))) > 20
    assert ink(png_pixels(SkiaRasterDevice(100, 100).render(point_scene(-0x4E2D)))) > 20


def test_symbol_size_is_the_r_radius() -> None:
    """`pch = 1` 的直径是 size 的 3/4（R 的 RADIUS = 0.375，不是 0.5）。"""
    pixels = png_pixels(SkiaRasterDevice(100, 100).render(point_scene(1, size=40.0)))
    rows, cols = np.nonzero((pixels[:, :, :3] < 250).any(axis=2))
    diameter = max(cols.max() - cols.min(), rows.max() - rows.min()) + 1
    assert 28 <= diameter <= 32  # 0.75 * 40 = 30pt（72dpi 下 1pt = 1px）± 描边


def test_unimplemented_pch_only_warns() -> None:
    with pytest.warns(UserWarning, match="pch 26"):
        SkiaRasterDevice(100, 100).render(point_scene(26))


def test_raster_blob_is_decoded() -> None:
    ramp = np.linspace(0, 255, 8, dtype=np.uint8)
    pixels = np.dstack(
        [
            np.full((8, 8), 40, dtype=np.uint8),
            np.tile(ramp, (8, 1)),
            np.full((8, 8), 200, dtype=np.uint8),
            np.full((8, 8), 255, dtype=np.uint8),
        ]
    )
    image = skia.Image.fromarray(np.ascontiguousarray(pixels), colorType=skia.kRGBA_8888_ColorType)
    data = bytes(image.encodeToData(skia.kPNG, 100).bytes())
    blob = ir.Blob(data, "image/png")
    bid = ir.blob_id(data, "image/png")
    node = ir.Node(
        NodeKind.RASTER,
        params={"blob": bid, "width": 8, "height": 8, "interpolate": False},
        bufs={"rect": f32([[10.0, 10.0, 90.0, 90.0]])},
    )
    root = ir.Node(
        NodeKind.VIEWPORT,
        params={"transform": (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)},
        bufs={"clip_rect": f32([[0.0, 0.0, 100.0, 100.0]])},
        children=(node,),
    )
    ir_scene = ir.Scene(root=root, size=(100.0, 100.0), blobs=ir.BlobTable({bid: blob}))
    colours = png_pixels(SkiaRasterDevice(100, 100).render(ir_scene))
    assert colours[50, 50, 1] > 100  # 绿色通道来自位图，不是白底


def test_fixed_metrics_scene_still_renders() -> None:
    """没有 skia 度量时（FixedMetrics）设备照样出图。"""
    tree = ViewportTree(
        Device(2, 1),
        metrics=FixedMetrics(widths={"hi": 0.2}, heights={"hi": 0.15}),
    )
    tree.push(viewport("page", clip="off"))
    ir_scene = scene([text_grob("hi", gp=gpar(col="#000000"))], tree).to_ir_scene()
    assert ink(png_pixels(SkiaRasterDevice(*ir_scene.size).render(ir_scene))) > 5


# ---------------------------------------------------------------------------
# CLI：render --scene … --out x.{png,svg,pdf}
# ---------------------------------------------------------------------------


def test_cli_renders_each_format(tmp_path: Path) -> None:
    ir_scene = smoke_scene()
    source = tmp_path / "scene.ggir.cbor"
    source.write_bytes(ir.encode(ir_scene))
    outputs = {}
    for suffix in (".png", ".svg", ".pdf"):
        target = tmp_path / f"out{suffix}"
        assert render_cli.main(["--scene", str(source), "--out", str(target)]) == 0
        outputs[suffix] = target.read_bytes()
    assert outputs[".pdf"].startswith(b"%PDF")
    assert b"<path" in outputs[".svg"]
    assert outputs[".png"].startswith(b"\x89PNG")


def test_cli_rejects_an_unknown_suffix(tmp_path: Path) -> None:
    source = tmp_path / "scene.ggir.cbor"
    source.write_bytes(ir.encode(smoke_scene()))
    assert render_cli.main(["--scene", str(source), "--out", str(tmp_path / "x.eps")]) == 2


def test_cli_dpi_flag_wins(tmp_path: Path) -> None:
    ir_scene = smoke_scene()
    source = tmp_path / "scene.ggir.cbor"
    source.write_bytes(ir.encode(ir_scene))
    target = tmp_path / "out.png"
    assert render_cli.main(["--scene", str(source), "--out", str(target), "--dpi", "300"]) == 0
    pixels = png_pixels(target.read_bytes())
    assert pixels.shape[:2] == (round(HEIGHT_PT / 72 * 300), round(WIDTH_PT / 72 * 300))

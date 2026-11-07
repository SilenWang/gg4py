"""设备层（SIL-595 / M0-8）：`ir.Scene` → PNG / SVG / PDF。

三条冒烟验收（issue 的验收 1–3）都在这里，另外守住设备的几条硬约束：

- 单位 pt、页面尺寸与 DPI 是显式参数，设备不替场景改纸；
- 矢量后端的文字一律是轮廓：PDF 里没有 `/Font`、SVG 里没有 `<text>`；
- `pch` 0..25 全部有几何，字符型 pch 走文字；
- 位图 blob 能解码；
- 图案填充在 SVG 后端写成真正的 `<pattern>`（SIL-833），PNG / PDF 走逐 tile 的
  矢量平铺；
- CLI `render --scene … --out x.{png,svg,pdf}` 三路都出图。

像素级回归在 `tests/test_grob_cases.py`（16 张 grob 快照），曲线求值的 R 对拍在
`tests/test_device_r_parity.py`（纯函数）与
`tests/test_device_render_r_parity.py`（设备级真渲染）。口径见
`docs/notes/device.md`。
"""

from __future__ import annotations

import base64
import importlib.util
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

import numpy as np
import pytest
import skia

from ggcore import ir
from ggcore.arrow import arrow, head_geometry
from ggcore.device import DeviceError
from ggcore.grobs import curve_grob, scene, text_grob
from ggcore.ir import Gpar, LineEnd, NodeKind, f32
from ggcore.units import FixedMetrics, unit
from ggcore.viewport import Device, ViewportTree, gpar, viewport
from ggskia import (
    SkiaPdfDevice,
    SkiaRasterDevice,
    SkiaSvgDevice,
    device_for,
)
from ggskia.cli import render as render_cli
from ggskia.curves import curve_points
from ggskia.pch import SYMBOLS, character_pch

WIDTH_PT = 6 * 72.0
HEIGHT_PT = 4 * 72.0
REPO = Path(__file__).resolve().parents[1]


def smoke_scene(cjk_label: str = "中文标签 · M0-8") -> ir.Scene:
    """手搓图：矩形 + 折线 + 中文标签 + 旋转视口里的文字（验收 4）。

    构造在 `tools/cases/device_cases.py`：PR 里那张 PNG 与这里跑的是同一张图。
    """
    return TOOL.build_scene(cjk_label)


def _load_tool() -> object:
    path = REPO / "tools" / "cases" / "device_cases.py"
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
    if pch == 46:
        # `'.'` 是 R 的 0.01 inch 实心方块，不吃 `size`：72 dpi 下墨迹只有几个像素。
        assert ink(pixels) >= 1
    else:
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


def test_svg_raster_keeps_the_bitmap_intact_and_scales_by_cell() -> None:
    """SVG 的 `<image>` 必须是完整不透明的 PNG，并按 svglite 的口径标注。

    skia 的 `SVGCanvas` 会在大位图上把重编码写坏（实测下半截全透明，SIL-794）；
    svglite 另外写 `preserveAspectRatio='none'` + `image-rendering='pixelated'`，
    少一个，3×1 的 raster 会被按原始长宽比塞进目标框，或者被 resvg 平滑糊掉。
    像素尺寸是「每格 ceil(目标/格数)」：80pt 宽、3 列 → 27×3 = 81 px。
    """
    ramp = np.linspace(0, 255, 3, dtype=np.uint8)
    pixels = np.dstack(
        [
            np.tile(ramp, (1, 1)),
            np.full((1, 3), 40, dtype=np.uint8),
            np.full((1, 3), 200, dtype=np.uint8),
            np.full((1, 3), 255, dtype=np.uint8),
        ]
    )
    image = skia.Image.fromarray(np.ascontiguousarray(pixels), colorType=skia.kRGBA_8888_ColorType)
    data = bytes(image.encodeToData(skia.kPNG, 100).bytes())
    blob = ir.Blob(data, "image/png")
    bid = ir.blob_id(data, "image/png")
    node = ir.Node(
        NodeKind.RASTER,
        params={"blob": bid, "width": 3, "height": 1, "interpolate": False},
        bufs={"rect": f32([[10.0, 10.0, 90.0, 90.0]])},
    )
    root = ir.Node(
        NodeKind.VIEWPORT,
        params={"transform": (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)},
        bufs={"clip_rect": f32([[0.0, 0.0, 100.0, 100.0]])},
        children=(node,),
    )
    ir_scene = ir.Scene(root=root, size=(100.0, 100.0), blobs=ir.BlobTable({bid: blob}))
    svg = SkiaSvgDevice(*ir_scene.size).render(ir_scene).decode("utf-8")

    match = re.search(
        r"<image\b[^>]*xlink:href=['\"]data:image/png;base64,([A-Za-z0-9+/=]+)['\"]", svg
    )
    assert match is not None
    tag = svg[match.start() : svg.index(">", match.start())]
    assert "preserveAspectRatio='none'" in tag
    assert "image-rendering='pixelated'" in tag

    embedded = skia.Image.MakeFromEncoded(base64.b64decode(match.group(1)))
    assert embedded is not None
    assert (embedded.width(), embedded.height()) == (81, 80)
    alpha = np.asarray(embedded.toarray())[:, :, 3]
    assert int(alpha.min()) == 255  # 没有透明缺口（skia 自己编码时下半截是透明的）


def test_fixed_metrics_scene_still_renders() -> None:
    """没有 skia 度量时（FixedMetrics）设备照样出图。"""
    tree = ViewportTree(
        Device(2, 1),
        metrics=FixedMetrics(widths={"hi": 0.2}, heights={"hi": 0.15}),
    )
    tree.push(viewport("page", clip="off"))
    ir_scene = scene([text_grob("hi", gp=gpar(col="#000000"))], tree).to_ir_scene()
    assert ink(png_pixels(SkiaRasterDevice(*ir_scene.size).render(ir_scene))) > 5


#: 曲线箭头的手算组（SIL-763 的审核口径）：三条曲率把「向哪边弯」都覆盖到。
CURVE_ARROW_CURVATURES = (-0.4, 1.0, -1.0)


def _curve_arrow_svg(curvature: float) -> tuple[str, tuple[float, float], np.ndarray]:
    """一条带两端箭头的曲线 → （SVG 文本, 页面尺寸, 采样后的页面坐标）。"""
    device = Device(4.0, 3.0)
    tree = ViewportTree(device)
    x1, y1, x2, y2 = 40.0, 180.0, 250.0, 40.0
    grob = curve_grob(
        unit(x1, "bigpts"),
        unit(y1, "bigpts"),
        unit(x2, "bigpts"),
        unit(y2, "bigpts"),
        curvature=curvature,
        angle=90.0,
        ncp=5,
        shape=1.0,
        square=False,
        open=True,
        default_units="bigpts",
        gp=gpar(col="#4C78A8", lwd=1.0),
        arrow=arrow(length=12.0, ends="both", type="open"),
    )
    ir_scene = scene(grob, tree).to_ir_scene()
    svg = SkiaSvgDevice(*ir_scene.size).render(ir_scene).decode()
    # 与 `_draw_curve` 同一套坐标：IR 的 y 是页面坐标（向下），曲线公式按 R 的
    # y 向上求值，采样后再翻回页面坐标。
    height = ir_scene.size[1]
    page_y1 = height - y1
    page_y2 = height - y2
    sampled = curve_points(
        x1,
        height - page_y1,
        x2,
        height - page_y2,
        curvature=curvature,
        angle=90.0,
        ncp=5,
        shape=1.0,
        square=False,
        inflect=False,
        open=True,
        page=ir_scene.size,
    )
    sampled = np.column_stack((sampled[:, 0], height - sampled[:, 1]))
    return svg, ir_scene.size, sampled


def _svg_two_point_segments(svg: str) -> list[tuple[float, float, float, float]]:
    """SVG 里的两点折线（箭翼就是 `drawLine` 出来的 `M…L…`）。"""
    pattern = re.compile(r'd="M([-\d.]+) ([-\d.]+)L([-\d.]+) ([-\d.]+)"')
    return [tuple(float(value) for value in match.groups()) for match in pattern.finditer(svg)]


def _wing_rows(
    sampled: np.ndarray, index: int, pair: tuple[tuple[float, float], tuple[float, float]]
) -> set[tuple[float, float, float, float]]:
    """一端的两支箭翼：`(端点 x, 端点 y, 底点 x, 底点 y)`，舍到 3 位小数。"""
    tip = sampled[index]
    return {
        (round(tip[0], 3), round(tip[1], 3), round(base[0], 3), round(base[1], 3)) for base in pair
    }


@pytest.mark.parametrize("curvature", CURVE_ARROW_CURVATURES)
def test_curve_arrow_tangents_follow_the_adjacent_sample_points(curvature: float) -> None:
    """曲线两端各取**自己的**相邻点求切向，不是整条曲线的弦（SIL-763）。

    旧实现把 `(sampled[0], sampled[-1])` 同时喂给两端，`last` 端拿到的是「另一端」，
    箭翼整体偏转；这里把设备画出来的箭翼与手算的 `head_geometry`（相邻点）逐点对，
    并显式断言它**不是**弦方向的几何。
    """
    svg, _size, sampled = _curve_arrow_svg(curvature)
    segments = _svg_two_point_segments(svg)
    assert len(segments) == 4  # ends="both"：两端各两支箭翼

    first = head_geometry(*sampled[0], *sampled[1], length_pt=12.0, angle=30.0)
    last = head_geometry(*sampled[-1], *sampled[-2], length_pt=12.0, angle=30.0)
    expected = _wing_rows(sampled, 0, first) | _wing_rows(sampled, -1, last)
    drawn = {tuple(round(value, 3) for value in segment) for segment in segments}
    assert drawn == expected

    # 弦方向（旧实现）在三条曲率上都与相邻点给出的几何明显不同。
    chord_first = head_geometry(*sampled[0], *sampled[-1], length_pt=12.0, angle=30.0)
    chord_last = head_geometry(*sampled[-1], *sampled[0], length_pt=12.0, angle=30.0)
    chord = _wing_rows(sampled, 0, chord_first) | _wing_rows(sampled, -1, chord_last)
    assert drawn != chord


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


def test_bad_raster_blob_fails_cleanly_in_every_backend(tmp_path: Path) -> None:
    """坏 blob 必须干净失败：三路都 exit 2，PDF 路线不能段错误（SIL-636）。

    `demo_scene()` 的 raster blob 是 1024 B 占位、不是真 PNG。skia 的 PDF 文档
    如果晚于它的 stream 析构会直接段错误，而那只在进程退出时炸——所以这里跑
    子进程，断言返回码是 2 而不是 -11 / 139。
    """
    source = tmp_path / "demo.ggir.cbor"
    source.write_bytes(ir.encode(ir.demo_scene()))
    environment = dict(os.environ, PYTHONPATH=str(REPO / "src"))
    for suffix in ("png", "svg", "pdf"):
        target = tmp_path / f"bad.{suffix}"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ggskia.cli.render",
                "--scene",
                str(source),
                "--out",
                str(target),
            ],
            capture_output=True,
            text=True,
            env=environment,
            timeout=300,
            check=False,
        )
        assert result.returncode == 2, (suffix, result.returncode, result.stderr)
        assert "位图解码失败" in result.stderr
        assert not target.exists()


# ---------------------------------------------------------------------------
# 图案填充（SIL-833）：SVG 后端写真正的 `<pattern>`
# ---------------------------------------------------------------------------


def _pattern_scene() -> ir.Scene:
    """一个 10pt 见方的棋盘 tile 填满一条矩形。"""
    from ggcore.fills import pattern_npc_rect, tile_pattern
    from ggcore.grobs import rect_grob

    spec = tile_pattern(
        lambda bbox: [
            pattern_npc_rect(bbox, 0.5, 0.5, 0.2, 0.2, "#000000"),
            pattern_npc_rect(bbox, 0.5, 0.5, 0.1, 0.1, "#FFFFFF"),
        ],
        width=10.0,
        height=10.0,
        units="pt",
    )
    tree = ViewportTree(Device(2.0, 2.0))
    tree.push(viewport("page", clip="off"))
    return scene(rect_grob(0.5, 0.5, 0.6, 0.6, gp=gpar(fill=spec)), tree).to_ir_scene()


def test_svg_writes_a_pattern_element_for_tiled_fills() -> None:
    """SVG 里的图案是 `<pattern>`，不是逐 tile 的「内容 + 裁剪矩形」。

    光栅器按 tile 拼 `<pattern>`；我们自己逐 tile 画时 tile 边界上的半像素覆盖率
    与参考图对不上（棋盘格每条边都差一点，见 SIL-833 的 `single-pattern-fill`）。
    """
    ir_scene = _pattern_scene()
    svg = SkiaSvgDevice(*ir_scene.size).render(ir_scene).decode("utf-8")
    assert "<pattern " in svg
    assert 'patternContentUnits="userSpaceOnUse"' in svg
    assert 'fill="url(#gpat-0)"' in svg
    # 占位色不能漏到产物里
    assert "#FE01" not in svg
    # 内容仍按节点局部坐标写：内容组平移到 tile 原点（`-origin`）
    assert '<g transform="translate(' in svg


def test_raster_device_still_tiles_patterns_by_hand() -> None:
    """PNG / PDF 没有 `<pattern>` 可用，走逐 tile 的矢量写法，出的图不能是空的。"""
    ir_scene = _pattern_scene()
    png = SkiaRasterDevice(*ir_scene.size).render(ir_scene)
    pixels = png_pixels(png)
    assert ink(pixels) > 200  # tile 内容真的画出来了
    assert ink(pixels) < pixels[:, :, :3].size // 3  # 不是整块涂黑


# ---------------------------------------------------------------------------
# 虚线：SVG 写 `stroke-dasharray`，PNG / PDF 里真的有缺口（SIL-868）
# ---------------------------------------------------------------------------


def dashed_scene(*, dashed: bool = True) -> ir.Scene:
    """一条 4pt 粗的水平线（y = 50，x = 10..90）；`dashed=False` 是实线对照。

    段长用 IR 的 pt 口径：`lty = (4, 4)` → SVG 的 `stroke-dasharray` 是
    `4 × DASH_UNIT = 5.333333`（svglite 的 1/96 in，见 `docs/notes/scales.md`）。
    `lineend = butt`：round 的帽会伸进缺口（4pt 线宽把 5.33pt 的缺口吃掉大半），
    PNG 的缺口判据只能用平头量。
    """
    node = ir.Node(
        NodeKind.SEGMENTS,
        gpar=Gpar(
            col=(0, 0, 0, 255),
            lwd=4.0,
            lty=(4.0, 4.0) if dashed else (),
            lineend=LineEnd.BUTT,
        ),
        params={},
        bufs={"segments": f32([[10.0, 50.0, 90.0, 50.0]])},
    )
    return scene_of(node, (100.0, 100.0))


def test_svg_writes_stroke_dasharray_for_dashed_strokes() -> None:
    """`SVGCanvas` 不序列化 `PathEffect`：虚线必须由我们自己补成 `stroke-dasharray`。

    旧行为是 skia 把虚线**展开成填充多边形**——产物里既没有 `stroke`，也没有
    `stroke-dasharray`，虚线与实线在语义上无法区分（SIL-715 #28 / SIL-868）。
    """
    svg = SkiaSvgDevice(100.0, 100.0).render(dashed_scene()).decode("utf-8")
    assert 'stroke="#000000"' in svg
    # 段长 × `DASH_UNIT = 4/3` → 5.333333（不是 4，也不是 16）
    assert 'stroke-dasharray="5.333333 5.333333"' in svg
    # 占位色不能漏到产物里（`#FD` 开头是虚线的占位通道）
    assert "#FD0" not in svg
    # 元素仍可被 XML 解析（属性替换没有破坏标签）
    ET.fromstring(svg.encode("utf-8"))


def test_dashed_points_and_segments_are_both_marked_in_svg() -> None:
    """点图元的虚线圈：`points` 的 stroked 圆也要带 `stroke-dasharray`。"""
    node = ir.Node(
        NodeKind.POINTS,
        gpar=Gpar(fill=(255, 0, 0, 255), col=(0, 0, 255, 255), lwd=4.5, lty=(9.0, 9.0)),
        params={"pch": 21, "size": 38.0},
        bufs={"points": f32([[50.0, 50.0], [70.0, 50.0]])},
    )
    svg = SkiaSvgDevice(100.0, 100.0).render(scene_of(node)).decode("utf-8")
    # 10 个…这里是 2 个点：每个点一条 fill、一条 dashed stroke
    assert svg.count('stroke-dasharray="12 12"') == 2
    assert 'fill="red"' in svg  # R 的 `fill = "red"` 不能被占位色顶掉
    # 占位色换回真颜色（这里写成 `#RRGGBB`，与 skia 自己写命名色的习惯无关）
    assert 'stroke="#0000FF"' in svg


def test_dashed_segments_keep_gaps_in_png() -> None:
    """PNG 走 `DashPathEffect`：沿线取样必须是「有墨 → 空 → 有墨」。"""
    pixels = png_pixels(SkiaRasterDevice(100.0, 100.0).render(dashed_scene()))
    row = (pixels[50, :, :3] < 250).any(axis=1)
    runs: list[bool] = []
    for value in row[10:91]:
        if not runs or runs[-1] != bool(value):
            runs.append(bool(value))
    assert runs[:4] == [True, False, True, False], runs
    # 80pt 的线 / (5.33 + 5.33)pt 一个周期 ≈ 7.5 段：实线退化成一段时这里会红
    assert runs.count(True) >= 7, runs


def test_dashed_segments_keep_gaps_in_pdf() -> None:
    """PDF 也不能退化成实线：内容流里一条虚线是一串子路径，实线只有一条。"""
    content = _pdf_content(SkiaPdfDevice(100.0, 100.0).render(dashed_scene()))
    assert content.count(b" m\n") > 3
    solid = _pdf_content(SkiaPdfDevice(100.0, 100.0).render(dashed_scene(dashed=False)))
    assert solid.count(b" m\n") == 1


def _pdf_content(pdf: bytes) -> bytes:
    """PDF 的页面内容流（Flate 压缩，解压后再看路径算子）。"""
    start = pdf.index(b"stream\n") + len(b"stream\n")
    return zlib.decompress(pdf[start : pdf.index(b"endstream", start)])

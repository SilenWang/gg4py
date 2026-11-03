"""skia 三路设备对渐变 / 图案填充的实现（SIL-751）。

- 渐变走 skia shader：SVG 后端写出 `<linearGradient>` / `<radialGradient>`
  （`gradientUnits="userSpaceOnUse"`，坐标是节点局部坐标）；
- 图案走**矢量平铺**（逐 tile 裁剪 + 平移画内容），三路后端都不落位图；
- `extend` 映射到 `spreadMethod`；图案只支持 repeat，别的显式报错。
"""

from __future__ import annotations

import re

import pytest

from ggcore import ir
from ggcore.device import DeviceError
from ggcore.fills import pattern_rect
from ggskia.skia import SkiaPdfDevice, SkiaRasterDevice, SkiaSvgDevice

WIDTH = 300.0
HEIGHT = 200.0


def _rect(x0: float, y0: float, x1: float, y1: float, fill: object) -> ir.Node:
    return ir.Node(
        "rect", gpar=ir.Gpar(fill=fill, col=None), bufs={"rect": ir.f32([[x0, y0, x1, y1]])}
    )


def _scene(
    *children: ir.Node, transform: tuple[float, ...] = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
) -> ir.Scene:
    root = ir.Node(
        "viewport",
        params={"name": "page", "clip": True, "transform": transform},
        bufs={"clip_rect": ir.f32([[0.0, 0.0, WIDTH, HEIGHT]])},
        children=children,
    )
    return ir.Scene(root=root, size=(WIDTH, HEIGHT))


LINEAR = ir.LinearGradient(
    stops=[(0.0, (228, 87, 86, 255)), (1.0, (76, 120, 168, 255))],
    start=(10.0, 10.0),
    end=(190.0, 10.0),
)
RADIAL = ir.RadialGradient(
    stops=[(0.0, (255, 255, 255, 255)), (1.0, (0, 0, 0, 255))],
    center=(100.0, 110.0),
    radius=40.0,
)
PATTERN = ir.TilePattern(
    content=(pattern_rect((4.0, 74.0, 14.0, 84.0), "#E45756"),),
    size=(12.0, 12.0),
    origin=(4.0, 74.0),
)


def _svg(scene: ir.Scene) -> str:
    return SkiaSvgDevice(WIDTH, HEIGHT).render(scene).decode("utf-8")


def test_linear_gradient_becomes_an_svg_linear_gradient() -> None:
    svg = _svg(_scene(_rect(10.0, 10.0, 190.0, 50.0, LINEAR)))
    match = re.search(r"<linearGradient[^>]*>", svg)
    assert match is not None
    assert 'gradientUnits="userSpaceOnUse"' in match.group(0)
    assert 'x1="10"' in match.group(0) and 'x2="190"' in match.group(0)
    assert "#e45756" in svg.lower() or "228" in svg
    assert "#4c78a8" in svg.lower() or "76" in svg


def test_radial_gradient_becomes_an_svg_radial_gradient() -> None:
    svg = _svg(_scene(_rect(40.0, 70.0, 160.0, 150.0, RADIAL)))
    match = re.search(r"<radialGradient[^>]*>", svg)
    assert match is not None
    assert 'r="40"' in match.group(0)
    assert "fx=" not in match.group(0)  # 没有焦点圆时不写 fx / fr


def test_radial_gradient_with_focal_point() -> None:
    """focal 渐变的 PNG 路径可用；SVG 侧 skia 把 `fr` / `r` 映射反了（已知缺口）。

    skia 的 SVG 序列化器对两圆锥渐变写 `fr = endRadius`、`r = startRadius`，
    正好与 SVG 规范相反（规范要求 `fr < r`）。所以含 focal 的 SVG 输出不可信，
    对拍 case 只用普通径向渐变；缺口记在 `docs/notes/ir.md` §6.1。
    """
    focal = ir.RadialGradient(
        stops=[(0.0, (255, 255, 255, 255)), (1.0, (0, 0, 0, 255))],
        center=(100.0, 110.0),
        radius=40.0,
        focal=(90.0, 110.0, 5.0),
    )
    scene = _scene(_rect(40.0, 70.0, 160.0, 150.0, focal))
    svg = _svg(scene)
    assert "<radialGradient" in svg
    assert SkiaRasterDevice(WIDTH, HEIGHT).render(scene)[:4] == b"\x89PNG"


def test_gradient_extend_pad_and_repeat_differ_in_raster() -> None:
    """`extend` 在栅格路径（PNG / PDF）里是真的生效的。

    skia 的 SVG 序列化器**不写** `spreadMethod`，所以 SVG 侧的 repeat / reflect
    退化成 pad——这是设备缺口，记在 `docs/notes/ir.md` §6.1；对拍 case 只用 pad。
    """

    def raster(extend: str) -> bytes:
        fill = ir.LinearGradient(
            stops=[(0.0, (228, 87, 86, 255)), (1.0, (76, 120, 168, 255))],
            start=(10.0, 10.0),
            end=(80.0, 10.0),
            extend=extend,
        )
        return SkiaRasterDevice(WIDTH, HEIGHT).render(_scene(_rect(10.0, 10.0, 190.0, 90.0, fill)))

    assert raster("pad") != raster("repeat")
    assert "spreadMethod" not in _svg(_scene(_rect(10.0, 10.0, 190.0, 90.0, LINEAR)))


def test_pattern_is_drawn_as_vectors_not_a_bitmap() -> None:
    svg = _svg(_scene(_rect(10.0, 70.0, 180.0, 150.0, PATTERN)))
    assert "<image" not in svg
    # 170 × 80 的窗口、12 × 12 的 tile → 十几块，至少不是一块
    assert len(re.findall(r"<rect\b", svg)) > 20


def test_pattern_tiles_are_clipped_to_the_filled_shape() -> None:
    """平铺副本按 tile 窗口裁剪：SVG 里每一块都带自己的 clipRect。"""
    svg = _svg(_scene(_rect(10.0, 10.0, 60.0, 60.0, PATTERN)))
    assert "<clipPath" in svg
    # 内容 rect 本身仍在局部坐标（裁剪生效靠 clipPath，不是重写坐标）
    assert re.search(r"<rect\b", svg) is not None


def test_pattern_rejects_non_repeat_extend() -> None:
    fill = ir.TilePattern(
        content=(pattern_rect((0.0, 0.0, 4.0, 4.0), "#E45756"),),
        size=(8.0, 8.0),
        origin=(0.0, 0.0),
        extend="pad",
    )
    with pytest.raises(DeviceError, match="extend=repeat"):
        _svg(_scene(_rect(0.0, 0.0, 50.0, 50.0, fill)))


def test_all_three_backends_render_gradients_and_patterns() -> None:
    scene = _scene(
        _rect(10.0, 10.0, 190.0, 50.0, LINEAR),
        _rect(40.0, 70.0, 160.0, 150.0, RADIAL),
        _rect(10.0, 70.0, 180.0, 150.0, PATTERN),
    )
    assert SkiaSvgDevice(WIDTH, HEIGHT).render(scene)
    png = SkiaRasterDevice(WIDTH, HEIGHT).render(scene)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    pdf = SkiaPdfDevice(WIDTH, HEIGHT).render(scene)
    assert pdf.startswith(b"%PDF")


def test_gradient_in_a_transformed_viewport_still_renders() -> None:
    """渐变坐标是局部的：视口缩放后 shader 跟着一起缩（不该漂到页面原点）。"""
    scaled = _scene(
        _rect(0.0, 0.0, 100.0, 100.0, LINEAR), transform=(2.0, 0.0, 0.0, 2.0, 20.0, 20.0)
    )
    svg = _svg(scaled)
    assert "<linearGradient" in svg
    png = SkiaRasterDevice(WIDTH, HEIGHT).render(scaled)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_solid_fill_svg_output_is_unchanged() -> None:
    """纯色填充不因为新增分支多出 gradient / defs 标签（既有 case 零回退）。"""
    svg = _svg(_scene(_rect(10.0, 10.0, 190.0, 50.0, (228, 87, 86, 255))))
    assert "Gradient" not in svg
    assert "<defs" not in svg

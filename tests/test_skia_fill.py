"""skia 三路设备对渐变 / 图案填充的实现（SIL-751）。

- 渐变走 skia shader：SVG 后端写出 `<linearGradient>` / `<radialGradient>`
  （`gradientUnits="userSpaceOnUse"`，坐标是节点局部坐标）；
- 图案走**矢量平铺**（逐 tile 裁剪 + 平移画内容），三路后端都不落位图；
- `extend` 映射到 `spreadMethod`；图案只支持 repeat，别的显式报错。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from PIL import Image

from ggcore import ir
from ggcore.device import DeviceError
from ggcore.fills import pattern_rect
from ggdiff.raster import rasterize_svg
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
    """focal 渐变：SVG 必须按规范写 `cx/cy/r` = 主圆、`fx/fy/fr` = 焦点圆。

    skia 的 SVG 序列化器把两圆锥渐变的 `fr` / `r` 写反（`fr = endRadius`、
    `r = startRadius`），所以设备在序列化之后按 IR 的 fill 重写标签（SIL-767 §2）。
    这里正着断言：`fr < r`、主圆是 `center` / `radius`、焦点圆是 `focal`。
    """
    focal = ir.RadialGradient(
        stops=[(0.0, (255, 255, 255, 255)), (1.0, (0, 0, 0, 255))],
        center=(100.0, 110.0),
        radius=40.0,
        focal=(90.0, 110.0, 5.0),
    )
    scene = _scene(_rect(40.0, 70.0, 160.0, 150.0, focal))
    tag = re.search(r"<radialGradient[^>]*>", _svg(scene))
    assert tag is not None
    attributes = dict(re.findall(r'([A-Za-z]+)="([^"]*)"', tag.group(0)))
    assert float(attributes["cx"]) == 100.0 and float(attributes["cy"]) == 110.0
    assert float(attributes["r"]) == 40.0
    assert float(attributes["fx"]) == 90.0 and float(attributes["fy"]) == 110.0
    assert float(attributes["fr"]) == 5.0
    # 规范要求 fr < r；skia 原来写出来的正好相反，这条是那个 bug 的回归断言。
    assert float(attributes["fr"]) < float(attributes["r"])
    assert SkiaRasterDevice(WIDTH, HEIGHT).render(scene)[:4] == b"\x89PNG"


def test_focal_gradient_svg_rasterizes_the_way_png_renders(tmp_path: Path) -> None:
    """focal 的 SVG 交给 resvg 光栅化后，和「普通径向渐变」确实不是一张图。

    只比属性不够——属性对、语义错（比如 `fr` 被 resvg 忽略）也会通过。这里取焦点
    圆中心与主圆中心两个采样点：焦点版在焦点处是首档色，普通版不是。
    """
    focal = ir.RadialGradient(
        stops=[(0.0, (255, 0, 0, 255)), (1.0, (0, 0, 255, 255))],
        center=(100.0, 110.0),
        radius=40.0,
        focal=(90.0, 110.0, 5.0),
    )
    plain = ir.RadialGradient(
        stops=[(0.0, (255, 0, 0, 255)), (1.0, (0, 0, 255, 255))],
        center=(110.0, 110.0),
        radius=40.0,
    )

    def pixels(fill: ir.RadialGradient, name: str) -> tuple[tuple[int, ...], ...]:
        path = tmp_path / f"{name}.svg"
        path.write_text(_svg(_scene(_rect(40.0, 70.0, 160.0, 150.0, fill))), encoding="utf-8")
        png = rasterize_svg(path, tmp_path / f"{name}.png")
        image = Image.open(png).convert("RGB")
        return (image.getpixel((int(fill.center[0]), 110)),)

    focal_pixel = pixels(focal, "focal")[0]
    plain_pixel = pixels(plain, "plain")[0]
    assert focal_pixel != plain_pixel
    assert focal_pixel[0] > focal_pixel[2]  # 焦点在主圆左侧 → 该点更靠近首档（红）


def test_gradient_extend_pad_and_repeat_differ_in_raster() -> None:
    """`extend` 在栅格路径（PNG / PDF）里是真的生效的。"""

    def raster(extend: str) -> bytes:
        fill = ir.LinearGradient(
            stops=[(0.0, (228, 87, 86, 255)), (1.0, (76, 120, 168, 255))],
            start=(10.0, 10.0),
            end=(80.0, 10.0),
            extend=extend,
        )
        return SkiaRasterDevice(WIDTH, HEIGHT).render(_scene(_rect(10.0, 10.0, 190.0, 90.0, fill)))

    assert raster("pad") != raster("repeat")


def test_gradient_extend_is_written_to_svg_as_spread_method() -> None:
    """repeat / reflect 必须在 SVG 里写 `spreadMethod`（SIL-767 §3）。

    skia 的序列化器不写这个属性，三条 `extend` 的 SVG 输出原本一模一样（都退化成
    pad）。设备现在按 IR 的 `extend` 补上：pad 是 SVG 缺省值、不写，其余照写，
    且三份 SVG 互不相同。
    """

    def svg(extend: str) -> str:
        fill = ir.LinearGradient(
            stops=[(0.0, (228, 87, 86, 255)), (1.0, (76, 120, 168, 255))],
            start=(10.0, 10.0),
            end=(80.0, 10.0),
            extend=extend,
        )
        return _svg(_scene(_rect(10.0, 10.0, 190.0, 90.0, fill)))

    pad, repeat, reflect = svg("pad"), svg("repeat"), svg("reflect")
    assert "spreadMethod" not in pad
    assert 'spreadMethod="repeat"' in repeat
    assert 'spreadMethod="reflect"' in reflect
    assert len({pad, repeat, reflect}) == 3


def test_pattern_is_drawn_as_vectors_not_a_bitmap() -> None:
    """SVG 里是矢量 `<pattern>`（与 svglite 同结构），不是位图、也不是逐 tile 展开。

    SIL-833：逐 tile 的「内容 + 裁剪矩形」在 tile 边界上有半像素覆盖率，光栅器
    拼 `<pattern>` 时是整块 tile，两者对不上（棋盘格整片发灰）。
    """
    svg = _svg(_scene(_rect(10.0, 70.0, 180.0, 150.0, PATTERN)))
    assert "<image" not in svg
    assert "<pattern " in svg
    assert 'fill="url(#gpat-0)"' in svg
    # 内容（两块 4 × 4 的矩形）写在 pattern 定义里，只写一份
    assert len(re.findall(r"<rect\b", svg)) < 10


def test_pattern_content_is_written_in_local_coordinates() -> None:
    """内容按节点局部坐标写，整个内容组平移到 tile 原点（`-origin`）。"""
    svg = _svg(_scene(_rect(10.0, 10.0, 60.0, 60.0, PATTERN)))
    assert "<clipPath" in svg
    assert re.search(r'<g transform="translate\([-\d. ]+\)">', svg) is not None
    assert "patternContentUnits=\"userSpaceOnUse\"" in svg


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


def test_gradient_is_embedded_in_pdf_as_a_shading() -> None:
    """PDF 侧的渐变验收：不能只断言 `%PDF` 开头，要看到 shading 本身。

    skia 的 PDF 后端把渐变写成 `/Pattern` → `/Shading`：轴向是 `ShadingType 2`，
    径向（含 focal）是 `ShadingType 3`，端点坐标 / 端点颜色 / `Extend` 都在
    对象字典里（未压缩，可以直接按文本断言）。工具链里没有 PDF 光栅器
    （统一栅格只装 resvg），所以这是**结构级**的最小验收：坐标写反、渐变被
    丢掉、只画端点色，这几种都会让它变红。
    """
    linear = ir.LinearGradient(
        stops=[(0.0, (255, 0, 0, 255)), (1.0, (0, 0, 255, 255))],
        start=(10.0, 10.0),
        end=(80.0, 10.0),
    )
    text = SkiaPdfDevice(WIDTH, HEIGHT).render(_scene(_rect(10.0, 10.0, 190.0, 90.0, linear)))
    payload = text.decode("latin-1")
    assert "/ShadingType 2" in payload
    assert "/Coords [10 10 80 10]" in payload
    assert "/C0 [1 0 0]" in payload and "/C1 [0 0 1]" in payload
    assert "/Extend [true true]" in payload  # pad：两端都延展最后一档

    focal = ir.RadialGradient(
        stops=[(0.0, (255, 0, 0, 255)), (0.5, (0, 255, 0, 255)), (1.0, (0, 0, 255, 255))],
        center=(100.0, 60.0),
        radius=40.0,
        focal=(92.0, 60.0, 4.0),
    )
    radial = SkiaPdfDevice(WIDTH, HEIGHT).render(_scene(_rect(10.0, 10.0, 190.0, 110.0, focal)))
    payload = radial.decode("latin-1")
    assert "/ShadingType 3" in payload
    # PDF 的径向坐标顺序是「焦点圆 → 主圆」：fx fy fr cx cy r。
    assert "/Coords [92 60 4 100 60 40]" in payload
    # 3 档 → 分段函数（FunctionType 3）+ 一个分界点。
    assert "/FunctionType 3" in payload and "/Bounds [.5]" in payload


def test_pdf_repeat_gradient_is_not_the_pad_shading() -> None:
    """`extend = repeat` 在 PDF 里走 function-based shading（`ShadingType 1`）。"""

    def pdf(extend: str) -> str:
        fill = ir.LinearGradient(
            stops=[(0.0, (255, 0, 0, 255)), (1.0, (0, 0, 255, 255))],
            start=(10.0, 10.0),
            end=(80.0, 10.0),
            extend=extend,
        )
        scene = _scene(_rect(10.0, 10.0, 190.0, 90.0, fill))
        return SkiaPdfDevice(WIDTH, HEIGHT).render(scene).decode("latin-1")

    pad, repeat = pdf("pad"), pdf("repeat")
    assert "/ShadingType 2" in pad
    assert "/ShadingType 1" in repeat
    assert pad != repeat

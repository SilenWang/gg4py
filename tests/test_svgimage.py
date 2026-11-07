"""SIL-867：`image-rendering="pixelated"` 的位图在 resvg 前按格点铺好。

守两条：

1. 口径与 svglite 一致（`ceil(ceil(目标 pt) / 格数) × 格数`），已是格点尺寸时
   **一个字节都不动**——参考图与 skia 设备腿因此不受影响；
2. resvg 不认 `image-rendering`，铺好之后棋盘格才画得回四色（不铺是一团插值）。
"""

from __future__ import annotations

import base64
import io
import shutil
from pathlib import Path

import pytest
from PIL import Image

from ggdiff.image import load_image
from ggdiff.raster import rasterize_svg
from ggdiff.svgimage import cell_aligned_pixels, snap_pixelated_images

COLOURS = [(255, 0, 0), (0, 160, 0), (0, 0, 255), (255, 255, 0)]


def _png(cells: tuple[int, int] = (2, 2)) -> bytes:
    """`cells` 个格点的棋盘格 PNG（每格一个颜色，按行优先循环取）。"""
    width, height = cells
    image = Image.new("RGB", (width, height))
    image.putdata(
        [
            COLOURS[(row * width + column) % len(COLOURS)]
            for row in range(height)
            for column in range(width)
        ]
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _svg(payload: bytes, *, width: float, height: float, pixelated: bool = True) -> str:
    attribute = ' image-rendering="pixelated"' if pixelated else ""
    data = base64.b64encode(payload).decode("ascii")
    return (
        "<svg xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink'"
        " width='80pt' height='80pt' viewBox='0 0 80 80'>"
        f"<image x='0' y='0' width='{width}' height='{height}'"
        f" preserveAspectRatio='none'{attribute}"
        f" href='data:image/png;base64,{data}' xlink:href='data:image/png;base64,{data}'/>"
        "</svg>"
    )


def _embedded_size(markup: str) -> tuple[int, int]:
    data = markup.split("base64,", 1)[1].split("'", 1)[0]
    with Image.open(io.BytesIO(base64.b64decode(data))) as image:
        return image.size


def _resvg_available() -> bool:
    return shutil.which("resvg") is not None


requires_resvg = pytest.mark.skipif(not _resvg_available(), reason="resvg 不在环境里")


def test_cell_aligned_pixels_follows_svglite() -> None:
    # 3×2 的 raster 铺进 586.448 × 474.884 pt：588 × 477（先 ceil 到 587 / 475，再按格点取整）。
    assert cell_aligned_pixels(2, 586.448) == 588
    assert cell_aligned_pixels(3, 474.884) == 477
    # 10 格的 irregular categorical：560 × 480。
    assert cell_aligned_pixels(10, 558.66) == 560
    assert cell_aligned_pixels(10, 474.884) == 480
    # 目标比格数还小也要给出至少一格。
    assert cell_aligned_pixels(10, 3.0) == 10


def test_pixelated_bitmap_is_prescaled_and_drawn_rect_is_kept(tmp_path: Path) -> None:
    source = tmp_path / "in.svg"
    target = tmp_path / "out.svg"
    source.write_text(_svg(_png(), width=80, height=80), encoding="utf-8")
    assert snap_pixelated_images(source, target) == 1
    markup = target.read_text(encoding="utf-8")
    assert _embedded_size(markup) == (80, 80)
    # 目标矩形不动：位图按格点铺好，`<image>` 仍是原来的 80×80。
    assert "width='80' height='80'" in markup
    # `href` 与 `xlink:href` 两处都换成了同一份新位图。
    assert markup.count("data:image/png;base64,") == 2


def test_snapping_is_idempotent_and_leaves_aligned_bitmaps_alone(tmp_path: Path) -> None:
    """参考图 / skia 设备腿的位图已经是格点尺寸 → 不重编码、不动字节。"""
    source = tmp_path / "aligned.svg"
    target = tmp_path / "copy.svg"
    source.write_text(_svg(_png((2, 2)), width=2, height=2), encoding="utf-8")
    assert snap_pixelated_images(source, target) == 0
    assert target.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")


def test_non_pixelated_images_are_left_to_the_rasterizer(tmp_path: Path) -> None:
    """`interpolate = TRUE` 的位图（图例 colourbar 那种）本来就该插值。"""
    source = tmp_path / "smooth.svg"
    target = tmp_path / "copy.svg"
    source.write_text(_svg(_png(), width=80, height=80, pixelated=False), encoding="utf-8")
    assert snap_pixelated_images(source, target) == 0
    assert target.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")


def test_namespace_prefixed_image_tags_are_handled(tmp_path: Path) -> None:
    """`inline_text_paths` 用 ElementTree 重写后标签带 `ns0:` 前缀。"""
    source = tmp_path / "prefixed.svg"
    target = tmp_path / "out.svg"
    markup = _svg(_png(), width=80, height=80).replace("<image", "<ns0:image")
    source.write_text(markup, encoding="utf-8")
    assert snap_pixelated_images(source, target) == 1
    assert _embedded_size(target.read_text(encoding="utf-8")) == (80, 80)


def test_in_place_only_touches_files_that_need_it(tmp_path: Path) -> None:
    plain = tmp_path / "plain.svg"
    plain.write_text(_svg(_png((2, 2)), width=2, height=2), encoding="utf-8")
    before = plain.stat().st_mtime_ns
    assert snap_pixelated_images(plain) == 0
    assert plain.stat().st_mtime_ns == before

    pending = tmp_path / "pending.svg"
    pending.write_text(_svg(_png(), width=80, height=80), encoding="utf-8")
    assert snap_pixelated_images(pending) == 1
    assert _embedded_size(pending.read_text(encoding="utf-8")) == (80, 80)


@requires_resvg
def test_resvg_draws_four_cells_after_snapping(tmp_path: Path) -> None:
    """resvg 不认 `image-rendering`：不铺是插值糊，铺好才是四色棋盘格。"""
    raw = tmp_path / "raw.svg"
    raw.write_text(_svg(_png(), width=80, height=80), encoding="utf-8")
    snapped = tmp_path / "snapped.svg"
    snap_pixelated_images(raw, snapped)

    rasterize_svg(raw, tmp_path / "raw.png", dpi=72)
    rasterize_svg(snapped, tmp_path / "snapped.png", dpi=72)
    loose = load_image(tmp_path / "raw.png")
    fixed = load_image(tmp_path / "snapped.png")

    assert len({tuple(pixel) for pixel in fixed.reshape(-1, 3).tolist()}) == 4
    assert len({tuple(pixel) for pixel in loose.reshape(-1, 3).tolist()}) > 4
    # 每格正好 40×40：左下是第二行第一格的颜色。
    assert tuple(fixed[20, 20]) == COLOURS[0]
    assert tuple(fixed[20, 60]) == COLOURS[1]
    assert tuple(fixed[60, 20]) == COLOURS[2]
    assert tuple(fixed[60, 60]) == COLOURS[3]

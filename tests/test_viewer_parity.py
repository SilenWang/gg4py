"""M2-12：两条渲染腿对拍的归一化与判据（不启浏览器）。

`tools/viewer/parity.py` 的三个判据各自只负责一件事：

- 颜色集合 → 涂错色 / 少一层（集合比、不计元素个数）；
- 墨迹差 → 画丢 / 画多 / 错位 / 线宽虚线不对；
- 重心与包围盒 → 整体位移。

这里用合成 SVG / PNG 逐条守住它们；负向对照（selftest）单独一格，防止
判据在「全绿」时其实什么都没看。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools" / "viewer"))
sys.path.insert(0, str(REPO / "src"))

import parity

from ggdiff.image import save_png

SVG_HEAD = '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20">'


def _svg(path: Path, body: str) -> Path:
    path.write_text(f"{SVG_HEAD}{body}</svg>", encoding="utf-8")
    return path


def _ink(path: Path, *, offset: int = 0, colour: int = 0) -> Path:
    """40×20 的白底 PNG，`(10+offset, 5)-(20+offset, 15)` 一块实心墨。"""
    image = np.full((20, 40, 3), 255, dtype=np.uint8)
    image[5:15, 10 + offset : 20 + offset] = colour
    save_png(path, image)
    return path


def test_palette_inherits_and_normalises(tmp_path: Path) -> None:
    svg = _svg(
        tmp_path / "a.svg",
        '<g fill="#F00" fill-opacity="0.5" stroke="none">'
        '<rect x="0" y="0" width="4" height="4"/>'
        '<path d="M0 0L1 1"/></g>',
    )
    assert parity.normalised_palette(svg) == {("#ff0000", "0.5")}


def test_palette_uses_svg_defaults(tmp_path: Path) -> None:
    """skia 只写与缺省不同的属性：没写 fill 的 `<path>` 是**黑色实心**。"""
    svg = _svg(tmp_path / "b.svg", '<path d="M0 0L1 1"/>')
    assert parity.normalised_palette(svg) == {("#000000", "1")}


def test_palette_ignores_invisible_hit_areas(tmp_path: Path) -> None:
    """查看器给图例 key 加了 `fill="transparent"` 的命中区，它不是涂色。"""
    svg = _svg(
        tmp_path / "c.svg",
        '<rect x="0" y="0" width="4" height="4" fill="#123456"/>'
        '<rect x="0" y="0" width="4" height="4" fill="transparent"/>',
    )
    assert parity.normalised_palette(svg) == {("#123456", "1")}


def test_ink_difference_ignores_antialiasing_at_the_edge(tmp_path: Path) -> None:
    left = _ink(tmp_path / "left.png", colour=40)
    right = _ink(tmp_path / "right.png", colour=52)  # 同一形状，边缘差一档
    assert parity.ink_difference(left, right) == 0.0


def test_ink_difference_sees_a_shift(tmp_path: Path) -> None:
    left = _ink(tmp_path / "left.png")
    right = _ink(tmp_path / "right.png", offset=4)
    assert parity.ink_difference(left, right) > 0.005


def test_centroid_and_bbox_track_position(tmp_path: Path) -> None:
    left = _ink(tmp_path / "left.png")
    right = _ink(tmp_path / "right.png", offset=3)
    assert parity._centroid_delta(parity.ink_centroid(left), parity.ink_centroid(right)) == 3.0
    assert parity._bbox_delta(parity.ink_bbox(left), parity.ink_bbox(right)) == 3.0


def test_blank_page_has_no_ink(tmp_path: Path) -> None:
    empty = save_png(tmp_path / "empty.png", np.full((20, 40, 3), 255, dtype=np.uint8))
    assert parity.ink_bbox(empty) is None
    assert parity.ink_centroid(empty) is None


def test_selftest_detects_shift_and_colour(tmp_path: Path) -> None:
    """负向对照：判据必须能抓到 2 pt 位移与错色。"""
    case = tmp_path / "case"
    case.mkdir()
    body = '<rect x="4" y="4" width="10" height="8" fill="#2266aa"/>'
    _svg(case / "skia.outlined.svg", body)
    _svg(case / "viewer.outlined.svg", body)
    checks = parity.selftest(tmp_path)
    assert [name for name, ok, _ in checks if not ok] == []


def test_untouched_pair_passes_selftest_baseline(tmp_path: Path) -> None:
    """对照：原样的一对 SVG 在位移 / 换色判据下都**不该**被判失败。"""
    case = tmp_path / "case"
    case.mkdir()
    body = '<rect x="4" y="4" width="10" height="8" fill="#2266aa"/>'
    _svg(case / "skia.outlined.svg", body)
    _svg(case / "viewer.outlined.svg", body)
    shifted = tmp_path / "shifted.svg"
    parity._mutated_shift(case / "viewer.outlined.svg", shifted, pt=0.0)
    from ggdiff.raster import rasterize_svg

    reference = rasterize_svg(
        case / "skia.outlined.svg", tmp_path / "ref.png", dpi=72, background="#ffffff"
    )
    moved = rasterize_svg(shifted, tmp_path / "moved.png", dpi=72, background="#ffffff")
    assert parity.ink_difference(reference, moved) == 0.0
    assert parity._centroid_delta(
        parity.ink_centroid(reference), parity.ink_centroid(moved)
    ) == pytest.approx(0.0)

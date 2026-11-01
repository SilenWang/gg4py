"""设备级 R 对拍（SIL-636 的回归门）：R 真渲染 vs 设备真渲染。

`tests/test_device_r_parity.py` 只比纯函数（`curve_points` / `xspline_points`
的返回值）。那条对拍挡不住「函数对、集成错」：`_draw_curve` 漏掉 y 翻转时它
100% 绿，而设备画出来的曲线是上下镜像的（SIL-636 的阻塞 1）。这里换一层——
同一张 4×3 in / 150 ppi 的页面上：

- **PNG**：R 4.5.3 渲染的 PNG（`tools/refs/device_render_ref.R`）与设备渲染
  的 PNG 比墨迹 IoU；
- **SVG**：从设备吐出的 SVG 里解析出折线的 `d`，与 R 的**设备坐标**折线
  （`grid:::xsplinePoints` → 英寸 → pt，y 向下）逐点比——拐角在哪一侧是这条
  断言钉的，不是形状差不多。

夹具同 `tests/fixtures/device_render_r/`：`index.json` + 每个用例一张 PNG。
重新生成：`pixi run -e refs refs:device-render`。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pytest
import skia

from ggcore.grobs import (
    curve_grob,
    points_grob,
    segments_grob,
    xspline_grob,
)
from ggcore.grobs import (
    scene as build_scene,
)
from ggcore.viewport import Device, ViewportTree, gpar
from ggskia import SkiaRasterDevice, SkiaSvgDevice

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "device_render_r"
DATA = json.loads((FIXTURES / "index.json").read_text(encoding="utf-8"))

PAGE = tuple(value * 72.0 for value in DATA["page_in"])
DPI = float(DATA["res"])
# 折线逐点比：IR 是 float32，R 是 double；0.01 pt 已经比一个像素小两个数量级。
POLYLINE_TOLERANCE = 0.01
# 墨迹 IoU：同一条线、同一组坐标，差的是抗锯齿（实测 0.98–1.00）。
IOU_FLOOR = 0.9

CASES = {case["id"]: case for case in DATA["cases"]}


def _render(grob: object, kind: str) -> bytes:
    tree = ViewportTree(Device(*DATA["page_in"]))
    ir_scene = build_scene(grob, tree).to_ir_scene()  # type: ignore[arg-type]
    device = (
        SkiaRasterDevice(*ir_scene.size, dpi=DPI)
        if kind == "png"
        else SkiaSvgDevice(*ir_scene.size)
    )
    return device.render(ir_scene)


def _pixels(data: bytes) -> np.ndarray:
    image = skia.Image.MakeFromEncoded(data)
    assert image is not None
    return np.array(image.toarray(), dtype=np.uint8, copy=True)


def _ink(pixels: np.ndarray) -> np.ndarray:
    """非白像素（页面白底；alpha 通道不参与——栅格设备的 PNG 一直是透明底）。"""
    return (pixels[:, :, :3] < 250).any(axis=2)


def _iou(left: np.ndarray, right: np.ndarray) -> float:
    a, b = _ink(left), _ink(right)
    union = int((a | b).sum())
    return float((a & b).sum() / union) if union else 1.0


_NUMBER = re.compile(r"[MLZ]|-?\d*\.?\d+(?:[eE][-+]?\d+)?")


def _svg_polyline(svg: bytes) -> np.ndarray:
    """设备 SVG 里第一条 `<path>` 的顶点（pt，y 向下）。"""
    text = svg.decode("utf-8")
    match = re.search(r'<path[^>]*\bd="([^"]*)"', text)
    assert match is not None, "SVG 里没有 <path>"
    tokens = _NUMBER.findall(match.group(1))
    points: list[tuple[float, float]] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in {"M", "L", "Z"}:
            index += 1
            continue
        points.append((float(token), float(tokens[index + 1])))
        index += 2
    return np.asarray(points, dtype=np.float64)


def _r_png(case_id: str) -> np.ndarray:
    return _pixels((FIXTURES / f"{case_id}.png").read_bytes())


def _grobs() -> dict[str, object]:
    xspline = CASES["xspline-open-4"]["params"]
    return {
        "curve-square-angle90": curve_grob(
            x1=0.1,
            y1=0.75,
            x2=0.5,
            y2=0.5,
            square=True,
            angle=90,
            gp=gpar(col="#000000", lwd=2.5),
        ),
        "curve-curved-angle45": curve_grob(
            x1=0.1,
            y1=0.75,
            x2=0.5,
            y2=0.5,
            square=False,
            angle=45,
            curvature=0.6,
            gp=gpar(col="#000000", lwd=2.5),
        ),
        "xspline-open-4": xspline_grob(
            x=xspline["x"],
            y=xspline["y"],
            shape=xspline["shape"],
            gp=gpar(col="#000000", lwd=2.5),
        ),
        "lwd-6-line": segments_grob(
            x0=0.1,
            y0=0.5,
            x1=0.9,
            y1=0.5,
            gp=gpar(col="#000000", lwd=6, lineend="butt"),
        ),
        "pch-46-dot": points_grob(
            x=0.5,
            y=0.5,
            pch=46,
            size=1.0,
            gp=gpar(col="#000000"),
        ),
    }


GROBS = _grobs()


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_rendered_png_matches_r(case_id: str) -> None:
    """R 画的 PNG 与设备画的 PNG 墨迹重合（镜像、平移、线宽都在这里。"""
    pixels = _pixels(_render(GROBS[case_id], "png"))
    reference = _r_png(case_id)
    assert pixels.shape == reference.shape
    score = _iou(pixels, reference)
    assert score >= IOU_FLOOR, f"{case_id}: IoU {score:.4f} < {IOU_FLOOR}"


POLYLINE_CASES = ["curve-square-angle90", "curve-curved-angle45", "xspline-open-4"]


@pytest.mark.parametrize("case_id", POLYLINE_CASES)
def test_rendered_svg_polyline_matches_r_device_polyline(case_id: str) -> None:
    """SVG 里的折线与 R 的设备坐标折线逐点相同（不是「形状差不多」）。"""
    got = _svg_polyline(_render(GROBS[case_id], "svg"))
    want = np.asarray(CASES[case_id]["polyline"], dtype=np.float64)
    assert got.shape == want.shape
    assert np.abs(got - want).max() < POLYLINE_TOLERANCE


def test_curve_square_corner_is_on_the_y2_side() -> None:
    """`square = TRUE, angle = 90` 的拐角在 `y2` 那一侧（沿弦线镜像会翻到 `y1`）。"""
    case = CASES["curve-square-angle90"]
    y1 = (1.0 - case["params"]["y1"]) * PAGE[1]
    y2 = (1.0 - case["params"]["y2"]) * PAGE[1]
    got = _svg_polyline(_render(GROBS["curve-square-angle90"], "svg"))
    want = np.asarray(case["polyline"], dtype=np.float64)

    def corner(points: np.ndarray) -> np.ndarray:
        chord_start, chord_end = points[0], points[-1]
        direction = chord_end - chord_start
        offsets = points - chord_start
        cross = np.abs(direction[0] * offsets[:, 1] - direction[1] * offsets[:, 0])
        return points[int(np.argmax(cross))]

    # 拐角离 y2 更近就是 y2 那一侧（xspline 会把尖角磨圆，所以不比绝对距离）。
    for name, points in (("R", want), ("device", got)):
        corner_y = float(corner(points)[1])
        assert abs(corner_y - y2) < abs(corner_y - y1), f"{name}: 拐角翻到了 y1 那一侧"


def test_stroke_width_matches_r_at_150_ppi() -> None:
    """`lwd = 6` @150 ppi 与 R 同宽：R 的 `lwd` 是 1/96 inch，不是 pt。"""
    reference = _ink(_r_png("lwd-6-line"))
    reference_rows = np.where(reference.any(axis=1))[0]
    reference_height = int(reference_rows.max() - reference_rows.min() + 1)
    assert reference_height == 10  # R 4.5.3 的实测值（6/96 in @150 ppi）

    ours = _ink(_pixels(_render(GROBS["lwd-6-line"], "png")))
    our_rows = np.where(ours.any(axis=1))[0]
    assert int(our_rows.max() - our_rows.min() + 1) == reference_height


def test_pch_46_dot_matches_r_tiny_square() -> None:
    """`pch = 46` 是 0.01 inch 的实心方块（R 的特判），不是 `.` 的字形。"""
    reference = _ink(_r_png("pch-46-dot"))
    rows, cols = np.where(reference)
    assert max(rows.max() - rows.min(), cols.max() - cols.min()) + 1 <= 3

    ours = _ink(_pixels(_render(GROBS["pch-46-dot"], "png")))
    rows, cols = np.where(ours)
    assert max(rows.max() - rows.min(), cols.max() - cols.min()) + 1 <= 3
    assert int(ours.sum()) > 0


def test_pch_46_ignores_size_like_r() -> None:
    """R 的 `pch = 46` 不吃 `size`（吃 gpar 的 `cex`，IR 还没有这个字段）。"""
    big = points_grob(x=0.5, y=0.5, pch=46, size=40.0, gp=gpar(col="#000000"))
    ours = _ink(_pixels(_render(big, "png")))
    rows, cols = np.where(ours)
    assert max(rows.max() - rows.min(), cols.max() - cols.min()) + 1 <= 3

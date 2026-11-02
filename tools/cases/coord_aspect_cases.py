#!/usr/bin/env python
"""坐标等比例的可视化验证（M1-5）：2×2 合成 panel → PNG / SVG，量像素宽高比。

    pixi run cases:coord            # 写 .coord-aspect/*.png / *.svg
    pixi run cases:coord --check    # 只跑测量与断言，不写文件

测的是**面板本身**：一张 6 × 4 in 的页面上放一个由 `coord.panel_params()` 算出的
panel（`panel_sizes` 决定它的英寸宽高），panel 里画一块底色 + 2×2 网格。没有
geom、没有轴标签，所以测量不会被文字或留白干扰。

三个 case：

| case | 期望 高/宽 | 说明 |
| --- | --- | --- |
| `fixed-ratio-1` | 1.000 | x/y 数据范围等宽（expand 后都是 2.2） |
| `fixed-ratio-2` | 2.000 | 同上；`aspect = ratio × yrange/xrange` |
| `cartesian-control` | 4/6 | 不写 `coord_fixed` 时 panel 铺满可用区域，不强制比例 |

两条独立测量：PNG 取「非白像素的外接框」（150 dpi），SVG 取面板底色矩形的
`width` / `height` 属性。两者都要落在期望值的 0.5% 以内。
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from ggcore import registry  # noqa: E402
from ggcore.aes import aes  # noqa: E402
from ggcore.build import build_plot  # noqa: E402
from ggcore.coord import PanelParams  # noqa: E402
from ggcore.data import Column, ColumnTable  # noqa: E402
from ggcore.grobs import g_table_grob, lines_grob, rect_grob, scene  # noqa: E402
from ggcore.gtable import gtable, gtable_add_grob  # noqa: E402
from ggcore.ir import Scene  # noqa: E402
from ggcore.plot import ggplot  # noqa: E402
from ggcore.units import unit  # noqa: E402
from ggcore.viewport import Device, ViewportTree, gpar, viewport  # noqa: E402
from ggskia import SkiaRasterDevice, SkiaSvgDevice  # noqa: E402

OUT = REPO / ".coord-aspect"
DEVICE_IN = (6.0, 4.0)
DPI = 150.0

#: 面板底色（测量 PNG 的锚点）与网格线颜色。
PANEL_COLOUR = "#DDE7F2"
GRID_COLOUR = "#333333"

#: 数据在 x / y 上取同一段范围，`fixed` 的物理比例才等于 `ratio`
#: （`aspect = ratio × diff(y.range) / diff(x.range)`，上游 `CoordFixed$aspect()`）。
DATA = ColumnTable(
    [
        ("x", Column("float", np.array([0.0, 1.0, 2.0]))),
        ("y", Column("float", np.array([0.0, 1.0, 2.0]))),
    ]
)


@dataclass(frozen=True, slots=True)
class Case:
    name: str
    coord: object
    #: 期望的 高/宽；`None` 表示「不强制比例」，用设备比例代替。
    expected: float | None


CASES: tuple[Case, ...] = (
    Case("fixed-ratio-1", registry.coord_fixed(ratio=1.0), 1.0),
    Case("fixed-ratio-2", registry.coord_fixed(ratio=2.0), 2.0),
    Case("cartesian-control", registry.coord_cartesian(), DEVICE_IN[1] / DEVICE_IN[0]),
)


# ---------------------------------------------------------------------------
# 场景
# ---------------------------------------------------------------------------


def plot_for(coord: object):
    """最小 plot：只为了拿训练后的 `coord.panel_params()`（不需要 geom 绘制）。"""
    p = ggplot(DATA, aes(x="x", y="y"))
    return p if coord is None else p + coord


def panel_scene(coord: object) -> tuple[Scene, PanelParams]:
    build = build_plot(plot_for(coord))
    panel = build.panel_params
    assert panel is not None
    width_in, height_in = panel.panel_sizes(*DEVICE_IN)
    table = gtable(
        widths=unit(width_in * 2.54, "cm"),
        heights=unit(height_in * 2.54, "cm"),
        name="plot",
    )
    panel_vp = viewport(
        "panel",
        x=0.5,
        y=0.5,
        width=unit(1.0, "npc"),
        height=unit(1.0, "npc"),
        xscale=panel.x_range,
        yscale=panel.y_range,
        clip="on",
    )
    background = rect_grob(
        x=0.5, y=0.5, width=1.0, height=1.0, gp=gpar(fill=PANEL_COLOUR, col=None), vp=panel_vp
    )
    border = rect_grob(
        x=0.5,
        y=0.5,
        width=1.0,
        height=1.0,
        gp=gpar(fill=None, col="#000000", lwd=0.75),
        vp=panel_vp,
    )
    # 2×2：中间一条竖线 + 一条横线；四角再补细线，让面板内部也有可辨认的结构。
    grid = lines_grob(
        x=[0.0, 1.0, 0.5, 0.5, 0.25, 0.25, 0.75, 0.75],
        y=[0.5, 0.5, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0],
        gp=gpar(col=GRID_COLOUR, lwd=0.6),
        vp=panel_vp,
    )
    table = gtable_add_grob(table, background, t=1, l=1, name="panel-bg", z=-2)
    table = gtable_add_grob(table, border, t=1, l=1, name="panel-border", z=-1)
    table = gtable_add_grob(table, grid, t=1, l=1, name="panel-grid", z=0)
    tree = ViewportTree(Device(*DEVICE_IN))
    return scene(g_table_grob(table), tree).to_ir_scene(), panel


def render(ir_scene: Scene) -> tuple[bytes, bytes]:
    png = SkiaRasterDevice(*ir_scene.size, dpi=DPI).render(ir_scene)
    svg = SkiaSvgDevice(*ir_scene.size).render(ir_scene)
    return png, svg


# ---------------------------------------------------------------------------
# 测量
# ---------------------------------------------------------------------------


def measure_png(png: bytes) -> tuple[int, int]:
    """面板在 PNG 里的 `(宽, 高)` 像素：非白像素的外接框（网格线在内侧）。"""
    import skia

    image = skia.Image.MakeFromEncoded(png)
    if image is None:  # pragma: no cover - Skia 自己产出的 PNG 不会解不开
        raise RuntimeError("PNG 解码失败")
    pixels = np.array(image.toarray(), dtype=np.uint8, copy=True)[..., :3]
    ink = np.any(pixels < 250, axis=-1)
    if not ink.any():
        raise RuntimeError("PNG 里没有面板（全白）")
    rows, cols = np.nonzero(ink)
    return (int(cols.max() - cols.min() + 1), int(rows.max() - rows.min() + 1))


def _svg_colour(value: str) -> tuple[str, ...] | None:
    """SVG 颜色 → 可比较的规范形式；Skia 会把 `#DDE7F2` 缩成 `#DEF`。"""
    value = value.strip().lower()
    if value in ("none", "transparent"):
        return None
    match = re.fullmatch(r"#([0-9a-f]{3})", value)
    if match:
        return tuple(ch * 2 for ch in match.group(1))
    match = re.fullmatch(r"#([0-9a-f]{6})", value)
    if match:
        return tuple(match.group(1)[index : index + 2] for index in (0, 2, 4))
    return (value,)


def measure_svg(svg: bytes) -> tuple[float, float]:
    """面板底色矩形在 SVG 里的 `(宽, 高)`（pt）。"""
    root = ET.fromstring(svg)
    target = _svg_colour(PANEL_COLOUR)
    best: tuple[float, float] | None = None
    best_area = 0.0
    for element in root.iter():
        if not element.tag.endswith("rect"):
            continue
        if _svg_colour(element.get("fill", "")) != target:
            continue
        width = float(element.get("width", "0"))
        height = float(element.get("height", "0"))
        if width * height > best_area:
            best_area = width * height
            best = (width, height)
    if best is None:  # pragma: no cover - 场景里一定有面板底色
        raise RuntimeError("SVG 里找不到面板底色矩形")
    return best


# ---------------------------------------------------------------------------
# 验收
# ---------------------------------------------------------------------------


def run(check_only: bool = False, out: Path = OUT) -> list[str]:
    """渲染 + 测量；返回问题列表（空 = 通过）。"""
    problems: list[str] = []
    rows: list[str] = []
    for case in CASES:
        ir_scene, _panel = panel_scene(case.coord)
        png, svg = render(ir_scene)
        png_size = measure_png(png)
        svg_size = measure_svg(svg)
        expected = case.expected if case.expected is not None else DEVICE_IN[1] / DEVICE_IN[0]
        for label, (width, height) in (("PNG", png_size), ("SVG", svg_size)):
            ratio = height / width
            rows.append(
                f"{case.name:<18} {label} {width:>7.1f} × {height:>7.1f}  "
                f"高/宽 = {ratio:.4f}（期望 {expected:.4f}）"
            )
            if abs(ratio - expected) > 0.005 * expected:
                problems.append(
                    f"{case.name} {label}: 高/宽 = {ratio:.6f}，期望 {expected:.6f}（容差 0.5%）"
                )
        if case.name == "cartesian-control":
            control_ratio = png_size[1] / png_size[0]
            if abs(control_ratio - 1.0) < 0.1:
                problems.append(f"对照 case 的 PNG 高/宽 = {control_ratio:.4f}，被强行做成了 1.0")
        if not check_only:
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{case.name}.png").write_bytes(png)
            (out / f"{case.name}.svg").write_bytes(svg)
    if rows:
        print("\n".join(rows))
    if not check_only:
        print(f"wrote {out}/*.png|svg")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify coord_fixed panel aspect ratios.")
    parser.add_argument("--check", action="store_true", help="only verify, do not write files")
    parser.add_argument("--out", type=Path, default=OUT, help=f"output directory (default: {OUT})")
    args = parser.parse_args(argv)
    problems = run(check_only=args.check, out=args.out)
    if problems:
        for problem in problems:
            print(f"cases:coord: {problem}", file=sys.stderr)
        return 1
    print("cases:coord: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())

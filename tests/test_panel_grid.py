"""`panel.grid`（SIL-723）：位置与轴同源、继承 / blank / 线宽。

不依赖 R：位置断言用「面板 npc = 该面板标度的断点」这条同源口径（与
`axis_ticks()` 同一个 `scale.breaks()`），元素语义用主题解析后的 grob 形态
（`segments` + `lineend = butt`）来判。像素级对拍在
`docs/cases/theme-grey-basic` / `theme-minimal-basic` 的 diff 里。
"""

from __future__ import annotations

import numpy as np
import pytest

from ggcore.data import Column, ColumnTable
from ggcore.geom.scene import scene_from_plot
from ggcore.ir.nodes import NodeKind, walk
from ggcore.plot import aes, geom_point, ggplot, scale_x_continuous, scale_y_continuous
from ggcore.theme import element_blank, element_line, theme, theme_grey, theme_void

SIZE = {"width_in": 4.0, "height_in": 3.0}
GRID = (0.5, 0.25)  # theme_grey: major 0.5mm / minor 0.25mm（R 的 linewidth）
#: IR 的 `gpar.lwd` 是 R 的 lwd 单位（1/96 in）：1mm = 72/25.4 × 0.75。
LWD_PER_MM = 72.0 / 25.4 * 0.75


def table() -> ColumnTable:
    return ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0, 3.0, 4.0, 5.0]))),
            ("y", Column("float", np.array([2.1, 2.8, 3.2, 3.9, 4.5]))),
        ]
    )


def base(extra: object | None = None):
    plot = (
        ggplot(table(), aes(x="x", y="y"))
        + geom_point()
        + scale_x_continuous(limits=(0, 6), expand=(0, 0))
        + scale_y_continuous(limits=(1.5, 5.5), expand=(0, 0))
        + theme_grey()
    )
    return plot if extra is None else plot + extra  # type: ignore[operator]


def panel_box(scene) -> np.ndarray | None:
    """面板背景矩形的本地尺寸（左上有原点、y 向上的面板坐标系）；没有背景给 None。"""
    for node in walk(scene.root):
        if node.kind is NodeKind.RECT and tuple(node.gpar.fill) == (235, 235, 235, 255):
            return np.asarray(node.bufs["rect"][0], dtype=float)
    return None


def grid_segments(plot) -> list[tuple[np.ndarray, float]]:
    """面板坐标系里、`butt` 线端的 segments（= 网格线，不含面板外的轴刻度）。"""
    scene = scene_from_plot(plot, **SIZE)
    box = panel_box(scene)
    if box is None:
        return []
    _x0, _y0, width, height = box
    out: list[tuple[np.ndarray, float]] = []
    for node in walk(scene.root):
        if node.kind is not NodeKind.SEGMENTS:
            continue
        segments = np.asarray(node.bufs["segments"], dtype=float)
        if not np.all(np.isfinite(segments)):
            continue
        inside = (
            (segments[:, [0, 2]] >= -1e-6).all()
            and (segments[:, [0, 2]] <= width + 1e-6).all()
            and (segments[:, [1, 3]] >= -1e-6).all()
            and (segments[:, [1, 3]] <= height + 1e-6).all()
        )
        if inside:
            out.append((segments, float(node.gpar.lwd)))
    return out


def _vertical(segments: np.ndarray) -> bool:
    return bool(np.allclose(segments[:, 0], segments[:, 2]))


def _horizontal(segments: np.ndarray) -> bool:
    return bool(np.allclose(segments[:, 1], segments[:, 3]))


def test_theme_grey_draws_major_and_minor_grid() -> None:
    """4 条网格 grob：major/minor × x/y；线宽取主题的 0.5 / 0.25mm。"""
    found = grid_segments(base())
    assert len(found) == 4
    by_shape = {
        (axis, bool(np.isclose(lwd, 0.5 * LWD_PER_MM))): segments
        for segments, lwd in found
        for axis in ("vertical" if _vertical(segments) else "horizontal",)
    }
    # x 范围 0..6 → 7 根主线；y 范围 1.5..5.5 → 5 根主线（R 的 labeling::extended）。
    assert len(by_shape[("vertical", True)]) == 7
    assert len(by_shape[("horizontal", True)]) == 5
    # 次网格 = 相邻主断点的中点：x 6 根、y 4 根。
    assert len(by_shape[("vertical", False)]) == 6
    assert len(by_shape[("horizontal", False)]) == 4
    minor_widths = {lwd for segments, lwd in found if not np.isclose(lwd, 0.5 * LWD_PER_MM)}
    assert len(minor_widths) == 1
    assert next(iter(minor_widths)) == pytest.approx(0.25 * LWD_PER_MM)


def test_grid_positions_are_the_axis_breaks() -> None:
    """网格位置 = 该面板标度断落在面板 npc 上的位置（不另算一套断点）。"""
    from ggcore.axis import axis_ticks
    from ggcore.build import build_plot
    from ggcore.geom.scene import _panel_scale, _panels

    plot = base()
    build = build_plot(plot)
    ((panel, params),) = _panels(build)
    ticks = axis_ticks(_panel_scale(build, panel, "x"), params, "bottom")
    scene = scene_from_plot(plot, **SIZE)
    _x0, _y0, width, _height = panel_box(scene)
    vertical = [segments for segments, lwd in grid_segments(plot) if _vertical(segments)]
    # major 的 7 根：位置与轴刻度逐项相等（npc × 面板宽）。
    major = max(vertical, key=len)
    assert [float(x) / width for x in major[:, 0]] == pytest.approx(list(ticks.positions))
    # minor 在主断点中点。
    minor = min(vertical, key=len)
    middles = [(a + b) / 2.0 for a, b in zip(ticks.positions, ticks.positions[1:], strict=False)]
    assert [float(x) / width for x in minor[:, 0]] == pytest.approx(middles)


def test_blank_major_x_drops_only_vertical_lines() -> None:
    plot = base(theme(**{"panel.grid.major.x": element_blank()}))
    found = grid_segments(plot)
    vertical = [segments for segments, _lwd in found if _vertical(segments)]
    horizontal = [segments for segments, _lwd in found if _horizontal(segments)]
    # 竖线只剩 minor（6 根），横线原样（major 5 + minor 4）。
    assert [len(item) for item in vertical] == [6]
    assert sorted(len(item) for item in horizontal) == [4, 5]


def test_blank_panel_grid_removes_every_grid_line() -> None:
    assert grid_segments(base(theme(**{"panel.grid": element_blank()}))) == []


def test_theme_void_has_no_grid() -> None:
    plot = (
        ggplot(table(), aes(x="x", y="y"))
        + geom_point()
        + scale_x_continuous(limits=(0, 6), expand=(0, 0))
        + scale_y_continuous(limits=(1.5, 5.5), expand=(0, 0))
        + theme_void()
    )
    assert grid_segments(plot) == []


def test_grid_linewidth_follows_the_element() -> None:
    plot = base(theme(**{"panel.grid.major": element_line(linewidth=1.0)}))
    widths = [lwd for _segments, lwd in grid_segments(plot)]
    major = 1.0 * LWD_PER_MM
    assert widths.count(pytest.approx(major)) == 2  # x / y 各一条 grob
    assert len(widths) == 4
    # major 换了线宽，minor 仍是 rel(0.5) 解析出的 0.25mm。
    assert widths.count(pytest.approx(0.25 * LWD_PER_MM)) == 2

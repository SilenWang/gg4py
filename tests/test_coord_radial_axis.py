"""`coord_radial()` 的版式与轴体系（SIL-843）。

不依赖 R：几何断言直接用上游 SVG 量到的口径（面板 = 可用的正方形、背景是
「外圆 − 内孔」的圆环、次网格 `setdiff(major)` + r 次圆、r 轴读 `axis.*.r`）。
像素级对拍在 `docs/cases/upstream-guide-axis-theta-angle`。
"""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from ggcore.axis import axis_ticks
from ggcore.axis_guide import AxisSuffixTheme, axis_guide_extent, axis_guide_ticks, guide_for
from ggcore.build import build_plot
from ggcore.data import Column, ColumnTable
from ggcore.geom.scene import (
    _panel_scale,
    _panels,
    _radial_axis_theme,
    _theme_of,
    plot_layout,
    scene_from_plot,
)
from ggcore.ir.nodes import NodeKind
from ggcore.plot import aes, coord_radial, geom_point, ggplot, scale_x_continuous
from ggcore.theme import resolve_theme, theme_grey

SIZE = {"width_in": 10.0, "height_in": 8.0}
GREY = (235, 235, 235, 255)
#: R 的 pt 是 1/72.27 in（`axis.text.r` 的 margin 是 2.2 R-pt）。
PT_PER_CM = 72.27 / 2.54
WHITE = (255, 255, 255, 255)


def table() -> ColumnTable:
    return ColumnTable(
        [
            ("x", Column("float", np.array([0.0, 80.0, 160.0]))),
            ("y", Column("float", np.array([10.0, 20.0, 34.0]))),
        ]
    )


def radial():
    return (
        ggplot(table(), aes(x="x", y="y"))
        + geom_point()
        # 17 个主断点（0..160 每 10）→ 16 个次断点（中点）。
        + scale_x_continuous(breaks=list(range(0, 161, 10)))
        + coord_radial(inner_radius=0.5)
        + theme_grey()
    )


def _panel_leaves(plot) -> list:
    scene = scene_from_plot(plot, **SIZE)
    leaves: list = []

    def collect(node) -> None:
        if node.kind is NodeKind.VIEWPORT:
            for child in node.children:
                collect(child)
            return
        leaves.append(node)

    def find(node) -> bool:
        if node.kind is NodeKind.VIEWPORT and str(node.params.get("name") or "").startswith(
            "panel"
        ):
            collect(node)
            return True
        return any(find(child) for child in getattr(node, "children", ()) or ())

    find(scene.root)
    return leaves


def test_radial_panel_background_is_a_ring_not_a_square() -> None:
    """`guide_grid(square = FALSE)` 把 `panel.background` 换成双环 polygon。

    上游 SVG 的 `#EBEBEB` 是「外圆（`inner_radius[1]`）− 内孔
    （`inner_radius[0]`）」两段子路径；铺成外接方形会让四角与内孔都多出一圈灰底
    （SIL-843 实测：25.1% 的图级差异里约 18 个百分点来自这里）。
    """
    backgrounds = [
        node
        for node in _panel_leaves(radial())
        if node.kind in (NodeKind.PATH, NodeKind.POLYGON)
        and node.gpar is not None
        and tuple(node.gpar.fill) == GREY
    ]
    assert len(backgrounds) == 1
    node = backgrounds[0]
    points = np.asarray(node.bufs["points"], dtype=float)
    ids = np.asarray(node.bufs["id"], dtype=int)
    assert set(ids.tolist()) == {0, 1}, "应当是外圆 + 内孔两段子路径"
    radii = []
    for sub_id in (0, 1):
        sub = points[ids == sub_id]
        cx = (sub[:, 0].max() + sub[:, 0].min()) / 2
        cy = (sub[:, 1].max() + sub[:, 1].min()) / 2
        distances = np.hypot(sub[:, 0] - cx, sub[:, 1] - cy)
        assert distances.std() < 1e-3, f"子路径 {sub_id} 应当是正圆"
        radii.append(float(distances.mean()))
    # 两段子路径的半径比 = `inner_radius[1] : inner_radius[0]` = 0.4 : 0.2。
    assert radii[1] / radii[0] == pytest.approx(0.5, rel=1e-4)


def test_radial_minor_grid_drops_major_breaks_and_draws_r_minor_circles() -> None:
    """radial 的次网格走 `guide_grid()` 的两步：`setdiff(major)` + r 的次圆。

    `polar_minor_breaks()` 的序列里本来就含主断点（`regular_minor_breaks()` 的口径，
    `CoordPolar$render_bg()` 不筛）；radial 走 `guide_grid()` 要筛，否则主辐条被画
    两遍。r 的次圆是相邻主断点的中点（上游 6 主 + 5 次）。
    """
    circles = [
        node
        for node in _panel_leaves(radial())
        if node.kind is NodeKind.POLYLINE and tuple(node.gpar.col) == WHITE
    ]
    assert circles, "r 网格圆应当是 polyline"
    widths = sorted({round(float(node.gpar.lwd), 6) for node in circles})
    assert len(widths) == 2, "主圆与次圆各一种线宽"

    by_width: dict[float, list[float]] = {width: [] for width in widths}
    for node in circles:
        points = np.asarray(node.bufs["points"], dtype=float)
        radius = float(np.hypot(points[:, 0] - 0.5, points[:, 1] - 0.5).mean())
        by_width[round(float(node.gpar.lwd), 6)].append(radius)
    major = sorted(by_width[widths[1]])
    minor = sorted(by_width[widths[0]])
    assert len(major) >= 3 and len(minor) == len(major) - 1, "次圆 = 相邻主断点的中点"
    # 次圆严格落在两个主圆之间（`setdiff` 之后不会与主圆重合）。
    middles = [(low + high) / 2.0 for low, high in itertools.pairwise(major)]
    assert np.allclose(minor, middles, rtol=1e-3)
    assert widths[0] == pytest.approx(widths[1] / 2.0, rel=1e-6), "次圆线宽是主圆一半"


def test_radial_theta_minor_spokes_skip_the_major_breaks() -> None:
    """theta 次辐条要减去主断点（`guide_grid()` 的 `setdiff`）。

    17 个主断点 + 16 个中点 = 33 根；不筛的话次辐条会多出 17 根压在主辐条上
    （上游 SVG 里是 18 对 35）。
    """
    spokes = [
        node
        for node in _panel_leaves(radial())
        if node.kind is NodeKind.SEGMENTS and tuple(node.gpar.col) == WHITE
    ]
    assert len(spokes) == 2, "主辐条 / 次辐条各一个 segments grob"

    ordered = sorted(spokes, key=lambda node: -float(node.gpar.lwd))
    major = np.asarray(ordered[0].bufs["segments"], dtype=float)
    minor = np.asarray(ordered[1].bufs["segments"], dtype=float)
    assert len(major) == 17, "17 个主断点各一根辐条"
    # 中点序列（`regular_minor_breaks()`）两端各补一根、再减主断点 = 18。
    assert len(minor) == 18, "次辐条 = 35 个 `regular_minor_breaks()` 值减 17 个主断点"
    # 次辐条一根都不许落主辐条上（不 `setdiff` 时 17 根全重合）。
    major_starts = major[:, :2]
    for start in minor[:, :2]:
        assert not np.any(np.all(np.isclose(major_starts, start, atol=1e-3), axis=1)), (
            "次辐条与主辐条重合——`guide_grid()` 的 setdiff 没生效"
        )


def test_radial_r_axis_reads_the_r_theme_suffix() -> None:
    """r 轴读 `axis.*.r`（上游 `theme_suffix = "r"`），不是 `axis.*.y`。

    `axis.text.r` 两侧各 2.2pt margin 且 `hjust = 0.5`，`axis.text.y` 只有右侧
    margin。差这 2.2pt，整表居中后面板横移 1.1pt——上游 SVG 里
    `guide-axis-theta with angle adapting` 的 axis-l 列宽是 16.97pt。
    """
    build = build_plot(radial())
    ((_panel, params),) = _panels(build)
    theme = _theme_of(build)
    wrapped = _radial_axis_theme(theme, params)
    assert isinstance(wrapped, AxisSuffixTheme)
    assert wrapped.get("axis.text.y") is theme.get("axis.text.r")
    assert wrapped.get("axis.ticks.y") is theme.get("axis.ticks.r")
    assert wrapped.get("axis.ticks.length.y") is theme.get("axis.ticks.length.y")

    scale = _panel_scale(build, 1, params.scale_key("left"))
    guide = guide_for(build, "y")
    base = axis_ticks(scale, params, "left")
    with_r = axis_guide_extent(
        wrapped,
        axis_guide_ticks(scale, params, "left", guide, wrapped, base=base),
        guide,
        side="left",
    )
    plain = axis_guide_extent(
        theme,
        axis_guide_ticks(scale, params, "left", guide, theme, base=base),
        guide,
        side="left",
    )
    assert (with_r - plain) * PT_PER_CM == pytest.approx(2.2, abs=1e-6)


def test_radial_panel_is_a_square_of_the_available_height() -> None:
    """面板 = 扣掉标题 / xlab / ylab 后的正方形（`CoordRadial$aspect()` = 1）。

    上游 SVG 量到面板 cell = 535.15pt（plot.background 575.61×576 里的 data 区
    半径 214.06 = 0.4 × 535.15）。
    """
    build = build_plot(radial())
    layout = plot_layout(build, width_in=SIZE["width_in"], height_in=SIZE["height_in"])
    assert layout.panel_area.width_cm == pytest.approx(layout.panel_area.height_cm, abs=1e-6)
    top, bottom, _right, _left = layout.margin_cm
    available = SIZE["height_in"] * 2.54 - top - bottom - layout.title_cm - layout.x_title_cm
    assert layout.panel_area.height_cm == pytest.approx(available, abs=1e-6)
    assert resolve_theme(theme_grey()).get("axis.title.x") is not None

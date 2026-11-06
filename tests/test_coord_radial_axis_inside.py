"""`coord_radial()` 的次轴槽 / 面板内旋转轴 / 叠放（SIL-844）。

断言都用上游 SVG 量到的口径（`docs/notes/guide.md` §8.5.1）：`guides(r.sec=)`
占一条 axis-r 列、`r.axis.inside` 的数值形式折成 `axis_rotation`、逐 guide
`theme=` 只改自己那条轴的描边、`axis.text.r` 的 `hjust = 0.5` 让标签居中、
`guide_axis_stack("axis_theta", …)` 的第二圈沿半径外推。像素级对拍在
`docs/cases/upstream-coord-polar-*` 与 `upstream-guide-axis-stacked-radial-axes`。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from ggcore.axis import polar_r_ticks
from ggcore.axis_guide import (
    axis_guide_grobs,
    axis_guide_ticks,
    guide_axis,
    guide_axis_stack,
    guide_axis_theta,
    polar_axis_grobs,
)
from ggcore.build import build_plot
from ggcore.data import Column, ColumnTable
from ggcore.geom.scene import _panels, _theme_of, plot_layout, scene_from_plot
from ggcore.gtable import CellBox
from ggcore.ir.nodes import NodeKind
from ggcore.plot import (
    aes,
    coord_radial,
    geom_point,
    geom_text,
    ggplot,
    guides,
    scale_x_continuous,
)
from ggcore.theme import element_line, theme, theme_grey

SIZE = {"width_in": 10.0, "height_in": 8.0}


def _cm(value) -> float:
    """grob 里的 `Unit`（`default_units="cm"`）→ cm）。"""
    return float(value[0].amount)


def table() -> ColumnTable:
    return ColumnTable(
        [
            ("x", Column("float", np.array([0.0, 90.0, 180.0, 270.0, 360.0]))),
            ("y", Column("float", np.array([1.0, 5.0, 9.0, 13.0, 17.0]))),
        ]
    )


def radial(**kwargs):
    return ggplot(table(), aes(x="x", y="y")) + geom_point() + coord_radial(**kwargs) + theme_grey()


def _first_panel(plot):
    build = build_plot(plot)
    ((_panel, params),) = _panels(build)
    return build, params


#: `orchid` (#DA70D6) / `dodgerblue` (#1E90FF) 在 IR 里的 RGBA。
LIME = (218, 112, 214, 255)
BLUE = (30, 144, 255, 255)


def _segment_colours(scene) -> set[tuple]:
    out: set[tuple] = set()

    def walk(node) -> None:
        if node.kind is NodeKind.SEGMENTS and node.gpar is not None:
            colour = node.gpar.col
            out.add(tuple(colour) if not isinstance(colour, str) else colour.upper())
        for child in getattr(node, "children", ()) or ():
            walk(child)

    walk(scene.root)
    return out


def _segments(scene, colour: str) -> list:
    out: list = []

    def walk(node) -> None:
        if node.kind is NodeKind.SEGMENTS and node.gpar is not None:
            if str(node.gpar.col).lower() == colour.lower():
                out.append(node)
        for child in getattr(node, "children", ()) or ():
            walk(child)

    walk(scene.root)
    return out


def test_r_axis_inside_two_angles_feed_axis_rotation() -> None:
    """`r.axis.inside = c(90, 225)` → `axis_rotation = (π/2, 1.25π)`。

    上游 `setup_panel_params()`：数值形式先 `theta_scale$transform()` 再
    `oob_squish()` 再 `theta_rescale(…, arc, 1)`，结果 `rep_len(…, 2)` 给主轴 /
    次轴各一个角度；`render_fg()` 用它 `rotate_r_axis()`。
    """
    _build, params = _first_panel(radial(r_axis_inside=(90.0, 225.0)))
    polar = params.polar
    assert polar.r_axis_inside is True
    rng = polar.theta_range
    expected = [
        (value - rng[0]) / (rng[1] - rng[0]) * (polar.arc[1] - polar.arc[0]) + polar.arc[0]
        for value in (90.0, 225.0)
    ]
    assert polar.axis_rotation == pytest.approx(tuple(expected), rel=1e-9)


def test_r_axis_inside_scalar_and_bool() -> None:
    """标量 = 两条轴同一角度；`False` = 两条轴都在面板外（`axis_rotation` 退回 arc）。"""
    _build, params = _first_panel(radial(r_axis_inside=180.0))
    assert params.polar.r_axis_inside is True
    assert params.polar.axis_rotation[0] == pytest.approx(params.polar.axis_rotation[1])

    _build, params = _first_panel(radial(r_axis_inside=False))
    assert params.polar.r_axis_inside is False
    assert params.polar.axis_rotation == pytest.approx(params.polar.arc)


def test_r_axis_inside_out_of_range_angles_are_squished() -> None:
    """越界角度按 `oob_squish(…, only.finite = FALSE)` 夹到 theta 范围端点。

    上游 `setup_panel_params()` 的顺序是 `transform()` → `oob_squish()` →
    `theta_rescale()`；少了夹，`r.axis.inside = c(-1000, 1000)` 会把 r 轴转到
    arc 之外（partial arc 下直接跑到面板外）。
    """
    _build, params = _first_panel(
        radial(start=0.25 * math.pi, end=0.75 * math.pi, r_axis_inside=(-1000.0, 1000.0))
    )
    polar = params.polar
    assert polar.axis_rotation == pytest.approx(polar.arc)


def test_r_sec_takes_an_axis_r_column_only_when_outside() -> None:
    """`guides(r.sec = …)` 在面板外时占一条 axis-r 列；`r.axis.inside` 为真时不占。

    缺这条列整表会横移一个轴宽（SIL-843 实测 8.45pt）。
    """
    sec = guides(
        **{
            "r.sec": guide_axis(),
            "theta.sec": guide_axis_theta(),
        }
    )
    inside = radial(r_axis_inside=False) + sec
    build = build_plot(inside)
    layout = plot_layout(build, **SIZE)
    assert layout.y_axis_right_cm > 0
    assert layout.y_axis_cm > 0

    build = build_plot(radial(r_axis_inside=True) + sec)
    layout = plot_layout(build, **SIZE)
    # 面板内：两条 r 轴都不占 gtable 列，但 r.sec 的标题列还在。
    assert layout.y_axis_cm == 0.0
    assert layout.y_axis_right_cm == 0.0


def test_per_guide_theme_colours_only_that_axis_line() -> None:
    """`guides(r.sec = guide_axis(theme = theme(axis.line.r = …)))` 只改那一条轴线。"""
    plot = (
        radial(r_axis_inside=False)
        + guides(
            **{
                "r.sec": guide_axis(theme=theme(**{"axis.line.r": element_line(colour="orchid")})),
                "theta.sec": guide_axis_theta(),
            }
        )
        + theme(**{"axis.line.r": element_line(colour="dodgerblue")})
    )
    scene = scene_from_plot(plot, **SIZE)
    colours = _segment_colours(scene)
    assert LIME in colours and BLUE in colours, f"逐 guide theme= 没有生效：{sorted(colours)}"


def test_axis_text_r_labels_are_centred() -> None:
    """`axis.text.r` 的 `hjust = 0.5`：标签锚点比贴边口径多退半个文字宽。"""
    build, params = _first_panel(radial(r_axis_inside=False))
    theme_ = _theme_of(build)
    from ggcore.axis_guide import AxisSuffixTheme

    wrapped = AxisSuffixTheme(theme_, "r")
    from ggcore.geom.scene import _panel_scale

    scale = _panel_scale(build, 1, params.scale_key("left"))
    base = polar_r_ticks(scale, params, "left")
    ticks = axis_guide_ticks(scale, params, "left", guide_axis(), wrapped, base=base)
    assert ticks.hjust == pytest.approx(0.5)
    assert ticks.vjust == pytest.approx(0.5)

    box = CellBox(1, 1, 1, 1, 2.0, 2.0, 10.0, 10.0)
    grobs = axis_guide_grobs(wrapped, ticks, box, guide_axis(), name="r-axis")
    texts = [grob for grob in grobs if type(grob).__name__ == "TextGrob"]
    assert texts
    # 左侧轴：锚点 = 面板左沿 - 刻度 - 右 margin - 半个文字宽（`hjust = 0.5` 落在
    # 标签盒中心，不是贴边；差这半个文字宽整条 r 轴会偏 4.9pt）。
    from ggcore.axis import margin_sides_cm, text_width_cm, tick_length_cm

    _mt, mr, _mb, _ml = margin_sides_cm(wrapped.get("axis.text.r").margin)
    width = text_width_cm(texts[0].label[0], 8.8, None, "")
    assert _cm(texts[0].x) == pytest.approx(
        2.0 - tick_length_cm(wrapped, "left") - mr - width / 2, abs=1e-6
    )


def test_stacked_theta_guides_draw_two_rings() -> None:
    """`guide_axis_stack("axis_theta", guide_axis_theta())` 的第二圈沿半径外推。"""
    build, params = _first_panel(radial(inner_radius=0.5))
    theme_ = _theme_of(build)
    from ggcore.geom.scene import _panel_scale

    scale = _panel_scale(build, 1, params.polar.theta_axis)
    box = CellBox(1, 1, 1, 1, 0.0, 0.0, 20.0, 20.0)
    stacked = polar_axis_grobs(
        scale,
        params,
        theme_,
        box,
        guide_axis_stack("axis_theta", guide_axis_theta(cap="both")),
        name="theta",
    )
    single = polar_axis_grobs(
        scale, params, theme_, box, guide_axis_theta(cap="both"), name="theta-one"
    )
    texts = [grob for grob in stacked if type(grob).__name__ == "TextGrob"]
    one = [grob for grob in single if type(grob).__name__ == "TextGrob"]
    assert len(texts) == 2 * len(one)
    first = np.mean(
        [math.hypot(_cm(grob.x) - 10.0, _cm(grob.y) - 10.0) for grob in texts[: len(one)]]
    )
    second = np.mean(
        [math.hypot(_cm(grob.x) - 10.0, _cm(grob.y) - 10.0) for grob in texts[len(one) :]]
    )
    # 第二圈沿半径外推 `spacing + 上一层标签盒的半径投影`（上游 `GuideAxisStack$draw()`
    # 的 theta 分支）；只钉「确实外推了一个可见的量」，具体值由
    # `_theta_ring_extent()` 的标签盒投影决定（字体相关）。
    gap_pt = (second - first) * 28.3465
    assert 2.25 < gap_pt < 40.0
    assert second > first


def test_rotate_angle_rotates_text_with_theta() -> None:
    """`rotate.angle = TRUE` → `flip_data_text_angle()`：angle = angle - deg(theta)。"""
    data = ColumnTable(
        [
            ("x", Column("float", np.array([0.0, 30.0, 90.0]))),
            ("y", Column("float", np.array([1.0, 1.0, 1.0]))),
            ("lab", Column("str", np.array(["a", "b", "c"]))),
        ]
    )
    plot = (
        ggplot(data, aes(x="x", y="y", label="lab"))
        + geom_text(angle=0.0)
        + scale_x_continuous(expand=(0.0, 0.0))
        + coord_radial(rotate_angle=True)
    )
    angles = sorted(
        round(float(node.params["angle"]), 6)
        for node in _text_nodes(scene_from_plot(plot, **SIZE))
        if node.texts and node.texts[0] in ("a", "b", "c")
    )
    # theta = 0 / 120° / 240°：angle = (0 - theta) mod 360 → 0 / 240 / 120；落在
    # (90, 270) 的两个各 +180（R 的 `flip_text_angle()` 不重新取模，所以是 420 / 300）。
    # 角度相同的标签会合成一个 grob：0 与 0 一组合并，剩两组。
    assert angles == pytest.approx([0.0, 420.0], abs=1e-6)

    # 关掉 `rotate.angle` 时文字保持 `angle` 美学原值。
    plain = (
        ggplot(data, aes(x="x", y="y", label="lab"))
        + geom_text(angle=0.0)
        + scale_x_continuous(expand=(0.0, 0.0))
        + coord_radial()
    )
    plain_angles = [
        float(node.params["angle"])
        for node in _text_nodes(scene_from_plot(plain, **SIZE))
        if node.texts and node.texts[0] in ("a", "b", "c")
    ]
    assert plain_angles == pytest.approx([0.0])


def _text_nodes(scene) -> list:
    out: list = []

    def walk(node) -> None:
        if node.kind is NodeKind.TEXT:
            out.append(node)
        for child in getattr(node, "children", ()) or ():
            walk(child)

    walk(scene.root)
    return out


def test_partial_arc_background_is_a_sector_not_a_full_ring() -> None:
    """partial arc 的 `panel.background` 是环形扇区（一段闭合子路径）。"""
    plot = radial(start=0.25 * math.pi, end=0.75 * math.pi, inner_radius=0.3)
    scene = scene_from_plot(plot, **SIZE)
    backgrounds = [
        node
        for node in _panel_backgrounds(scene)
        if node.gpar is not None
        and node.gpar.fill is not None
        and tuple(node.gpar.fill) == (235, 235, 235, 255)
    ]
    assert backgrounds
    node = backgrounds[0]
    ids = node.bufs.get("id")
    subpaths = 1 if ids is None else len(set(np.asarray(ids, dtype=int).tolist()))
    assert subpaths == 1, "部分弧只有一段闭合子路径（外弧 + 内弧回程）"
    points = np.asarray(node.bufs["points"], dtype=float)
    # 外弧 179 段 + 内弧 179 段 = 358 个顶点（满圆是两段各自闭合的 179 点）。
    assert points.shape[0] == 358


def _panel_backgrounds(scene) -> list:
    out: list = []

    def collect(node) -> None:
        if node.kind is not NodeKind.VIEWPORT:
            out.append(node)
            return
        for child in node.children:
            collect(child)

    def find(node) -> bool:
        name = str(node.params.get("name") or "")
        if node.kind is NodeKind.VIEWPORT and name.startswith("panel"):
            collect(node)
            return True
        return any(find(child) for child in getattr(node, "children", ()) or ())

    find(scene.root)
    return out


def test_sf_degree_labels_are_three_character_nodes() -> None:
    """ "80°W" 拆成三个节点（上游是 plotmath 的 `"80" * degree * W`）。"""
    from ggcore.axis_guide import _degree_label_grobs

    grobs = _degree_label_grobs(
        "80°W",
        10.0,
        5.0,
        hjust=0.0,
        vjust=1.0,
        angle=315.0,
        gp={"fontsize": 8.8},
        family="",
        size=8.8,
        metrics=None,
        name="label",
    )
    assert [grob.label[0] for grob in grobs] == ["80", "°", "W"]
    xs = [_cm(grob.x) for grob in grobs]
    # 三个节点沿 45° 基线依次排开（x 单调增、y 单调减：`rot = 315`）。
    assert xs[0] < xs[1] < xs[2]
    ys = [_cm(grob.y) for grob in grobs]
    assert ys[0] > ys[1] > ys[2]

"""guides 长尾（M2-S2 / SIL-739）的单元口径。

R 对拍在 `tests/test_guide_long_r_parity.py`；这里钉住：

- `guide_colourbar` 4.0.3 的参数面（display / nbin 默认 / title.position /
  ticks.colour / frame.colour / draw.ulim / draw.llim / 旧写法 raster）；
- `guide_bins` / `guide_coloursteps` 的训练形状（箱数、边界标签、低值在上）；
- 轴 guide 的工厂、component 转换与 `guide_axis_stack` 的叠放；
- `annotation_logticks()` 与 `calc_logticks()`（R 的同名函数）。
"""

from __future__ import annotations

import numpy as np
import pytest

from ggcore import registry
from ggcore.annotations import LogticksAnnotation, annotation_logticks, calc_logticks
from ggcore.axis_guide import (
    axis_guide_from_component,
    axis_guide_ticks,
    guide_axis,
    guide_axis_logticks,
    guide_axis_stack,
    guide_axis_theta,
)
from ggcore.build import build_plot
from ggcore.components import Guide as GuideComponent
from ggcore.data import Column, ColumnTable
from ggcore.geom.scene import plot_layout, scene_from_plot
from ggcore.guide import (
    BinnedKeys,
    GuideBins,
    GuideColoursteps,
    GuideError,
    build_guides,
    guide_colourbar,
    guide_from_component,
    legend_layout,
)
from ggcore.ir.nodes import NodeKind, walk
from ggcore.plot import aes, ggplot
from ggcore.theme import element_line, resolve_theme
from ggcore.theme import theme as make_theme

SIZE = {"width_in": 4.0, "height_in": 3.0}


def _table() -> ColumnTable:
    return ColumnTable(
        [
            ("x", Column("float", np.array([1.5, 1.8, 2.2, 2.6, 3.0]))),
            ("y", Column("float", np.array([26.0, 25.0, 24.5, 23.0, 22.5]))),
            (
                "g",
                Column(
                    "categorical",
                    np.array([0, 1, 2, 0, 1], dtype=np.int32),
                    levels=("a", "b", "c"),
                ),
            ),
            ("v", Column("float", np.array([120.0, 160.0, 200.0, 260.0, 340.0]))),
        ]
    )


def _colour_plot():
    return (
        ggplot(_table(), aes(x="x", y="y", colour="v"))
        + registry.geom_point()
        + registry.labs(x="X", y="Y")
    )


# ---------------------------------------------------------------------------
# guide_colourbar 的参数面
# ---------------------------------------------------------------------------


def test_colourbar_display_and_nbin_defaults() -> None:
    assert guide_colourbar().nbin == 300
    assert guide_colourbar(display="gradient").nbin == 15
    assert guide_colourbar(nbin=8, display="rectangles").nbin == 8
    # 4.0.3 的旧写法 `raster=FALSE` 折成 display="rectangles"。
    assert guide_colourbar(raster=False).display == "rectangles"
    assert guide_colourbar(raster=True).display == "raster"
    with pytest.raises(GuideError, match="display"):
        guide_colourbar(display="bitmap")
    with pytest.raises(GuideError, match=r"title\.position"):
        guide_colourbar(title_position="middle")
    with pytest.raises(GuideError, match="alpha"):
        guide_colourbar(alpha=1.5)


def test_colourbar_accepts_dotted_argument_names() -> None:
    guide = guide_colourbar(**{"ticks.colour": "#123456", "frame.colour": "#654321"})
    assert guide.ticks_colour == "#123456"
    assert guide.frame_colour == "#654321"
    with pytest.raises(GuideError, match="不认识"):
        guide_colourbar(unknown=1)


def test_guide_components_map_new_names() -> None:
    kind = guide_from_component(GuideComponent(name="bins", aesthetic="colour"))
    assert isinstance(kind, GuideBins)
    steps = guide_from_component(GuideComponent(name="coloursteps", aesthetic="colour"))
    assert isinstance(steps, GuideColoursteps) and steps.even_steps
    alias = guide_from_component(GuideComponent(name="colorsteps", aesthetic="colour"))
    assert isinstance(alias, GuideColoursteps)
    with pytest.raises(GuideError, match="bins"):
        guide_from_component(GuideComponent(name="bins_unknown"))


# ---------------------------------------------------------------------------
# bins / coloursteps 的训练
# ---------------------------------------------------------------------------


def test_bins_keys_have_one_more_row_than_bins() -> None:
    build = build_plot(_colour_plot() + registry.guide_bins("colour", show_limits=True))
    guides = build_guides(build)
    assert isinstance(guides[0].guide, GuideBins)
    bins = guides[0].bins
    assert isinstance(bins, BinnedKeys)
    assert bins.bins >= 1
    assert len(bins.edges) == bins.bins + 1
    assert len(bins.labels) == bins.bins + 1
    assert len(guides[0].keys) == bins.bins + 1
    assert guides[0].keys[-1].values["colour"] is None
    assert bins.show_limits == (True, True)


def test_bins_layout_puts_low_values_at_the_top() -> None:
    """R 的 `GuideBins$build_labels()` 先 `1 - .value`，竖排时低值在**上**。"""
    build = build_plot(_colour_plot() + registry.guide_bins("colour", show_limits=True))
    guides = build_guides(build)
    theme = resolve_theme(build.theme)
    layout = legend_layout(guides[0], theme, "right")
    boxes = [cell.box.y_cm for cell in layout.keys]
    assert boxes == sorted(boxes, reverse=True)


def test_coloursteps_layout_labels_every_bin_edge() -> None:
    build = build_plot(_colour_plot() + registry.guide_coloursteps("colour", show_limits=True))
    guides = build_guides(build)
    assert isinstance(guides[0].guide, GuideColoursteps)
    theme = resolve_theme(build.theme)
    layout = legend_layout(guides[0], theme, "right")
    bar = layout.bar
    assert bar is not None
    assert layout.ticks
    for position, _label in layout.ticks:
        assert bar.y_cm - 1e-9 <= position <= bar.y_cm + bar.height_cm + 1e-9


def test_uneven_coloursteps_uses_data_spacing() -> None:
    build = build_plot(_colour_plot() + registry.guide_coloursteps("colour", even_steps=False))
    bins = build_guides(build)[0].bins
    assert bins is not None and bins.even is False
    widths = [high - low for low, high in bins.bin_bounds()]
    assert len({round(width, 6) for width in widths}) > 1


# ---------------------------------------------------------------------------
# 轴 guide
# ---------------------------------------------------------------------------


def test_axis_guide_factories_validate() -> None:
    assert guide_axis(n_dodge=3).n_dodge == 3
    with pytest.raises(ValueError, match=r"n\.dodge"):
        guide_axis(n_dodge=0)
    with pytest.raises(ValueError, match="cap"):
        guide_axis(cap="middle")
    assert guide_axis_logticks().is_logticks
    # `preserve` 是本仓的别名：top / bottom → cap upper / lower。
    assert guide_axis_logticks(preserve="top").cap == "upper"
    assert guide_axis_logticks(preserve="bottom").cap == "lower"
    stack = guide_axis_stack(guide_axis(), guide_axis_logticks())
    assert stack.is_stack and len(stack.guides) == 2
    assert guide_axis_theta().is_theta


def test_axis_guide_from_component_roundtrip() -> None:
    component = GuideComponent(
        name="axis",
        aesthetic="x",
        params={"angle": 45, "check.overlap": True, "n.dodge": 2},
    )
    guide = axis_guide_from_component(component)
    assert guide is not None
    assert guide.angle == 45 and guide.check_overlap and guide.n_dodge == 2
    stack = axis_guide_from_component(
        GuideComponent(
            name="axis_stack",
            aesthetic="x",
            params={
                "first": GuideComponent(name="axis", params={}),
                "guide": GuideComponent(name="axis_logticks", params={}),
            },
        )
    )
    assert stack is not None and len(stack.guides) == 2


def test_axis_angle_and_dodge_change_the_extent() -> None:
    build = build_plot(_colour_plot())
    theme = resolve_theme(build.theme)
    params = build.panels[0].panel_params
    scale = build.panels[0].scales.scale("x")
    base = axis_guide_ticks(scale, params, "bottom", guide_axis(), theme)
    rotated = axis_guide_ticks(scale, params, "bottom", guide_axis(angle=45), theme)
    assert rotated.angle == 45
    assert base.angle == 0.0
    assert guide_axis(n_dodge=2).n_dodge == 2


def test_layout_uses_axis_guide_from_plot() -> None:
    plain = plot_layout(build_plot(_colour_plot()))
    rotated = plot_layout(build_plot(_colour_plot() + registry.guide_axis("x", angle=45)))
    assert rotated.x_axis_cm > plain.x_axis_cm


# ---------------------------------------------------------------------------
# annotation_logticks
# ---------------------------------------------------------------------------


def test_annotation_logticks_params() -> None:
    annotation = annotation_logticks(sides="bl", short=0.2, mid=0.4, long=0.6)
    assert isinstance(annotation, LogticksAnnotation)
    assert annotation.sides == "bl"
    assert annotation.short_cm == pytest.approx(0.2)
    assert annotation.long_cm == pytest.approx(0.6)
    with pytest.raises(ValueError, match="sides"):
        annotation_logticks(sides="x")
    with pytest.raises(ValueError, match="base"):
        annotation_logticks(base=1)


def test_calc_logticks_three_lengths() -> None:
    ticks, ends = calc_logticks(10, 0, 2, shortend=0.1, midend=0.2, longend=0.3)
    assert ticks.tolist() == [
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        20,
        30,
        40,
        50,
        60,
        70,
        80,
        90,
        100,
    ]
    # 1 / 10 / 100 是 long，5 / 50 是 mid，其余 short。
    assert ends[0] == pytest.approx(0.3)
    assert ends[4] == pytest.approx(0.2)
    assert ends[1] == pytest.approx(0.1)
    assert ends[-1] == pytest.approx(0.3)


def test_annotation_is_drawn_on_log_axis() -> None:
    plot = _colour_plot() + registry.scale_x_log10() + annotation_logticks(sides="b")
    scene = scene_from_plot(plot, **SIZE)
    names = {node.kind for node in walk(scene.root)}
    assert NodeKind.SEGMENTS in names
    build = build_plot(plot)
    assert len(build.annotations) == 1


def test_axis_theta_labels_are_drawn() -> None:
    plot = (
        ggplot(_table(), aes(x="g", y="y"))
        + registry.geom_col()
        + registry.coord_polar()
        + registry.guide_axis_theta("theta")
    )
    scene = scene_from_plot(plot, **SIZE)
    texts = [node for node in walk(scene.root) if node.kind is NodeKind.TEXT]
    assert texts


# ---------------------------------------------------------------------------
# cap=（轴线端点）/ theta 次刻度 / 分箱 reverse
# ---------------------------------------------------------------------------


def _amounts(unit: object) -> list[float]:
    return [float(element.amount) for element in unit.elements]


def _axis_line_grobs(plot, panel_index: int = 0):
    from ggcore.geom.scene import _axis_grobs, _theme_of

    build = build_plot(plot)
    layout = plot_layout(build, **SIZE)
    grobs = _axis_grobs(build, _theme_of(build), layout, None)
    box = list(layout.panel_boxes.values())[panel_index]
    lines = {}
    for grob in grobs:
        name = str(getattr(grob, "name", ""))
        if name.startswith("axis-line-") and name.endswith(("-bottom", "-left")):
            lines[name.rsplit("-", 1)[1]] = grob
    return lines, box


def _line_plot(cap: str):
    return (
        _colour_plot()
        + make_theme(**{"axis.line": element_line(colour="black")})
        + registry.guide_axis("x", cap=cap)
        + registry.guide_axis("y", cap=cap)
    )


def test_axis_cap_trims_the_axis_line() -> None:
    """`cap=` 四态改 axis.line 的端点（R 的 `GuideAxis$extract_decor()`）。"""
    full, box = _axis_line_grobs(_line_plot("none"))
    left = _amounts(full["bottom"].x0)[0]
    right = _amounts(full["bottom"].x1)[0]
    assert left == pytest.approx(box.x_cm)
    assert right == pytest.approx(box.x_cm + box.width_cm)

    upper, _ = _axis_line_grobs(_line_plot("upper"))
    assert _amounts(upper["bottom"].x0)[0] == pytest.approx(left)
    assert _amounts(upper["bottom"].x1)[0] < right

    lower, _ = _axis_line_grobs(_line_plot("lower"))
    assert _amounts(lower["bottom"].x0)[0] > left
    assert _amounts(lower["bottom"].x1)[0] == pytest.approx(right)

    both, _ = _axis_line_grobs(_line_plot("both"))
    assert _amounts(both["bottom"].x0)[0] > left
    assert _amounts(both["bottom"].x1)[0] < right

    # 竖向轴同样收：`axis.line.y` 的 y 端点。
    y_full = _amounts(full["left"].y0)[0]
    y_both = _amounts(both["left"].y0)[0]
    assert y_both > y_full


def test_axis_cap_preserve_alias_maps_to_cap() -> None:
    assert guide_axis_logticks(preserve="top").cap == "upper"
    assert guide_axis_logticks(preserve="bottom").cap == "lower"
    assert guide_axis_logticks(preserve="both").cap == "both"


def test_axis_theta_minor_ticks_are_drawn() -> None:
    def segments(minor: bool) -> int:
        plot = (
            ggplot(_table(), aes(x="x", y="y"))
            + registry.geom_point()
            + registry.coord_radial()
            + registry.guide_axis_theta("theta", minor_ticks=minor)
        )
        scene = scene_from_plot(plot, **SIZE)
        return sum(1 for node in walk(scene.root) if node.kind is NodeKind.SEGMENTS)

    assert segments(True) > segments(False)


def test_bins_reverse_mirrors_keys_and_labels() -> None:
    build = build_plot(_colour_plot() + registry.guide_bins("colour", reverse=True))
    guide_build = next(item for item in build_guides(build) if item.kind == "bins")
    layout = legend_layout(guide_build, resolve_theme(build.theme), metrics=None)

    plain_build = build_plot(_colour_plot() + registry.guide_bins("colour"))
    plain = next(item for item in build_guides(plain_build) if item.kind == "bins")
    plain_layout = legend_layout(plain, resolve_theme(plain_build.theme), metrics=None)

    # 键格：颜色与标签一起镜像（R 的 `extract_params()` 倒序 + 列左旋）。
    values = [cell.key.values["colour"] for cell in layout.keys]
    assert values == list(reversed([cell.key.values["colour"] for cell in plain_layout.keys]))
    assert [cell.key.label for cell in layout.keys] == sorted(
        [cell.key.label for cell in layout.keys], reverse=True
    )
    # 刻度：位置仍升序，但上下端对调——plain 的最大标签在顶，reverse 的在底。
    plain_top = max(plain_layout.ticks, key=lambda item: item[0])[1]
    reverse_top = max(layout.ticks, key=lambda item: item[0])[1]
    ticks_labels = [label for _position, label in layout.ticks]
    assert reverse_top == max(ticks_labels)  # R 的 reverse：高值在上
    assert plain_top == min(label for _position, label in plain_layout.ticks)

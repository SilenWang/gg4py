"""图例（M1-11）：guide 数据对象、合并规则、key 尺寸与 key grob。

对拍 R 的尺寸 / 断点在 `tests/test_guide_r_parity.py`；这里钉口径：

- `guide_legend` / `guide_colourbar` / `guide_none` 的参数校验；
- 合并规则（同一美学只有一个 guide；title + 键标签 + 类型相同才合并）；
- key 尺寸（`legend.key.size` = 1.2 lines = 0.6096cm）、竖向无行距、横向 spacing.x；
- 9 个 geom 都能用 `Geom.draw()` 画出 key（不另写形状代码）；
- 未实现项明确报错（`guide_bins` / `legend.position="inside"` / 连续标度配 colourbar 之外的错配）。
"""

from __future__ import annotations

import hashlib
import importlib.util
import warnings
from pathlib import Path

import numpy as np
import pytest

from ggcore import ir, registry
from ggcore.build import build_plot
from ggcore.data import Column, ColumnTable
from ggcore.geom.scene import plot_layout, scene_from_plot
from ggcore.grobs import rect_grob, text_grob
from ggcore.guide import (
    AUTO,
    Guide,
    GuideColourbar,
    GuideCustom,
    GuideError,
    GuideLegend,
    GuideNone,
    build_guides,
    guide_colourbar,
    guide_custom,
    guide_from_component,
    guide_legend,
    guide_none,
    key_table,
    legend_box_layout,
    legend_grob,
    legend_layout,
)
from ggcore.plot import aes, ggplot, guides
from ggcore.theme import Theme, element_text, margin, resolve_theme
from ggcore.theme import theme as make_theme
from ggcore.units import UnitContext, convert_height, convert_width, unit
from ggcore.viewport import gpar


class FakeMetrics:
    def strwidth(self, text: str, *, fontsize: float, cex: float, font: str = "sans") -> float:
        del font
        return 0.5 * float(fontsize) * float(cex) * len(text) / 72.0

    def strheight(self, text: str, *, fontsize: float, cex: float, font: str = "sans") -> float:
        del text, font
        return 0.955 * float(fontsize) * float(cex) / 72.0


METRICS = FakeMetrics()


def data() -> ColumnTable:
    return ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]))),
            ("y", Column("float", np.array([2.0, 4.0, 3.0, 5.0, 6.0, 7.0]))),
            (
                "g",
                Column(
                    "categorical",
                    np.array([0, 1, 2, 0, 1, 2], dtype=np.int32),
                    levels=("a", "b", "c"),
                ),
            ),
            (
                "h",
                Column(
                    "categorical",
                    np.array([0, 0, 1, 1, 2, 2], dtype=np.int32),
                    levels=("p", "q", "r"),
                ),
            ),
        ]
    )


def _theme() -> Theme:
    return Theme()


def _layout(plot, *, position: str | None = "right", metrics=METRICS):
    build = build_plot(plot)
    theme_resolved = resolve_theme(build.theme if isinstance(build.theme, Theme) else Theme())
    guides = build_guides(build)
    return (
        build,
        theme_resolved,
        guides,
        [legend_layout(guide, theme_resolved, position, metrics=metrics) for guide in guides],
    )


# ---------------------------------------------------------------------------
# 工厂 / 校验
# ---------------------------------------------------------------------------


def test_guide_factories_and_validation() -> None:
    legend = guide_legend(title="C", nrow=2, byrow=True, reverse=True)
    assert isinstance(legend, GuideLegend)
    assert legend.kind == "legend" and legend.title == "C" and legend.nrow == 2 and legend.byrow
    assert guide_legend().title is AUTO
    bar = guide_colourbar(nbin=64, barheight=unit(2, "cm"))
    assert isinstance(bar, GuideColourbar) and bar.nbin == 64
    assert isinstance(guide_none(), GuideNone)

    with pytest.raises(GuideError, match="direction"):
        guide_legend(direction="diagonal")
    with pytest.raises(GuideError, match="正整数"):
        guide_legend(nrow=0)
    with pytest.raises(GuideError, match="nbin"):
        guide_colourbar(nbin=1)


def test_guide_from_component_maps_registry_names() -> None:
    component = registry.guide_legend("colour", title="G")
    guide = guide_from_component(component)
    assert isinstance(guide, GuideLegend) and guide.title == "G"
    assert isinstance(guide_from_component(registry.guide_none("fill")), GuideNone)
    assert isinstance(guide_from_component(registry.guide_colourbar("colour")), GuideColourbar)
    # 未知 guide 名字点名报错（guide_bins 未实现）。
    unknown = registry.guide("guide_bins") if hasattr(registry, "guide") else None
    del unknown
    from ggcore.components import Guide as GuideComponent

    with pytest.raises(GuideError, match="guide_bins"):
        guide_from_component(GuideComponent(name="guide_bins"))


# ---------------------------------------------------------------------------
# 合并规则
# ---------------------------------------------------------------------------


def test_single_colour_guide() -> None:
    plot = ggplot(data(), aes(x="x", y="y", colour="g")) + registry.geom_point()
    _build, _theme_value, guides, layouts = _layout(plot)
    assert len(guides) == 1
    guide = guides[0]
    assert guide.aesthetics == ("colour",)
    assert guide.title == "g"
    assert [key.label for key in guide.keys] == ["a", "b", "c"]
    assert guide.layers == (0,)
    # 三个 key 的竖直排列：无行距，key 高 = legend.key.size = 1.2 lines。
    layout = layouts[0]
    assert len(layout.keys) == 3
    key_cm = 1.2 * 12 * 1.2 / 72 * 2.54
    assert layout.keys[0].box.height_cm == pytest.approx(key_cm)
    assert layout.keys[1].box.y_cm == pytest.approx(layout.keys[0].box.y_cm - key_cm)


def test_colour_and_fill_on_different_variables_are_two_guides() -> None:
    plot = ggplot(data(), aes(x="x", y="y", colour="g", fill="h")) + registry.geom_point(shape=21)
    _build, _theme_value, guides, layouts = _layout(plot)
    assert [guide.aesthetics for guide in guides] == [("colour",), ("fill",)]
    assert [guide.title for guide in guides] == ["g", "h"]
    for guide in guides:
        assert len(guide.keys) == 3
    # 两张图例各自 3 行 key。
    assert [len(layout.keys) for layout in layouts] == [3, 3]


def test_colour_and_shape_on_the_same_variable_merge() -> None:
    plot = ggplot(data(), aes(x="x", y="y", colour="g", shape="g")) + registry.geom_point()
    _build, _theme_value, guides, layouts = _layout(plot)
    assert len(guides) == 1
    guide = guides[0]
    assert guide.aesthetics == ("colour", "shape")
    assert [key.label for key in guide.keys] == ["a", "b", "c"]
    # 合并后的键同时带 colour 与 shape；图层只保留一次。
    assert set(guide.keys[0].values) == {"colour", "shape"}
    assert guide.layers == (0,)
    assert len(layouts[0].keys) == 3


def test_merge_requires_same_title_and_labels() -> None:
    # 两个变量恰好同标签时 R 也合并（hashables = title + labels + name）；
    # 这里让 h 的标签不同，确保不合并。
    table = data()
    plot = ggplot(table, aes(x="x", y="y", colour="g", fill="h")) + registry.geom_point(shape=21)
    build = build_plot(plot)
    guides = build_guides(build)
    assert len(guides) == 2


def test_guide_none_and_show_legend_false() -> None:
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="g"))
        + registry.geom_point()
        + registry.guide_none("colour")
    )
    assert build_guides(build_plot(plot)) == ()

    hidden = ggplot(data(), aes(x="x", y="y", colour="g")) + registry.geom_point(show_legend=False)
    assert build_guides(build_plot(hidden)) == ()


def test_labs_none_removes_the_title() -> None:
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="g"))
        + registry.geom_point()
        + registry.labs(colour=None)
    )
    guide = build_guides(build_plot(plot))[0]
    assert guide.title is None
    # 标题为 None 时图例少一行标题。
    layout = _layout(plot)[3][0]
    assert layout.title_box is None


def test_guide_title_override_wins_over_the_mapping() -> None:
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="g"))
        + registry.geom_point()
        + registry.guide_legend("colour", title="Group")
    )
    guide = build_guides(build_plot(plot))[0]
    assert guide.title == "Group"


def test_reverse_orders_keys() -> None:
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="g"))
        + registry.geom_point()
        + registry.guide_legend("colour", reverse=True)
    )
    guide = build_guides(build_plot(plot))[0]
    assert [key.label for key in guide.keys] == ["c", "b", "a"]


# ---------------------------------------------------------------------------
# key 尺寸 / 排列
# ---------------------------------------------------------------------------


def test_key_size_follows_legend_key_size() -> None:
    plot = ggplot(data(), aes(x="x", y="y", colour="g")) + registry.geom_point()
    _build, theme_value, _guides, layouts = _layout(plot)
    layout = layouts[0]
    key_w = convert_width(theme_value["legend.key.width"], "cm", ctx=UnitContext())
    key_h = convert_height(theme_value["legend.key.height"], "cm", ctx=UnitContext())
    assert float(np.asarray(key_w).sum()) == pytest.approx(0.6096)
    assert float(np.asarray(key_h).sum()) == pytest.approx(0.6096)
    assert layout.keys[0].box.width_cm == pytest.approx(0.6096)
    assert layout.width_cm == pytest.approx(
        layout.keys[0].box.width_cm + 0.1933 + layout.keys[0].label_box.width_cm + 0.3866,
        rel=1e-5,
    )


def test_guide_keywidth_override_and_horizontal_direction() -> None:
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="g"))
        + registry.geom_point()
        + registry.guide_legend("colour", keywidth=unit(1.0, "cm"))
    )
    build = build_plot(plot)
    theme_value = resolve_theme(Theme())
    guide = build_guides(build)[0]
    vertical = legend_layout(guide, theme_value, "right", metrics=METRICS)
    assert vertical.keys[0].box.width_cm == pytest.approx(1.0)
    horizontal = legend_layout(guide, theme_value, "bottom", metrics=METRICS)
    assert horizontal.direction == "horizontal"
    # 横向：三个 key 排一行，标签在各自 key 右侧。
    xs = [cell.box.x_cm for cell in horizontal.keys]
    assert xs == sorted(xs) and len(set(xs)) == 3
    assert horizontal.keys[0].label_box.x_cm > horizontal.keys[0].box.x_cm
    assert horizontal.width_cm > vertical.width_cm
    assert horizontal.height_cm < vertical.height_cm


def test_ncol_arranges_keys_in_a_grid() -> None:
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="g"))
        + registry.geom_point()
        + registry.guide_legend("colour", ncol=2)
    )
    _build, theme_value, guides, _layouts = _layout(plot)
    layout = legend_layout(guides[0], theme_value, "right", metrics=METRICS)
    # 3 个 key、ncol = 2 → 2 行（先按列铺：第 1 列 2 个、第 2 列 1 个）。
    rows = sorted({round(cell.box.y_cm, 9) for cell in layout.keys})
    assert len(rows) == 2
    columns = sorted({round(cell.box.x_cm, 9) for cell in layout.keys})
    assert len(columns) == 2


def test_colourbar_layout_and_ticks() -> None:
    plot = ggplot(data(), aes(x="x", y="y", colour="y")) + registry.geom_point()
    _build, _theme_value, guides, layouts = _layout(plot)
    guide = guides[0]
    assert isinstance(guide.guide, GuideColourbar)
    layout = layouts[0]
    assert layout.bar is not None
    # 色条：宽 = legend.key.width，高 = 5 × legend.key.height（R 4.0.3 的默认）。
    assert layout.bar.width_cm == pytest.approx(0.6096)
    assert layout.bar.height_cm == pytest.approx(5 * 0.6096)
    # 刻度按断点在 limits 里的位置排（自下而上）。
    ys = [y for y, _label in layout.ticks]
    assert ys == sorted(ys)
    assert [label for _y, label in layout.ticks] == [key.label for key in guide.keys]


def test_colourbar_rejects_discrete_scales() -> None:
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="g"))
        + registry.geom_point()
        + registry.guide_colourbar("colour")
    )
    with pytest.raises(GuideError, match="连续标度"):
        build_guides(build_plot(plot))


# ---------------------------------------------------------------------------
# key grob：9 个 geom 都复用 Geom.draw()
# ---------------------------------------------------------------------------


def _geom_plots() -> dict[str, object]:
    table = data()
    box_table = ColumnTable(
        [
            ("x", Column("categorical", np.array([0, 1], dtype=np.int32), levels=("a", "b"))),
            ("ymin", Column("float", np.array([0.1, 0.2]))),
            ("lower", Column("float", np.array([0.3, 0.35]))),
            ("middle", Column("float", np.array([0.5, 0.5]))),
            ("upper", Column("float", np.array([0.7, 0.65]))),
            ("ymax", Column("float", np.array([0.9, 0.8]))),
        ]
    )
    return {
        "point": ggplot(table, aes(x="x", y="y", colour="g")) + registry.geom_point(),
        "line": ggplot(table, aes(x="x", y="y", colour="g")) + registry.geom_line(),
        "path": ggplot(table, aes(x="x", y="y", colour="g")) + registry.geom_path(),
        "bar": ggplot(table, aes(x="g", fill="h")) + registry.geom_bar(),
        "col": ggplot(table, aes(x="g", y="y", fill="h")) + registry.geom_col(),
        "area": ggplot(table, aes(x="x", y="y", colour="g")) + registry.geom_area(stat="identity"),
        "histogram": ggplot(table, aes(x="x", y="y", fill="h"))
        + registry.geom_histogram(stat="identity"),
        "boxplot": ggplot(
            box_table,
            aes(x="x", ymin="ymin", lower="lower", middle="middle", upper="upper", ymax="ymax"),
        )
        + registry.geom_boxplot(stat="identity")
        + registry.geom_point(data=box_table, mapping=aes(x="x", y="middle", colour="ymin")),
        "smooth": ggplot(table, aes(x="x", y="y", colour="g"))
        + registry.geom_smooth(stat="identity"),
    }


@pytest.mark.parametrize("geom_name", sorted(_geom_plots()))
def test_every_geom_draws_legend_keys_with_its_own_draw(geom_name: str) -> None:
    plot = _geom_plots()[geom_name]
    build = build_plot(plot)
    guides = build_guides(build)
    assert guides, f"{geom_name} 应该至少有一张图例"
    theme_value = resolve_theme(Theme())
    warning_count = 0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for guide in guides:
            layout = legend_layout(guide, theme_value, "right", metrics=METRICS)
            grobs = legend_grob(guide, build, theme_value, layout, metrics=METRICS)
            assert grobs
            warning_count += 1
    assert warning_count == len(guides)


def test_scene_with_legend_emits_labels_and_keys() -> None:
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="g"))
        + registry.geom_point()
        + registry.labs(title="T", x="X", y="Y")
    )
    scene = scene_from_plot(plot, width_in=7, height_in=7, metrics=METRICS)
    texts = [node.texts[0] for node in _walk(scene) if node.kind.value == "text"]
    assert {"T", "X", "Y", "g", "a", "b", "c"} <= set(texts)
    # 图例 key 的背景色块（legend.key fill = #EBEBEB）。
    fills = {
        tuple(node.gpar.fill)
        for node in _walk(scene)
        if node.kind.value == "rect" and node.gpar.fill is not None
    }
    # legend.key 的 fill = #EBEBEB（主题解析值），IR 里是 RGBA 元组。
    assert (235, 235, 235, 255) in fills


def test_subtitle_and_caption_are_laid_out_as_rows() -> None:
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="g"))
        + registry.geom_point()
        + registry.labs(title="T", subtitle="S", caption="C", x="X", y="Y")
    )
    layout = plot_layout(build_plot(plot), width_in=7, height_in=7, metrics=METRICS)
    assert layout.title_cm > 0 and layout.subtitle_cm > 0 and layout.caption_cm > 0
    assert layout.subtitle is not None and layout.caption is not None
    # 副标题紧贴标题下方；注脚贴着页面底边（次行是 x 轴标题）。
    assert layout.subtitle.top == pytest.approx(layout.title.y_cm)
    assert layout.caption.y_cm == pytest.approx(layout.margin_cm[2])
    scene = scene_from_plot(plot, width_in=7, height_in=7, metrics=METRICS)
    texts = [node.texts[0] for node in _walk(scene) if node.kind.value == "text"]
    assert {"T", "S", "C"} <= set(texts)


@pytest.mark.parametrize("position", ["right", "left", "top", "bottom"])
def test_legend_does_not_overlap_title_or_caption(position: str) -> None:
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="g"))
        + registry.geom_point()
        + make_theme(**{"legend.position": position})
        + registry.labs(title="T", subtitle="S", caption="C", x="X", y="Y")
    )
    layout = plot_layout(build_plot(plot), width_in=7, height_in=7, metrics=METRICS)
    assert layout.legend_boxes
    union_y = min(box.y_cm for box in layout.legend_boxes)
    union_top = max(box.top for box in layout.legend_boxes)
    if layout.title is not None:
        assert union_top <= layout.title.y_cm + 1e-9 or layout.legend_side in ("right", "left")
    if layout.subtitle is not None:
        assert union_top <= layout.subtitle.y_cm + 1e-9 or layout.legend_side in ("right", "left")
    if layout.caption is not None:
        assert union_y >= layout.caption.top - 1e-9 or layout.legend_side in ("right", "left")


def test_legend_position_inside_places_the_legend_in_the_panel() -> None:
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="g"))
        + registry.geom_point()
        + make_theme(**{"legend.position": "inside", "legend.position.inside": (0.25, 0.75)})
    )
    layout = plot_layout(build_plot(plot), width_in=7, height_in=7, metrics=METRICS)
    assert layout.legend_side is None or layout.legend_side == "inside"
    assert layout.legend_boxes
    box = layout.legend_boxes[0]
    area = layout.panel_area
    # 默认 `legend.justification.inside = center`：盒中心落在 (0.25, 0.75)。
    assert box.x_cm + box.width_cm / 2.0 == pytest.approx(area.x_cm + 0.25 * area.width_cm)
    assert box.y_cm + box.height_cm / 2.0 == pytest.approx(area.y_cm + 0.75 * area.height_cm)
    # inside 不占版面：面板区与没有图例时一样大。
    plain = plot_layout(
        build_plot(
            ggplot(data(), aes(x="x", y="y", colour="g"))
            + registry.geom_point()
            + make_theme(**{"legend.position": "none"})
        ),
        width_in=7,
        height_in=7,
        metrics=METRICS,
    )
    assert area.width_cm == pytest.approx(plain.panel_area.width_cm)
    assert area.height_cm == pytest.approx(plain.panel_area.height_cm)


def test_legend_position_numeric_pair_means_inside() -> None:
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="g"))
        + registry.geom_point()
        + make_theme(**{"legend.position": (0.5, 0.5)})
    )
    layout = plot_layout(build_plot(plot), width_in=7, height_in=7, metrics=METRICS)
    box = layout.legend_boxes[0]
    area = layout.panel_area
    assert box.x_cm + box.width_cm / 2.0 == pytest.approx(area.x_cm + area.width_cm / 2.0)


def test_theme_void_keeps_the_legend_but_drops_the_axes() -> None:
    """ggplot2 4.0.3 的 theme_void 只抹轴（legend.position 仍是 "right"）。"""
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="g"))
        + registry.geom_point()
        + registry.theme_void()
    )
    layout = plot_layout(build_plot(plot), width_in=7, height_in=7, metrics=METRICS)
    assert layout.x_axis_cm == 0.0 and layout.y_axis_cm == 0.0
    assert layout.x_title_cm == 0.0 and layout.y_title_cm == 0.0
    assert layout.guides and layout.legend_boxes


# ---------------------------------------------------------------------------
# SIL-705 回归：scale guide / colourbar reverse / 横向 / key 串美学 / 网格
# ---------------------------------------------------------------------------


def test_scale_guide_parameter_is_honoured() -> None:
    """`scale_*(guide=)` 不再被静默忽略；`plot.guides` 仍优先。"""
    base = ggplot(data(), aes(x="x", y="y", colour="g")) + registry.geom_point()
    assert build_guides(build_plot(base + registry.scale_colour_discrete(guide="none"))) == ()
    titled = build_guides(
        build_plot(base + registry.scale_colour_discrete(guide=registry.guide_legend(title="X")))
    )
    assert titled[0].title == "X"
    both = build_guides(
        build_plot(
            base
            + registry.scale_colour_discrete(guide="none")
            + registry.guide_legend("colour", title="P")
        )
    )
    assert both[0].title == "P"
    with pytest.raises(GuideError, match="guide_bins"):
        build_guides(build_plot(base + registry.scale_colour_discrete(guide="bins")))


def test_colourbar_reverse_ticks_follow_the_bar() -> None:
    """R：`reverse=TRUE` 时 `.value` 也是反的——标签与色带同向。"""
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="y"))
        + registry.geom_point()
        + registry.guide_colourbar("colour", reverse=True)
    )
    build, theme_value, guides, layouts = _layout(plot)
    guide, layout = guides[0], layouts[0]
    bar = layout.bar
    assert bar is not None
    # 键已反序（最大值在前）；R 的 reverse 把最大值放到色带底部。
    assert layout.ticks[0][0] == pytest.approx(bar.y_cm)
    assert layout.ticks[-1][0] == pytest.approx(bar.y_cm + bar.height_cm)
    grobs = legend_grob(guide, build, theme_value, layout, name="g")
    bottom = next(grob for grob in grobs if grob.name == "g.bar-0")
    assert bottom.gp.fill == guide.keys[0].values["colour"]


def test_horizontal_colourbar_draws_bar_and_labels_below() -> None:
    """横向 colourbar 有真实色条（5×key 宽 × key 高），标签在下方。"""
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="y"))
        + registry.geom_point()
        + registry.guide_colourbar("colour", direction="horizontal")
    )
    build, theme_value, guides, layouts = _layout(plot)
    guide, layout = guides[0], layouts[0]
    bar = layout.bar
    assert layout.direction == "horizontal" and bar is not None
    assert bar.width_cm == pytest.approx(5 * 0.6096)
    assert bar.height_cm == pytest.approx(0.6096)
    assert layout.ticks
    assert all(bar.x_cm <= x <= bar.x_cm + bar.width_cm for x, _label in layout.ticks)
    grobs = legend_grob(guide, build, theme_value, layout, name="g")
    assert len([grob for grob in grobs if ".bar-" in grob.name]) == guide.guide.nbin
    labels = [grob for grob in grobs if "colourbar-label" in grob.name]
    assert len(labels) == len(guide.keys)
    label_y = float(np.asarray(convert_height(labels[0].y, "cm", ctx=UnitContext())).sum())
    assert label_y < bar.y_cm


def test_colourbar_ticks_false_drops_tick_lines_but_keeps_labels() -> None:
    """R：`ticks = FALSE` 只去掉刻度线，断点标签照画。"""
    base = ggplot(data(), aes(x="x", y="y", colour="y")) + registry.geom_point()
    for ticks in (True, False):
        plot = base + registry.guide_colourbar("colour", ticks=ticks)
        build, theme_value, guides, layouts = _layout(plot)
        grobs = legend_grob(guides[0], build, theme_value, layouts[0], name="g")
        has_tick_lines = bool([grob for grob in grobs if ".tick-" in grob.name])
        assert has_tick_lines is ticks
        assert len([grob for grob in grobs if "colourbar-label" in grob.name]) == len(
            guides[0].keys
        )


def test_legend_grid_too_small_is_an_error() -> None:
    """`nrow * ncol` 放不下键时明确报错，不再抛 IndexError。"""
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="g"))
        + registry.geom_point()
        + registry.guide_legend("colour", nrow=1, ncol=1)
    )
    with pytest.raises(GuideError, match="放不下"):
        _layout(plot)


def test_split_guides_do_not_leak_the_other_aesthetic() -> None:
    """`colour = cyl, fill = gear` + `shape = 21`：两个图例各管各的美学。"""
    plot = ggplot(data(), aes(x="x", y="y", colour="g", fill="h")) + registry.geom_point(
        shape=21, size=2.5
    )
    build = build_plot(plot)
    guides = build_guides(build)
    assert [guide.aesthetics for guide in guides] == [("colour",), ("fill",)]
    colour_guide, fill_guide = guides
    index = colour_guide.layers[0]
    layer = build.layers[index]
    mapping = build.raw_mappings[index]
    geom = layer.geom_object.name
    colour_key = key_table(layer, colour_guide.keys[0].values, geom, mapping=mapping)
    fill_key = key_table(layer, fill_guide.keys[0].values, geom, mapping=mapping)
    assert bool(np.all(colour_key.column("fill").na_mask))
    assert bool(np.all(fill_key.column("colour").na_mask))
    assert colour_key.column("colour").values[0] == colour_guide.keys[0].values["colour"]


_CASES_WITHOUT_LEGEND = (
    "geom-bar-stacked",
    "geom-col-identity",
    "geom-line-groups",
    "geom-point-shapes",
    "stat-area-align",
)


@pytest.mark.parametrize("name", _CASES_WITHOUT_LEGEND)
def test_reference_cases_keep_the_legend_off(name: str) -> None:
    """R 参考图是 `theme_void() + legend.position="none"`：case 也必须关图例。"""
    path = Path(__file__).resolve().parents[1] / "docs" / "cases" / name / "plot.py"
    spec = importlib.util.spec_from_file_location(f"case_{name.replace('-', '_')}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    layout = plot_layout(build_plot(module.build()["plot"]), metrics=METRICS)
    assert not layout.legend_layouts


def test_axis_and_legend_are_deterministic() -> None:
    """轴 / 图例 / 标题进场景后，同一输入两次 encode 仍逐字节相等。"""

    def plot() -> object:
        return (
            ggplot(data(), aes(x="x", y="y", colour="g"))
            + registry.geom_point()
            + registry.facet_wrap(("h",), ncol=2)
            + registry.labs(title="Report", x="X", y="Y")
        )

    one = hashlib.sha256(ir.encode(scene_from_plot(plot(), width_in=6, height_in=4))).hexdigest()
    two = hashlib.sha256(ir.encode(scene_from_plot(plot(), width_in=6, height_in=4))).hexdigest()
    assert one == two


def _walk(scene: ir.Scene):
    stack = [scene.root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(node.children)


# ---------------------------------------------------------------------------
# SIL-723：色条按标度 limits 的全量程取色（不是断点色的插值）
# ---------------------------------------------------------------------------


def _colourbar_plot(*, limits=(16.2, 30.3), reverse: bool = False):
    table = ColumnTable(
        [
            ("x", Column("float", np.array([0.1, 0.2, 0.3, 0.4, 0.5]))),
            ("y", Column("float", np.array([0.2, 0.5, 0.3, 0.7, 0.4]))),
            ("v", Column("float", np.array([20.0, 22.0, 25.0, 27.0, 30.0]))),
        ]
    )
    return (
        ggplot(table, aes(x="x", y="y", colour="v"))
        + registry.geom_point()
        + registry.scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.scale_colour_gradient(limits=limits)
        + registry.guide_colourbar("colour", nbin=64, reverse=reverse)
        + registry.theme_void()
    )


def _bar_fills(plot) -> list[str]:
    build, theme_value, guides, layouts = _layout(plot)
    grobs = legend_grob(guides[0], build, theme_value, layouts[0], name="g")
    return [grob.gp.fill for grob in grobs if ".bar-" in grob.name]


def test_colourbar_samples_the_full_scale_range() -> None:
    """`limits = (16.2, 30.3)`：色条首末是这个范围端点的颜色，不是最低断点 20 的色。"""
    fills = _bar_fills(_colourbar_plot())
    assert len(fills) == 64
    # 缺省 low / high（`#132B43` / `#56B1F7`）：全量程端点必须都在色条里。
    assert fills[0] == "#132B43"
    assert fills[-1] == "#56B1F7"
    # 最低断点 20 的色（约 t = 0.27）不是端点——旧实现把色条画成 20..30，端点是它。
    scale = build_plot(_colourbar_plot()).scales.scale("colour")
    assert scale is not None
    at_lowest_break = scale.palette([0.0])[0]
    assert at_lowest_break == fills[0]  # 只是一个 sanity check（palette 起点）
    assert fills[0] != "#22496C"  # 断点 20 的色不是色条低端


def test_colourbar_reverse_flips_the_full_range() -> None:
    normal = _bar_fills(_colourbar_plot())
    flipped = _bar_fills(_colourbar_plot(reverse=True))
    assert flipped == list(reversed(normal))
    assert flipped[0] == "#56B1F7" and flipped[-1] == "#132B43"


def test_colourbar_endpoints_match_the_data_mapping() -> None:
    """色条端点 = 标度 limits 的端点色（与 `scale.map()` 同一条 palette）。"""
    plot = _colourbar_plot()
    build = build_plot(plot)
    scale = build.scales.scale("colour")
    assert scale is not None
    endpoints = scale.palette([0.0, 1.0])
    fills = _bar_fills(plot)
    assert (fills[0], fills[-1]) == (endpoints[0], endpoints[1])
    # 低值 20 的颜色确实出现在色条里（旧实现只覆盖断点色阶，仍会有；关键是端点）。
    low_value = scale.map(Column("float", np.array([20.0]))).values.tolist()[0]
    assert low_value in fills


def test_scale_colour_gradient_aliases_are_registered() -> None:
    """`scale_colour_gradient` / `scale_fill_gradient` 与 `*_continuous` 同义。"""
    assert registry.scale_colour_gradient().name == "colour_gradient"
    assert registry.scale_fill_gradient().name == "fill_gradient"
    table = data()
    p = ggplot(table, aes(x="x", y="y"))
    # 方法链入口与 `+` 入口产生同一实现（同一个注册表）。
    by_method = p.scale_colour_gradient(low="#000000")
    by_plus = p + registry.scale_colour_gradient(low="#000000")
    assert next(iter(by_method.scales.values())).name == "colour_gradient"
    assert next(iter(by_plus.scales.values())).name == "colour_gradient"
    from ggcore.scales import GradientScale, scale_from_component

    scale = scale_from_component(registry.scale_fill_gradient(limits=(0, 1)))
    assert isinstance(scale, GradientScale)


# ---------------------------------------------------------------------------
# SIL-725：竖向图例在 **panel 行**里居中（不含 facet 的顶部 / 底部 strip 带）
# ---------------------------------------------------------------------------

#: 1pt 对应的 cm（断言容差用 pt 表达）。
PT_CM = 2.54 / 72.0


def _facet_legend_layout(*, strip_double: bool = False):
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="g"))
        + registry.geom_point()
        + registry.facet_wrap(("h",), ncol=2)  # 3 个面板 → 2 个 panel 行
    )
    if strip_double:
        # strip 行高 = 文本行高 + 上下 margin：字号与 margin 同时翻倍 ≈ 两倍行高。
        plot = plot + make_theme(
            **{"strip.text": element_text(size=17.6, margin=margin(8.8, 8.8, 8.8, 8.8))}
        )
    return plot_layout(build_plot(plot), width_in=6, height_in=4, metrics=METRICS)


def _center_cm(boxes) -> float:
    return (min(box.y_cm for box in boxes) + max(box.top for box in boxes)) / 2.0


def _panel_rows_center_cm(layout) -> float:
    return (
        min(box.y_cm for box in layout.panel_boxes.values())
        + max(box.top for box in layout.panel_boxes.values())
    ) / 2.0


def _panel_area_center_cm(layout) -> float:
    return layout.panel_area.y_cm + layout.panel_area.height_cm / 2.0


def test_vertical_legend_is_centred_on_the_panel_rows() -> None:
    """2×2 facet + 竖向 colour 图例：盒中心 = panel 行中心（±0.1pt）。

    修前挂在整个 `panel_area` 上，而 `panel_area` 含顶部 strip 带，中心因此比
    panel 行中心高半个 strip（本图 ≈ 8pt）。
    """
    layout = _facet_legend_layout()
    center = _center_cm(layout.legend_boxes)
    assert center == pytest.approx(_panel_rows_center_cm(layout), abs=0.1 * PT_CM)
    # panel 行中心明显低于 panel_area 中心：修回旧写法这里会变红。
    assert _panel_area_center_cm(layout) - center > 0.1  # cm
    assert abs(center - _panel_area_center_cm(layout)) > 0.1 * PT_CM


def test_single_panel_vertical_legend_keeps_the_panel_area_centre() -> None:
    """没有 strip 时 panel 行 == panel_area：单面板图不能因为这次改动移动。"""
    plot = ggplot(data(), aes(x="x", y="y", colour="g")) + registry.geom_point()
    layout = plot_layout(build_plot(plot), width_in=6, height_in=4, metrics=METRICS)
    assert list(layout.panel_boxes) == [1]
    center = _center_cm(layout.legend_boxes)
    assert center == pytest.approx(_panel_area_center_cm(layout), abs=0.1 * PT_CM)
    assert center == pytest.approx(_panel_rows_center_cm(layout), abs=0.1 * PT_CM)


def test_legend_centre_follows_the_panel_rows_when_the_strip_grows() -> None:
    """strip 行翻倍 → 面板行整体下移，图例中心跟着面板行走（不是钉在 panel_area）。"""
    base = _facet_legend_layout()
    doubled = _facet_legend_layout(strip_double=True)
    for layout in (base, doubled):
        assert _center_cm(layout.legend_boxes) == pytest.approx(
            _panel_rows_center_cm(layout), abs=0.1 * PT_CM
        )
    assert _panel_rows_center_cm(doubled) < _panel_rows_center_cm(base) - 0.1
    assert _center_cm(doubled.legend_boxes) < _center_cm(base.legend_boxes) - 0.1


# ---------------------------------------------------------------------------
# M2-2（SIL-738）：guides() 入口 / key 合并 / override / 布局 / 扩展点
# ---------------------------------------------------------------------------


def test_guides_entry_overrides_scale_and_supports_none() -> None:
    base = ggplot(data(), aes(x="x", y="y", colour="g")) + registry.geom_point()
    # `guides(colour = "none")` 与 `scale_(guide="none")` 等价，且 plot 级优先。
    plot = base + guides(colour="none")
    assert build_guides(build_plot(plot)) == ()
    scale_none = base + registry.scale_colour_discrete(guide="none")
    assert build_guides(build_plot(scale_none)) == ()
    assert build_guides(build_plot(scale_none + guides(colour="legend")))
    # `guides(colour = None)` 取消 plot 级设置，回落到 scale。
    fallback = base + guides(colour="none") + guides(colour=None)
    assert build_guides(build_plot(fallback))
    # color 是 colour 的别名。
    assert build_guides(build_plot(base + guides(color="none"))) == ()
    # 位置参数也认 dict（R 的 `guides(list(...))`）。
    assert build_guides(build_plot(base + guides({"colour": "none"}))) == ()


def test_guides_accepts_guide_implementations_and_components() -> None:
    base = ggplot(data(), aes(x="x", y="y", colour="g")) + registry.geom_point()
    implementation = base + guides(colour=guide_legend(title="impl", nrow=1))
    assert build_guides(build_plot(implementation))[0].title == "impl"
    component = base + guides(colour=registry.guide_legend(title="component"))
    assert build_guides(build_plot(component))[0].title == "component"


def test_colour_and_fill_on_the_same_variable_share_one_guide() -> None:
    """同一变量的 colour + fill：标题 / 标签 / guide 类型相同 → 合成一张，键不重复。"""
    plot = ggplot(data(), aes(x="x", y="y", colour="g", fill="g")) + registry.geom_point(shape=21)
    guides_built = build_guides(build_plot(plot))
    assert len(guides_built) == 1
    assert guides_built[0].aesthetics == ("colour", "fill")
    assert [key.label for key in guides_built[0].keys] == ["a", "b", "c"]
    for key in guides_built[0].keys:
        assert set(key.values) == {"colour", "fill"}
    assert guides_built[0].layers == (0,)


def test_merge_requires_the_same_order() -> None:
    """R 的 hash 分组包含 order：order 不同不合并。"""
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="g", shape="g"))
        + registry.geom_point()
        + guides(colour=guide_legend(order=1), shape=guide_legend(order=2))
    )
    assert len(build_guides(build_plot(plot))) == 2


def test_merge_of_override_aes_keeps_the_first_and_warns() -> None:
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="g", shape="g"))
        + registry.geom_point()
        + guides(
            colour=guide_legend(override_aes={"colour": "black", "size": 4}),
            shape=guide_legend(override_aes={"colour": "red"}),
        )
    )
    with pytest.warns(UserWarning, match="override.aes"):
        merged = build_guides(build_plot(plot))[0]
    assert merged.guide.override_aes["colour"] == "black"


def test_override_aes_reaches_the_key_grob() -> None:
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="g"))
        + registry.geom_point()
        + guides(colour=guide_legend(override_aes={"colour": "black", "alpha": 0.5}))
    )
    build = build_plot(plot)
    theme_value = resolve_theme(Theme())
    guide = build_guides(build)[0]
    layout = legend_layout(guide, theme_value, "right", metrics=METRICS)
    grobs = legend_grob(guide, build, theme_value, layout, metrics=METRICS)
    points = [item for item in grobs if type(item).__name__ == "PointsGrob"]
    assert points
    for item in points:
        assert str(item.gp.col).startswith("#000000")
        # alpha 与颜色合成到 RGBA 十六进制（#00000080 即 50%）。
        assert str(item.gp.col).endswith("80")


def test_override_aes_vector_applies_per_key() -> None:
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="g"))
        + registry.geom_point()
        + guides(colour=guide_legend(override_aes={"colour": ["#111111", "#222222"]}))
    )
    build = build_plot(plot)
    theme_value = resolve_theme(Theme())
    guide = build_guides(build)[0]
    layout = legend_layout(guide, theme_value, "right", metrics=METRICS)
    points = [
        item
        for item in legend_grob(guide, build, theme_value, layout, metrics=METRICS)
        if type(item).__name__ == "PointsGrob"
    ]
    assert [item.gp.col for item in points] == ["#111111", "#222222", "#111111"]


def test_label_position_left_and_top() -> None:
    for position in ("left", "top", "bottom"):
        plot = (
            ggplot(data(), aes(x="x", y="y", colour="g"))
            + registry.geom_point()
            + guides(colour=guide_legend(label_position=position))
        )
        _build, theme_value, guides_built, _layouts = _layout(plot)
        layout = legend_layout(guides_built[0], theme_value, "right", metrics=METRICS)
        assert layout.label_position == position
        cell = layout.keys[0]
        if position == "left":
            assert cell.label_box.x_cm < cell.box.x_cm
        elif position == "top":
            assert cell.label_box.y_cm >= cell.box.y_cm + cell.box.height_cm
        else:
            assert cell.label_box.top <= cell.box.y_cm


def test_horizontal_legend_defaults_to_five_columns_and_left_title() -> None:
    """R 4.0.3：横排默认 `nrow = ceil(n / 5)`；标题默认在左侧（单独一列）。"""
    table = ColumnTable(
        [
            ("x", Column("float", np.arange(12.0))),
            ("y", Column("float", np.arange(12.0))),
            (
                "g",
                Column(
                    "categorical",
                    np.arange(12, dtype=np.int32) % 12,
                    levels=tuple(str(index) for index in range(12)),
                ),
            ),
        ]
    )
    plot = ggplot(table, aes(x="x", y="y", colour="g")) + registry.geom_point()
    build = build_plot(plot)
    theme_value = resolve_theme(Theme())
    layout = legend_layout(build_guides(build)[0], theme_value, "bottom", metrics=METRICS)
    assert layout.direction == "horizontal"
    assert layout.title_position == "left"
    # 12 个键 → 3 行 × 4 列；标签在键右侧。
    ys = sorted({round(cell.box.y_cm, 9) for cell in layout.keys})
    xs = sorted({round(cell.box.x_cm, 9) for cell in layout.keys})
    assert (len(ys), len(xs)) == (3, 4)


def test_byrow_fills_rows_first() -> None:
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="g"))
        + registry.geom_point()
        + guides(colour=guide_legend(ncol=2, byrow=True))
    )
    _build, theme_value, guides_built, _layouts = _layout(plot)
    layout = legend_layout(guides_built[0], theme_value, "right", metrics=METRICS)
    rows = [round(cell.box.y_cm, 9) for cell in layout.keys]
    # byrow：前两个键在同一行（y 相同），第三个换行。
    assert rows[0] == rows[1]
    assert rows[2] != rows[0]


def test_title_and_label_justification_are_honoured() -> None:
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="g"))
        + registry.geom_point()
        + guides(colour=guide_legend(title_hjust=1.0, label_hjust=1.0))
    )
    _build, theme_value, guides_built, _layouts = _layout(plot)
    layout = legend_layout(guides_built[0], theme_value, "right", metrics=METRICS)
    assert layout.title_hjust == 1.0
    grobs = legend_grob(guides_built[0], build_plot(plot), theme_value, layout, metrics=METRICS)
    labels = [item for item in grobs if getattr(item, "name", "").startswith("guide.label")]
    assert labels and all(item.hjust == 1.0 for item in labels)


def test_guide_custom_draws_its_grob_and_title() -> None:
    box = rect_grob(0.0, 0.0, 1.0, 1.0, default_units="cm", gp=gpar(fill="#123456"))
    plot = (
        ggplot(data(), aes(x="x", y="y"))
        + registry.geom_point()
        + guides(custom=guide_custom(box, width=unit(1.0, "cm"), height=unit(1.0, "cm"), title="C"))
    )
    build = build_plot(plot)
    built = build_guides(build)
    assert len(built) == 1
    guide = built[0]
    assert isinstance(guide.guide, GuideCustom)
    assert guide.title == "C"
    theme_value = resolve_theme(Theme())
    layout = legend_layout(guide, theme_value, "right", metrics=METRICS)
    assert layout.content_box is not None
    grobs = legend_grob(guide, build, theme_value, layout, metrics=METRICS)
    assert any(getattr(item, "name", "") == "guide.title" for item in grobs)
    content = [item for item in grobs if getattr(item, "vp", None) is not None]
    assert content and content[0].gp.fill == "#123456"
    # 自定义 guide 不占「被映射的美学」那一路；默认图例也不会凭空出现。
    assert build_guides(
        build_plot(
            ggplot(data(), aes(x="x", y="y"))
            + registry.geom_point()
            + guides(custom=guide_custom(box, width=unit(1.0, "cm"), height=unit(1.0, "cm")))
        )
    )


def test_guide_custom_deduplicates_identical_guides() -> None:
    box = rect_grob(0.0, 0.0, 1.0, 1.0, default_units="cm", gp=gpar(fill="#123456"))
    custom = guide_custom(box, width=unit(1.0, "cm"), height=unit(1.0, "cm"), title="C")
    plot = (
        ggplot(data(), aes(x="x", y="y"))
        + registry.geom_point()
        + guides(first=custom, second=custom)
    )
    assert len(build_guides(build_plot(plot))) == 1


class _DescribeGuide(Guide):
    """扩展点演示：只换标题、不画 key（M2-9 的扩展 API 走同一组方法）。"""

    kind = "legend"
    available_aes = ("any",)

    def __init__(self, title: str = "described") -> None:
        self.title = title
        self.position = None
        self.order = 0.0

    def train(self, build, aesthetic, scale):
        trained = super().train(build, aesthetic, scale)
        if trained is None:
            return None
        from dataclasses import replace as _replace

        return _replace(trained, title=self.title)

    def gengrob(self, guide_build, build, theme, layout, *, metrics=None, name="guide"):
        return [text_grob(guide_build.title or "", 0.0, 0.0, default_units="cm")]


def test_custom_guide_subclass_can_override_train_and_gengrob() -> None:
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="g"))
        + registry.geom_point()
        + guides(colour=_DescribeGuide("A guide showing a, b, c"))
    )
    build = build_plot(plot)
    built = build_guides(build)
    assert built[0].title == "A guide showing a, b, c"
    theme_value = resolve_theme(Theme())
    layout = legend_layout(built[0], theme_value, "right", metrics=METRICS)
    grobs = built[0].guide.gengrob(built[0], build, theme_value, layout)
    assert len(grobs) == 1
    assert grobs[0].label[0] == "A guide showing a, b, c"


def test_registered_guide_component_uses_build_guide_and_draw_keys() -> None:
    """M2-9 的注册入口：组件子类 `build_guide()` + 运行时 `draw_keys()`。"""
    from dataclasses import dataclass

    from ggcore.components import Guide as GuideComponent

    @dataclass(frozen=True)
    class StarGuide(GuideLegend):
        kind: str = "star"

        def draw_keys(self, guide_build, theme, layout, *, metrics=None, name="guide"):
            return [
                text_grob(
                    f"*{cell.key.label}",
                    cell.box.x_cm,
                    cell.box.y_cm,
                    default_units="cm",
                    name=f"{name}.star-{index}",
                )
                for index, cell in enumerate(layout.keys)
            ]

    class StarSpec(GuideComponent):
        def build_guide(self):
            return StarGuide(
                title=self.params.get("title", AUTO),
                direction=self.params.get("direction"),
            )

    registry.register_guide("star", StarSpec)
    try:
        plot = (
            ggplot(data(), aes(x="x", y="y", colour="g"))
            + registry.geom_point()
            + guides(colour=registry.guide_star(aesthetic="colour"))
        )
        build = build_plot(plot)
        built = build_guides(build)
        assert len(built) == 1 and built[0].guide.kind == "star"
        theme_value = resolve_theme(Theme())
        layout = legend_layout(built[0], theme_value, "right", metrics=METRICS)
        grobs = legend_grob(built[0], build, theme_value, layout, metrics=METRICS)
        assert any(getattr(item, "name", "").startswith("guide.star-") for item in grobs)
        # 字符串写法也走注册表（`scale_*(guide="star")` 同一路径）。
        string_plot = (
            ggplot(data(), aes(x="x", y="y", colour="g"))
            + registry.geom_point()
            + guides(colour="star")
        )
        assert build_guides(build_plot(string_plot))[0].guide.kind == "star"
    finally:
        registry.unregister("guide", "star")
    # 未注册的名字仍点名报错。
    with pytest.raises(GuideError, match="guide_bins"):
        build_guides(
            build_plot(
                ggplot(data(), aes(x="x", y="y", colour="g"))
                + registry.geom_point()
                + guides(colour="guide_bins")
            )
        )


def test_legend_box_layout_stacks_vertically_and_horizontally() -> None:
    plot = ggplot(data(), aes(x="x", y="y", colour="g", fill="h")) + registry.geom_point(shape=21)
    build = build_plot(plot)
    theme_value = resolve_theme(Theme())
    built = build_guides(build)
    assert len(built) == 2
    layouts = [legend_layout(guide, theme_value, "right", metrics=METRICS) for guide in built]
    vertical = legend_box_layout(layouts, "right", theme_value)
    assert vertical.direction == "vertical"
    assert vertical.height_cm == pytest.approx(sum(item.height_cm for item in layouts) + 0.3866)
    assert vertical.width_cm == pytest.approx(max(item.width_cm for item in layouts))
    horizontal = legend_box_layout(layouts, "bottom", theme_value)
    assert horizontal.direction == "horizontal"
    assert horizontal.width_cm == pytest.approx(
        sum(item.width_cm for item in layouts) + 0.3866, abs=1e-4
    )
    assert horizontal.height_cm == pytest.approx(max(item.height_cm for item in layouts))
    # 每个图例在盒内不重叠。
    for direction_box in (vertical, horizontal):
        first, second = direction_box.boxes
        assert first.x_cm + first.width_cm <= second.x_cm + 1e-9 or (
            first.y_cm >= second.y_cm + second.height_cm - 1e-9
        )


def test_guide_positions_can_differ_per_guide() -> None:
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="g", fill="h"))
        + registry.geom_point(shape=21)
        + guides(
            colour=guide_legend(position="right"),
            fill=guide_legend(position="bottom"),
        )
    )
    layout = plot_layout(build_plot(plot), width_in=7, height_in=7, metrics=METRICS)
    assert len(layout.legend_box_layouts) == 2
    assert {box.position for box in layout.legend_box_layouts} == {"right", "bottom"}
    right = next(box for box in layout.legend_box_layouts if box.position == "right")
    bottom = next(box for box in layout.legend_box_layouts if box.position == "bottom")
    assert right.direction == "vertical" and bottom.direction == "horizontal"


def test_guide_legend_title_subtitle_rows() -> None:
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="g"))
        + registry.geom_point()
        + guides(colour=guide_legend(title="T", subtitle="S"))
    )
    build = build_plot(plot)
    theme_value = resolve_theme(Theme())
    guide = build_guides(build)[0]
    layout = legend_layout(guide, theme_value, "right", metrics=METRICS)
    assert layout.title_box is not None and layout.subtitle_box is not None
    assert layout.subtitle_box.top == pytest.approx(layout.title_box.y_cm)
    grobs = legend_grob(guide, build, theme_value, layout, metrics=METRICS)
    texts = [list(getattr(item, "label", ())) for item in grobs]
    assert ["T"] in texts and ["S"] in texts


@pytest.mark.parametrize("position", ["top", "bottom"])
def test_horizontal_legend_sits_outside_the_panel(position: str) -> None:
    """top / bottom 的图例盒在面板之外：top 在顶轴之上，bottom 在 x 轴标题之下。"""
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="g"))
        + registry.geom_point()
        + make_theme(**{"legend.position": position})
    )
    layout = plot_layout(build_plot(plot), width_in=4, height_in=3, metrics=METRICS)
    box = layout.legend_boxes[0]
    if position == "top":
        assert box.y_cm >= layout.panel_area.top
        assert box.y_cm == pytest.approx(
            layout.panel_area.top + layout.x_axis_top_cm + layout.x_title_top_cm + 0.3866,
            abs=0.01,
        )
    else:
        assert box.top <= layout.panel_area.y_cm
        # R 的 guide-box-bottom 在 axis-b / xlab-b 之下、caption 之上。
        assert box.y_cm >= layout.margin_cm[2]
        assert box.top <= layout.panel_area.y_cm - layout.x_axis_cm - layout.x_title_cm + 1e-9


def test_guide_extension_functions_forward_to_methods() -> None:
    """`guide_train` / `guide_transform` / `guide_geom` / `guide_gengrob` 是方法名的旧入口。"""
    from ggcore.guide import guide_gengrob, guide_geom, guide_train, guide_transform

    plot = ggplot(data(), aes(x="x", y="y", colour="g")) + registry.geom_point()
    build = build_plot(plot)
    scale = build.scales.scale("colour")
    guide = guide_legend(title="G")
    trained = guide_train(guide, build, "colour", scale)
    assert trained is not None and trained.title == "G"
    assert guide_transform(guide, trained.keys) == trained.keys
    assert guide_geom(guide, build.layers[0]) is None
    theme_value = resolve_theme(Theme())
    layout = legend_layout(trained, theme_value, "right", metrics=METRICS)
    assert guide_gengrob(trained, build, theme_value, layout, metrics=METRICS)

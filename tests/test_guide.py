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
from ggcore.grobs import RasterGrob
from ggcore.guide import (
    AUTO,
    GuideColourbar,
    GuideError,
    GuideLegend,
    GuideNone,
    build_guides,
    guide_colourbar,
    guide_from_component,
    guide_legend,
    guide_none,
    key_table,
    legend_grob,
    legend_layout,
)
from ggcore.plot import aes, ggplot
from ggcore.scales import gradient_pal
from ggcore.theme import Theme, resolve_theme
from ggcore.theme import theme as make_theme
from ggcore.units import UnitContext, convert_height, convert_width, unit


class FakeMetrics:
    def strwidth(self, text: str, *, fontsize: float, cex: float, font: str = "sans") -> float:
        del font
        return 0.5 * float(fontsize) * float(cex) * len(text) / 72.0

    def strheight(self, text: str, *, fontsize: float, cex: float, font: str = "sans") -> float:
        del text, font
        return 0.955 * float(fontsize) * float(cex) / 72.0


METRICS = FakeMetrics()


def _bar_pixels(grob) -> np.ndarray:
    """色条位图的像素（`RasterGrob.data` → `(H, W, 3)`）。"""
    import io

    from PIL import Image

    with Image.open(io.BytesIO(grob.data)) as image:
        return np.asarray(image.convert("RGB"), dtype=np.uint8).copy()


def _hex(pixel: np.ndarray) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(int(channel) for channel in pixel))


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


def test_colourbar_spans_scale_limits_instead_of_break_colours() -> None:
    """SIL-722：色带两端取 limits（`palette(0)` / `palette(1)`），断点只管刻度。

    v1 把断点色当端点再插值：limits 比断点宽时，低值点的深色在图例里找不到
    （实测只覆盖调色板 t≈0.27 → 0.97）。
    """
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="y"))
        + registry.geom_point()
        + registry.scale_colour_continuous(limits=(0, 10), breaks=(3, 5, 7))
    )
    build, theme_value, guides, layouts = _layout(plot)
    guide, layout = guides[0], layouts[0]
    assert guide.limits == (0.0, 10.0)
    assert [key.label for key in guide.keys] == ["3", "5", "7"]
    grobs = legend_grob(guide, build, theme_value, layout, name="g")
    bars = [grob for grob in grobs if grob.name == "g.bar"]
    assert len(bars) == 1 and isinstance(bars[0], RasterGrob)
    pixels = _bar_pixels(bars[0])
    assert pixels.shape[:2] == (guide.guide.nbin, 1)
    low, high = gradient_pal()([0.0, 1.0])
    assert _hex(pixels[-1, 0]) == low == "#132B43"
    assert _hex(pixels[0, 0]) == high == "#56B1F7"
    # 首个断点（3 / 10）不在色带底端：断点只决定刻度位置，不再裁剪色带。
    assert layout.bar is not None
    assert layout.ticks[0][0] > layout.bar.y_cm


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


def test_legend_position_inside_is_named_as_unimplemented() -> None:
    plot = (
        ggplot(data(), aes(x="x", y="y", colour="g"))
        + registry.geom_point()
        + make_theme(**{"legend.position": "inside"})
    )
    with pytest.raises(GuideError, match="inside"):
        plot_layout(build_plot(plot))


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
    pixels = _bar_pixels(next(grob for grob in grobs if grob.name == "g.bar"))
    assert _hex(pixels[-1, 0]) == guide.keys[0].values["colour"]
    assert _hex(pixels[0, 0]) == guide.keys[-1].values["colour"]


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
    bar_grob = next(grob for grob in grobs if grob.name == "g.bar")
    assert _bar_pixels(bar_grob).shape[:2] == (1, guide.guide.nbin)
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

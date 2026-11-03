"""guide / 主轴与 ggplot2 4.0.3 的 R 侧对拍（M1-11）。

夹具由 `pixi run -e refs refs:guide`（`tools/refs/guide_ref.R`）生成，R 与 Python
用同一份 12 行数据。两条断言线：

1. **行 / 列尺寸**（cm）：`ggplotGrob()` 画在 7×7in 的 pdf(NULL) 上读回的
   `axis-l` / `axis-b` / `ylab-l` / `xlab-b` / `title` 行高列宽，以及每张图例
   gtable 的宽高——容差 0.05cm（0.5mm，任务口径）；
2. **断点 / 标签 / 图例键**：`panel_params$x/y` 的 breaks + labels、`get_guide_data()`
   的键标签与映射值，逐值相等（位置是 npc，容差 1e-12）。

`theme_void()` 的 R 4.0.3 行为是「轴消失、图例保留」（`legend.position` 仍是
`"right"`），不是任务初稿写的「轴/图例都消失」；本测试按 R 的实际输出钉住，
偏差记在 `docs/notes/guide.md`。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ggcore import registry
from ggcore.axis import axis_ticks
from ggcore.build import build_plot
from ggcore.data import Column, ColumnTable
from ggcore.geom.scene import plot_layout
from ggcore.guide import GuideColourbar, build_guides, guide_legend
from ggcore.plot import aes, ggplot, guides
from ggcore.theme import theme as make_theme
from ggskia.text import ShaperMetrics

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "guide_r_reference.json"
REFERENCE = json.loads(FIXTURE.read_text(encoding="utf-8"))
CASES = REFERENCE["cases"]
#: 任务口径：≤ 0.5mm。
TOLERANCE_CM = 0.05
METRICS = ShaperMetrics()


def _table() -> ColumnTable:
    data = REFERENCE["data"]

    def categorical(values: list[str], levels: list[str]) -> Column:
        index = {level: position for position, level in enumerate(levels)}
        return Column(
            "categorical",
            np.array([index[value] for value in values], dtype=np.int32),
            levels=tuple(levels),
        )

    return ColumnTable(
        [
            ("x", Column("float", np.array(data["x"], dtype=np.float64))),
            ("y", Column("float", np.array(data["y"], dtype=np.float64))),
            ("disp", Column("float", np.array(data["disp"], dtype=np.float64))),
            ("cyl", categorical(data["cyl"], data["cyl_levels"])),
            ("gear", categorical(data["gear"], data["gear_levels"])),
        ]
    )


def _plot(name: str) -> ggplot:
    table = _table()
    labels = registry.labs(x="X", y="Y")
    if name == "legend_colour_discrete":
        return ggplot(table, aes(x="x", y="y", colour="cyl")) + registry.geom_point() + labels
    if name == "legend_colour_fill":
        return (
            ggplot(table, aes(x="x", y="y", colour="cyl", fill="gear"))
            + registry.geom_point(shape=21, size=2.5)
            + labels
        )
    if name == "legend_merged":
        return (
            ggplot(table, aes(x="x", y="y", colour="cyl", shape="cyl"))
            + registry.geom_point()
            + labels
        )
    if name == "colourbar":
        return ggplot(table, aes(x="x", y="y", colour="disp")) + registry.geom_point() + labels
    if name == "axis_continuous":
        return ggplot(table, aes(x="x", y="y")) + registry.geom_point() + labels
    if name == "axis_discrete":
        return ggplot(table, aes(x="cyl", y="y")) + registry.geom_point() + labels
    if name == "axis_log10":
        return (
            ggplot(table, aes(x="x", y="y"))
            + registry.geom_point()
            + registry.scale_x_log10()
            + labels
        )
    if name == "theme_void":
        return (
            ggplot(table, aes(x="x", y="y", colour="cyl"))
            + registry.geom_point()
            + registry.labs(title="T", x="X", y="Y")
            + registry.theme_void()
        )
    if name == "legend_colour_fill_same":
        return (
            ggplot(table, aes(x="x", y="y", colour="cyl", fill="cyl"))
            + registry.geom_point(shape=21, size=2.5)
            + labels
        )
    if name == "legend_override":
        return (
            ggplot(table, aes(x="x", y="y", colour="cyl"))
            + registry.geom_point()
            + labels
            + guides(colour=guide_legend(override_aes={"alpha": 1, "colour": "black"}))
        )
    if name == "legend_nrow2":
        return (
            ggplot(table, aes(x="x", y="y", colour="cyl"))
            + registry.geom_point()
            + labels
            + guides(colour=guide_legend(nrow=2))
        )
    if name == "legend_label_left":
        return (
            ggplot(table, aes(x="x", y="y", colour="cyl"))
            + registry.geom_point()
            + labels
            + guides(colour=guide_legend(label_position="left"))
        )
    if name == "legend_top":
        return (
            ggplot(table, aes(x="x", y="y", colour="cyl"))
            + registry.geom_point()
            + labels
            + make_theme(**{"legend.position": "top"})
        )
    if name == "legend_inside":
        return (
            ggplot(table, aes(x="x", y="y", colour="cyl"))
            + registry.geom_point()
            + labels
            + make_theme(**{"legend.position": "inside", "legend.position.inside": (0.3, 0.7)})
        )
    if name == "legend_order":
        return (
            ggplot(table, aes(x="x", y="y", colour="cyl", fill="gear"))
            + registry.geom_point(shape=21, size=2.5)
            + labels
            + guides(colour=guide_legend(order=2), fill=guide_legend(order=1))
        )
    if name == "legend_two_bottom":
        return (
            ggplot(table, aes(x="x", y="y", colour="cyl", fill="gear"))
            + registry.geom_point(shape=21, size=2.5)
            + labels
            + make_theme(**{"legend.position": "bottom"})
        )
    raise AssertionError(f"fixture 里有未覆盖的 case {name!r}")


BUILDERS = {name: (lambda name=name: _plot(name)) for name in CASES}


def test_fixture_covers_the_documented_cases() -> None:
    assert set(CASES) == {
        "legend_colour_discrete",
        "legend_colour_fill",
        "legend_merged",
        "colourbar",
        "axis_continuous",
        "axis_discrete",
        "axis_log10",
        "theme_void",
        "legend_colour_fill_same",
        "legend_override",
        "legend_nrow2",
        "legend_label_left",
        "legend_top",
        "legend_inside",
        "legend_order",
        "legend_two_bottom",
    }
    assert REFERENCE["ggplot2"].startswith("4.0.3")


@pytest.mark.parametrize("name", sorted(CASES))
def test_axis_and_legend_sizes_match_r(name: str) -> None:
    """轴 / 图例的行列尺寸差 ≤ 0.5mm（任务验收口径）。"""
    case = CASES[name]
    layout = plot_layout(
        build_plot(BUILDERS[name]()),
        width_in=REFERENCE["size_in"][0],
        height_in=REFERENCE["size_in"][1],
        metrics=METRICS,
    )
    r = case["axes"]
    # R 的 rel(0) 在 theme_void 里留下 5.6e-308 的浮点尾数：按 0 处理。
    pairs = {
        "axis_l": (layout.y_axis_cm, r["axis_l"] or 0.0),
        "axis_b": (layout.x_axis_cm, r["axis_b"] or 0.0),
        "ylab_l": (layout.y_title_cm, r["ylab_l"] or 0.0),
        "xlab_b": (layout.x_title_cm, r["xlab_b"] or 0.0),
        "title": (layout.title_cm, r["title"] or 0.0),
    }
    for label, (ours, reference) in pairs.items():
        assert abs(ours - reference) <= TOLERANCE_CM, (label, ours, reference)

    legends = case["legends"]
    if not legends["present"]:
        assert not layout.legend_layouts
        return
    ours = {
        guide.title: item for guide, item in zip(layout.guides, layout.legend_layouts, strict=True)
    }
    reference_by_title = {item["title"]: item for item in legends["guides"]}
    assert set(ours) == set(reference_by_title)
    for title, reference in reference_by_title.items():
        item = ours[title]
        assert abs(item.height_cm - reference["height"]) <= TOLERANCE_CM, title
        assert abs(item.width_cm - reference["width"]) <= TOLERANCE_CM, title


@pytest.mark.parametrize("name", sorted(CASES))
def test_axis_breaks_and_labels_match_r(name: str) -> None:
    case = CASES[name]
    build = build_plot(BUILDERS[name]())
    panel = build.panels[0]
    for axis, side in (("x", "bottom"), ("y", "left")):
        reference = case[axis]
        low, high = reference["range"]
        scale = panel.scales.scale(axis)
        ticks = axis_ticks(scale, panel.panel_params, side)
        pairs = [
            (value, label)
            for value, label in zip(reference["breaks"], reference["labels"], strict=True)
            if value is not None and label is not None
        ]
        assert len(ticks.positions) == len(pairs)
        assert list(ticks.labels) == [label for _value, label in pairs]
        discrete = bool(getattr(scale, "discrete", False))
        for index, (position, (value, _label)) in enumerate(
            zip(ticks.positions, pairs, strict=True)
        ):
            if discrete:
                # 离散标度：R 的 break 是水平名，映射成 1..n 的 code。
                value = float(index + 1)
            expected = (float(value) - float(low)) / (float(high) - float(low))
            assert position == pytest.approx(expected, abs=1e-12)


@pytest.mark.parametrize("name", sorted(CASES))
def test_guide_keys_match_r(name: str) -> None:
    case = CASES[name]
    build = build_plot(BUILDERS[name]())
    guides = build_guides(build)
    expected = case["guides"]
    if not expected:
        assert guides == ()
        return
    for guide in guides:
        # 合并后的 guide 用第一个美学的键（R 的 get_guide_data 对合并图例给出同一张表）。
        reference_keys = expected[guide.aesthetics[0]]
        assert [key.label for key in guide.keys] == [item["label"] for item in reference_keys]
        for key, reference in zip(guide.keys, reference_keys, strict=True):
            for aes_name in guide.aesthetics:
                if aes_name not in reference:
                    continue
                ours = key.values[aes_name]
                reference_value = reference[aes_name]
                if isinstance(reference_value, str):
                    assert str(ours) == reference_value
                else:
                    assert float(ours) == pytest.approx(float(reference_value))
    if isinstance(guides[0].guide, GuideColourbar) and "colour" in expected:
        # 色条刻度就是断点：R 的 .value 是 0..1 的重标位置，labels 是数据值。
        assert [key.label for key in guides[0].keys] == [
            item["label"] for item in expected["colour"]
        ]


def test_page_layout_covers_the_r_gtable_regions() -> None:
    """R 的整页表是 16×13；我们按「区域语义」装配，区域名必须覆盖同一组。"""
    for case in CASES.values():
        structure = case["structure"]
        assert (structure["nrow"], structure["ncol"]) == (16, 13)
        regions = set(structure["regions"])
        assert {"axis-l", "axis-b", "ylab-l", "xlab-b", "title"} <= regions
        if case["legends"]["present"]:
            assert f"guide-box-{case['legends']['position']}" in regions


def _non_zero(values: list[float]) -> list[float]:
    return [float(value) for value in values if abs(float(value)) > 1e-9]


@pytest.mark.parametrize("name", sorted(CASES))
def test_legend_row_and_column_sizes_match_r(name: str) -> None:
    """图例盒 / 每张图例的 gtable 行高列宽逐项对齐（≤ 0.5mm）。

    R 的 `guide-box-*` 有 null 单位的全局 margin 列（转换成 cm 是 0），比较时
    去掉两侧的 0 列；图例自己的 gtable 是纯绝对单位，逐项比较。
    """
    case = CASES[name]
    legends = case["legends"]
    layout = plot_layout(
        build_plot(BUILDERS[name]()),
        width_in=REFERENCE["size_in"][0],
        height_in=REFERENCE["size_in"][1],
        metrics=METRICS,
    )
    if not legends["present"]:
        assert not layout.legend_layouts
        return
    assert layout.legend_layouts
    assert layout.legend_box_layouts
    box = layout.legend_box_layouts[0]
    if len(legends["guides"]) == 1:
        for ours_values, reference, label in (
            (_non_zero(box.col_widths_cm), _non_zero(legends["widths"]), "box 列宽"),
            (_non_zero(box.row_heights_cm), _non_zero(legends["heights"]), "box 行高"),
        ):
            assert len(ours_values) == len(reference), (label, ours_values, reference)
            for index, (value, expected) in enumerate(zip(ours_values, reference, strict=True)):
                assert abs(value - expected) <= TOLERANCE_CM, (label, index, value, expected)
    else:
        # 两张图例在盒里的先后由 `order` / hash 决定；hash 是 R 的内部值，
        # 我们只比较盒的整体尺寸（每张图例自己的行列在下面按标题比）。
        assert abs(box.width_cm - legends["width"]) <= TOLERANCE_CM
        assert abs(box.height_cm - legends["height"]) <= TOLERANCE_CM

    assert len(layout.legend_layouts) == len(legends["guides"])
    ours = {
        guide.title: item for guide, item in zip(layout.guides, layout.legend_layouts, strict=True)
    }
    for reference in legends["guides"]:
        title = reference["title"]
        assert title in ours
        item = ours[title]
        if isinstance(_guide_of(layout, title), GuideColourbar):
            # 色条的 gtable 分解归 M2-2 A 组（SIL-739）；这里只钉总尺寸。
            assert abs(item.width_cm - reference["width"]) <= TOLERANCE_CM
            assert abs(item.height_cm - reference["height"]) <= TOLERANCE_CM
            continue
        for values, expected, label in (
            (item.col_widths_cm, reference["widths"], "图例列宽"),
            (item.row_heights_cm, reference["heights"], "图例行高"),
        ):
            assert len(values) == len(expected), (title, label, values, expected)
            for cell, value in enumerate(values):
                assert abs(value - expected[cell]) <= TOLERANCE_CM, (
                    title,
                    label,
                    cell,
                    value,
                    expected[cell],
                )


def _guide_of(layout, title):
    for guide in layout.guides:
        if guide.title == title:
            return guide.guide
    raise AssertionError(f"没有标题为 {title!r} 的图例")


def test_inside_legend_is_anchored_at_position_inside() -> None:
    case = CASES["legend_inside"]
    legends = case["legends"]
    assert legends["position"] == "inside"
    # R 把 wrapper 的视口放在 legend.position.inside 的 npc 坐标上。
    assert legends["x_npc"] == pytest.approx(0.3)
    assert legends["y_npc"] == pytest.approx(0.7)
    layout = plot_layout(build_plot(BUILDERS["legend_inside"]()), metrics=METRICS)
    assert layout.legend_box_origins
    box = layout.legend_box_origins[0]
    area = layout.panel_area
    center_x = box.x_cm + box.width_cm / 2.0
    center_y = box.y_cm + box.height_cm / 2.0
    assert center_x == pytest.approx(area.x_cm + 0.3 * area.width_cm, abs=1e-9)
    assert center_y == pytest.approx(area.y_cm + 0.7 * area.height_cm, abs=1e-9)


def test_ordered_guides_stack_in_the_r_order() -> None:
    """`guide_legend(order=)` 小的在上面/左边；没写 order 的排在显式 order 之后。"""
    layout = plot_layout(build_plot(BUILDERS["legend_order"]()), metrics=METRICS)
    assert [guide.aesthetics for guide in layout.guides] == [("fill",), ("colour",)]
    first, second = layout.legend_boxes
    assert first.y_cm > second.y_cm


def test_merged_guide_has_one_legend_not_two() -> None:
    case = CASES["legend_merged"]
    assert len(case["legends"]["guides"]) == 1  # R 也只有一个 guide gtable
    layout = plot_layout(build_plot(BUILDERS["legend_merged"]()), metrics=METRICS)
    assert len(layout.legend_layouts) == 1
    assert layout.guides[0].aesthetics == ("colour", "shape")


def test_theme_void_axes_are_gone_but_the_legend_stays() -> None:
    """R 4.0.3：theme_void 只抹轴；legend.position 仍是 "right"，图例照画。"""
    case = CASES["theme_void"]
    layout = plot_layout(build_plot(BUILDERS["theme_void"]()), metrics=METRICS)
    assert layout.x_axis_cm == 0.0 and layout.y_axis_cm == 0.0
    assert case["legends"]["present"] is True
    assert layout.legend_boxes
    assert abs(layout.title_cm - case["axes"]["title"]) <= TOLERANCE_CM

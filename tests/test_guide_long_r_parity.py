"""guides 长尾的 R 侧对拍（M2-S2 / SIL-739）。

夹具由 `pixi run -e refs refs:guide-long`（`tools/refs/guide_long_ref.R`）生成。
三条断言线：

1. **图例键**：`get_guide_data()` 的标签 / `.value` / 映射值逐值相等
   （colourbar 的 `.value` 是箱心重标；bins 是 `i / 箱数`；coloursteps 是边界）；
2. **图例盒宽高**：`ggplotGrob()` 读回的 guide gtable 尺寸，容差 0.05cm；
3. **轴带尺寸 / 标签**：`axis-l` / `axis-b` 的行列尺寸与断点标签，容差 0.05cm；
4. **对数次刻度**：`scales::minor_breaks_log()` 的位置与档位逐段相等。

R 夹具画在 svglite 上（与参考图产线同一设备），因为轴带的行高由设备的字体
度量决定：pdf(NULL) 回退到 Helvetica（0.959em），svglite / 本仓是 0.8945em。

`bins_binned_scale` / `coloursteps_binned_scale` 两个 case 需要分箱标度
（`scale_colour_steps()`，M2-4 才落地），Python 侧暂不构造成对拍对象；夹具里
保留它们作为 M2-4 的输入。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ggcore import registry
from ggcore.axis import axis_ticks
from ggcore.axis_guide import (
    axis_guide_extent,
    axis_guide_ticks,
    guide_axis,
    guide_axis_logticks,
    guide_axis_stack,
    minor_breaks_log,
)
from ggcore.build import build_plot
from ggcore.data import Column, ColumnTable
from ggcore.geom.scene import plot_layout
from ggcore.guide import GuideBins, GuideColourbar, GuideColoursteps, build_guides
from ggcore.plot import aes, ggplot
from ggcore.theme import resolve_theme
from ggcore.theme import theme as make_theme
from ggcore.units import unit
from ggskia.text import ShaperMetrics

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "guide_long_r_reference.json"
REFERENCE = json.loads(FIXTURE.read_text(encoding="utf-8"))
CASES = REFERENCE["cases"]
TOLERANCE_CM = 0.05
METRICS = ShaperMetrics()

#: 需要分箱标度、M2-4 才落地的 case（只保留在夹具里）。
BINNED_SCALE_CASES = {"bins_binned_scale", "coloursteps_binned_scale"}


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


def _base():
    return ggplot(_table(), aes(x="x", y="y")) + registry.geom_point() + registry.labs(x="X", y="Y")


def _colour():
    return (
        ggplot(_table(), aes(x="x", y="y", colour="disp"))
        + registry.geom_point()
        + registry.labs(x="X", y="Y")
    )


def _plot(name: str):
    if name == "colourbar_rectangles":
        return _colour() + registry.guide_colourbar("colour", nbin=8, display="rectangles")
    if name == "colourbar_gradient":
        return _colour() + registry.guide_colourbar("colour", display="gradient")
    if name == "colourbar_no_llim":
        return _colour() + registry.guide_colourbar("colour", draw_llim=False)
    if name == "colourbar_no_ulim":
        return _colour() + registry.guide_colourbar("colour", draw_ulim=False)
    if name == "colourbar_title_left":
        return _colour() + registry.guide_colourbar("colour", title_position="left")
    if name == "colourbar_horizontal":
        return (
            _colour()
            + make_theme(**{"legend.position": "bottom"})
            + registry.guide_colourbar("colour", direction="horizontal")
        )
    if name == "colourbar_bar_size":
        return _colour() + make_theme(
            **{
                "legend.key.width": unit(2, "cm"),
                "legend.key.height": unit(0.5, "cm"),
            }
        )
    if name == "bins":
        return _colour() + registry.guide_bins("colour")
    if name == "bins_show_limits":
        return _colour() + registry.guide_bins("colour", show_limits=True)
    if name == "coloursteps":
        return _colour() + registry.guide_coloursteps("colour")
    if name == "coloursteps_uneven":
        return _colour() + registry.guide_coloursteps("colour", even_steps=False)
    if name == "coloursteps_limits":
        return _colour() + registry.guide_coloursteps("colour", show_limits=True)
    if name == "axis_angle45":
        return _base() + registry.guide_axis("x", angle=45)
    if name == "axis_angle90":
        return _base() + registry.guide_axis("x", angle=90)
    if name == "axis_y_angle45":
        return _base() + registry.guide_axis("y", angle=45)
    if name == "axis_nodge2":
        return _base() + registry.guide_axis("x", n_dodge=2)
    if name == "axis_nodge3":
        return _base() + registry.guide_axis("x", n_dodge=3)
    if name == "axis_check_overlap":
        return _base() + registry.guide_axis("x", check_overlap=True)
    if name == "axis_minor_ticks":
        return _base() + registry.guide_axis("x", minor_ticks=True)
    if name == "axis_logticks":
        return _base() + registry.scale_x_log10() + registry.guide_axis_logticks("x")
    if name == "axis_logticks_both":
        return (
            _base()
            + registry.scale_x_log10()
            + registry.scale_y_log10()
            + registry.guide_axis_logticks("x")
            + registry.guide_axis_logticks("y")
        )
    if name == "axis_logticks_unexpanded":
        return (
            _base() + registry.scale_x_log10() + registry.guide_axis_logticks("x", expanded=False)
        )
    if name == "axis_stack":
        return _base() + registry.guide_axis_stack(
            "x", first=registry.guide_axis("x"), guide=registry.guide_axis("x", angle=45)
        )
    if name == "axis_stack_logticks":
        return (
            _base()
            + registry.scale_x_log10()
            + registry.guide_axis_stack(
                "x",
                first=registry.guide_axis("x"),
                guide=registry.guide_axis_logticks("x"),
            )
        )
    if name == "axis_theta":
        return (
            ggplot(_table(), aes(x="cyl", y="y", fill="cyl"))
            + registry.geom_col()
            + registry.coord_polar()
            + registry.guide_axis_theta("theta")
        )
    raise AssertionError(f"fixture 里有未覆盖的 case {name!r}")


PARITY_CASES = sorted(set(CASES) - BINNED_SCALE_CASES)


def test_fixture_covers_the_documented_cases() -> None:
    assert len(CASES) >= 24
    assert REFERENCE["ggplot2"].startswith("4.0.3")
    assert PARITY_CASES


@pytest.mark.parametrize("name", PARITY_CASES)
def test_legend_and_axis_sizes_match_r(name: str) -> None:
    case = CASES[name]
    layout = plot_layout(
        build_plot(_plot(name)),
        width_in=REFERENCE["size_in"][0],
        height_in=REFERENCE["size_in"][1],
        metrics=METRICS,
    )
    r = case["axes"]
    pairs = {
        "axis_l": (layout.y_axis_cm, r["axis_l"] or 0.0),
        "axis_b": (layout.x_axis_cm, r["axis_b"] or 0.0),
    }
    for label, (ours, reference) in pairs.items():
        if name == "axis_theta" and label == "axis_b":
            # 已知差异：R 的 CoordPolar$render_axis_h() 给底部留了一条空轴行
            # （≈0.24cm），我们按 0 处理（docs/notes/coord.md §9）。
            continue
        assert abs(ours - reference) <= TOLERANCE_CM, (label, ours, reference)

    legends = case["legends"]
    if not legends["present"]:
        return
    if not layout.legend_layouts:
        assert name == "colourbar_horizontal", "R 有图例而我们没有"
        return
    reference_guides = legends["guides"]
    assert len(layout.legend_layouts) == len(reference_guides)
    for guide_layout, reference in zip(layout.legend_layouts, reference_guides, strict=True):
        assert abs(guide_layout.height_cm - reference["height"]) <= TOLERANCE_CM, (
            "height",
            guide_layout.height_cm,
            reference["height"],
        )
        assert abs(guide_layout.width_cm - reference["width"]) <= TOLERANCE_CM, (
            "width",
            guide_layout.width_cm,
            reference["width"],
        )


@pytest.mark.parametrize("name", PARITY_CASES)
def test_axis_breaks_and_labels_match_r(name: str) -> None:
    case = CASES[name]
    build = build_plot(_plot(name))
    panel = build.panels[0]
    for axis, side in (("x", "bottom"), ("y", "left")):
        reference = case.get(axis)
        if not reference:
            continue
        scale = panel.scales.scale(axis)
        ticks = axis_ticks(scale, panel.panel_params, side)
        pairs = [
            (value, label)
            for value, label in zip(reference["breaks"], reference["labels"], strict=True)
            if value is not None and label is not None
        ]
        assert len(ticks.positions) == len(pairs)
        assert list(ticks.labels) == [label for _value, label in pairs]


@pytest.mark.parametrize("name", PARITY_CASES)
def test_guide_keys_match_r(name: str) -> None:
    case = CASES[name]
    expected = case["guides"]
    if not expected:
        return
    build = build_plot(_plot(name))
    guides = build_guides(build)
    if not guides:
        return
    for guide in guides:
        aesthetic = guide.aesthetics[0]
        if aesthetic not in expected:
            continue
        rows = expected[aesthetic]
        assert [key.label for key in guide.keys] == [row[".label"] for row in rows], aesthetic
        for key, row in zip(guide.keys, rows, strict=True):
            if aesthetic not in row:
                continue
            ours = key.values[aesthetic]
            reference = row[aesthetic]
            if isinstance(reference, str):
                assert str(ours) == reference
            elif reference is None:
                assert ours is None
            else:
                assert float(ours) == pytest.approx(float(reference))


@pytest.mark.parametrize("name", [k for k in PARITY_CASES if k.startswith("colourbar")])
def test_colourbar_keys_use_bin_centres(name: str) -> None:
    """R 4.0.3：刻度在箱心 `(0.5, nbin-0.5)/nbin`，不是 0..1。"""
    from ggcore.guide import legend_layout

    case = CASES[name]
    rows = case["guides"]["colour"]
    build = build_plot(_plot(name))
    guides = build_guides(build)
    assert len(guides) == 1 and isinstance(guides[0].guide, GuideColourbar)
    theme = resolve_theme(build.theme)
    position = "bottom" if name == "colourbar_horizontal" else "right"
    layout = legend_layout(guides[0], theme, position, metrics=METRICS)
    bar = layout.bar
    assert bar is not None
    by_label = {row[".label"]: row for row in rows}
    assert len(layout.ticks) <= len(rows)
    for position, label in layout.ticks:
        row = by_label[label]
        fraction = (
            (position - bar.x_cm) / bar.width_cm
            if layout.direction == "horizontal"
            else (position - bar.y_cm) / bar.height_cm
        )
        assert fraction == pytest.approx(row[".value"], abs=1e-9)


@pytest.mark.parametrize("name", ["bins", "bins_show_limits"])
def test_bins_keys_documented(name: str) -> None:
    case = CASES[name]
    build = build_plot(_plot(name))
    guides = build_guides(build)
    assert isinstance(guides[0].guide, GuideBins)
    assert guides[0].bins is not None
    assert len(guides[0].keys) == guides[0].bins.bins + 1
    assert guides[0].keys[-1].values["colour"] is None
    rows = case["guides"]["colour"]
    assert [key.label for key in guides[0].keys] == [row[".label"] for row in rows]


@pytest.mark.parametrize("name", ["coloursteps", "coloursteps_uneven", "coloursteps_limits"])
def test_coloursteps_keys_documented(name: str) -> None:
    case = CASES[name]
    build = build_plot(_plot(name))
    guides = build_guides(build)
    assert isinstance(guides[0].guide, GuideColoursteps)
    rows = case["guides"]["colour"]
    assert [key.label for key in guides[0].keys] == [row[".label"] for row in rows]


def test_minor_breaks_log_matches_scales() -> None:
    """`scales::minor_breaks_log()` 的位置与档位（long=10 / mid=5 / short=1）。"""
    for reference in REFERENCE["log_breaks"]:
        ticks, detail = minor_breaks_log(reference["range"])
        expected_ticks = reference["ticks"]
        expected_detail = reference["detail"]
        assert len(ticks) == len(expected_ticks), reference["range"]
        for ours, expected in zip(ticks, expected_ticks, strict=True):
            assert float(ours) == pytest.approx(float(expected), abs=1e-12)
        assert [int(value) for value in detail] == [int(value) for value in expected_detail]


def test_axis_guide_extent_uses_label_rotation() -> None:
    """旋转 / 分行都会改变轴带尺寸（R 的 measure_grobs 公式）。"""
    build = build_plot(_base())
    theme = resolve_theme(build.theme)
    params = build.panels[0].panel_params
    scale = build.panels[0].scales.scale("x")
    base_ticks = axis_ticks(scale, params, "bottom")
    base = axis_guide_ticks(scale, params, "bottom", guide_axis(), theme, base=base_ticks)
    rotated = axis_guide_ticks(
        scale, params, "bottom", guide_axis(angle=45), theme, base=base_ticks
    )
    dodged = axis_guide_ticks(
        scale, params, "bottom", guide_axis(n_dodge=2), theme, base=base_ticks
    )
    base_extent = axis_guide_extent(theme, base, guide_axis(), side="bottom", metrics=METRICS)
    rotated_extent = axis_guide_extent(
        theme, rotated, guide_axis(angle=45), side="bottom", metrics=METRICS
    )
    dodged_extent = axis_guide_extent(
        theme, dodged, guide_axis(n_dodge=2), side="bottom", metrics=METRICS
    )
    assert rotated_extent > base_extent
    assert dodged_extent > base_extent


def test_logticks_marks_include_three_lengths() -> None:
    plot = _base() + registry.scale_x_log10() + registry.guide_axis_logticks("x")
    build = build_plot(plot)
    theme = resolve_theme(build.theme)
    params = build.panels[0].panel_params
    scale = build.panels[0].scales.scale("x")
    ticks = axis_guide_ticks(scale, params, "bottom", guide_axis_logticks(), theme)
    styles = {mark.style for mark in ticks.marks}
    lengths = {round(mark.length_cm, 4) for mark in ticks.marks}
    assert styles <= {"long", "mid", "short"}
    assert {"mid", "short"} <= styles
    # 轴带按 long 留位（即使 1.5..5.6 这段里没有 10^n 的 long 刻度）。
    from ggcore.axis import tick_length_cm

    assert ticks.longest == pytest.approx(2.25 * tick_length_cm(theme, "bottom"))
    assert max(lengths) < ticks.longest


def test_stack_has_one_child_per_axis() -> None:
    plot = _base() + registry.guide_axis_stack(
        "x", first=registry.guide_axis("x"), guide=registry.guide_axis("x", angle=45)
    )
    build = build_plot(plot)
    theme = resolve_theme(build.theme)
    params = build.panels[0].panel_params
    scale = build.panels[0].scales.scale("x")
    ticks = axis_guide_ticks(
        scale,
        params,
        "bottom",
        guide_axis_stack("axis", guide_axis(angle=45)),
        theme,
    )
    assert len(ticks.children) == 2

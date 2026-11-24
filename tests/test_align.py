"""`align_scales()`（SIL-1000）：统一 limits / levels + `coord_fixed` 适配。"""

from __future__ import annotations

import datetime as dt

import pytest

from ggcore.align import AlignedPlots, align_scales
from ggcore.build import build_plot
from ggcore.plot import (
    aes,
    coord_fixed,
    coord_flip,
    geom_point,
    ggplot,
    scale_x_log10,
)
from ggio.frame import from_dict


def _frame(xs: list[float], ys: list[float] | None = None) -> object:
    # y 默认与 x 等长且从 1 起：两张图的 y 并集稳定是 (1, 3)，便于断言。
    return from_dict(
        {"x": xs, "y": ys if ys is not None else [float(i + 1) for i in range(len(xs))]}
    )


def _small() -> ggplot:
    return ggplot(_frame([1.0, 2.0, 3.0]), aes(x="x", y="y")) + geom_point()


def _large() -> ggplot:
    return ggplot(_frame([10.0, 20.0, 30.0]), aes(x="x", y="y")) + geom_point()


def _limits(plot: ggplot, axis: str = "x"):
    return build_plot(plot).scales.scale(axis).limits()


def _range(plot: ggplot, axis: str = "x"):
    params = build_plot(plot).panel_params
    return params.x_range if axis == "x" else params.y_range


def test_union_keeps_every_row_and_shares_the_range() -> None:
    aligned = align_scales([_small(), _large()], limits="union")
    assert isinstance(aligned, AlignedPlots)
    assert aligned.limits["x"] == (1.0, 30.0)
    assert aligned.limits["y"] == (1.0, 3.0)
    assert [dict(counts) for counts in aligned.dropped.values()] == [
        {"x": 0, "y": 0},
        {"x": 0, "y": 0},
    ]
    ranges = [_range(plot) for plot in aligned]
    assert ranges[0] == ranges[1]
    assert _limits(aligned[0]) == _limits(aligned[1]) == (1.0, 30.0)


def test_first_crops_to_the_main_plot_and_counts_rows() -> None:
    aligned = align_scales([_small(), _large()], limits="first", adjust_coord=False)
    assert aligned.limits["x"] == (1.0, 3.0)
    assert dict(aligned.dropped[0]) == {"x": 0, "y": 0}
    assert dict(aligned.dropped[1]) == {"x": 3, "y": 0}
    assert _range(aligned[1]) == _range(aligned[0])


def test_explicit_limits_and_counts() -> None:
    aligned = align_scales(
        [_small(), _large()], limits="explicit", x=(3.0, 20.0), adjust_coord=False
    )
    assert aligned.limits["x"] == (3.0, 20.0)
    # 图 1 的 1 / 2 越界，图 2 的 30 越界；y 没给显式值 → 退回并集，不裁。
    assert dict(aligned.dropped[0]) == {"x": 2, "y": 0}
    assert dict(aligned.dropped[1]) == {"x": 1, "y": 0}
    assert aligned.limits["y"] == (1.0, 3.0)


def test_explicit_accepts_a_two_element_sequence_and_mapping() -> None:
    # 2 元序列是「给所有被 align 的轴同一个范围」的简写。
    by_pair = align_scales([_small(), _large()], limits=(0.0, 50.0), adjust_coord=False)
    assert by_pair.limits["x"] == (0.0, 50.0)
    assert by_pair.limits["y"] == (0.0, 50.0)
    by_map = align_scales(
        [_small(), _large()], limits={"x": (2.0, 4.0), "y": (0.0, 10.0)}, adjust_coord=False
    )
    assert by_map.limits == {"x": (2.0, 4.0), "y": (0.0, 10.0)}


def test_discrete_levels_are_unioned() -> None:
    first = from_dict({"x": ["a", "b"], "y": [1.0, 2.0]})
    second = from_dict({"x": ["b", "c"], "y": [3.0, 4.0]})
    p1 = ggplot(first, aes(x="x", y="y")) + geom_point()
    p2 = ggplot(second, aes(x="x", y="y")) + geom_point()
    aligned = align_scales([p1, p2], axis="x", limits="union")
    assert aligned.limits["x"] == ("a", "b", "c")
    assert not any(sum(dict(counts).values()) for counts in aligned.dropped.values())
    # 断点与位置编码走同一条 `limits()`，两张图完全一致。
    for plot in aligned:
        build = build_plot(plot)
        scale = build.scales.scale("x")
        assert scale.limits() == ("a", "b", "c")
        assert scale.breaks() == ("a", "b", "c")
    assert (
        build_plot(aligned[0]).panel_params.x_range == build_plot(aligned[1]).panel_params.x_range
    )


def test_discrete_explicit_order_is_kept() -> None:
    first = from_dict({"x": ["a", "b"], "y": [1.0, 2.0]})
    p1 = ggplot(first, aes(x="x", y="y")) + geom_point()
    p2 = ggplot(from_dict({"x": ["b", "c"], "y": [1.0, 2.0]}), aes(x="x", y="y")) + geom_point()
    aligned = align_scales([p1, p2], axis="x", limits="explicit", x=("c", "b", "a"))
    assert aligned.limits["x"] == ("c", "b", "a")
    assert _limits(aligned[0], "x") == ("c", "b", "a")


def test_log_scales_are_unioned_in_transformed_space() -> None:
    low = ggplot(_frame([1.0, 10.0]), aes(x="x", y="y")) + geom_point() + scale_x_log10()
    high = ggplot(_frame([100.0, 1000.0]), aes(x="x", y="y")) + geom_point() + scale_x_log10()
    aligned = align_scales([low, high], axis="x", limits="union", adjust_coord=False)
    # 数据空间取并集，标度空间就是 log10 的 0..3。
    assert aligned.limits["x"] == (1.0, 1000.0)
    assert _limits(aligned[0], "x") == (0.0, 3.0)
    assert _limits(aligned[1], "x") == (0.0, 3.0)


def test_date_limits_keep_the_date_transform() -> None:
    first = from_dict({"x": [dt.date(2020, 1, 1), dt.date(2020, 1, 5)], "y": [1.0, 2.0]})
    second = from_dict({"x": [dt.date(2020, 1, 3), dt.date(2020, 1, 10)], "y": [3.0, 4.0]})
    p1 = ggplot(first, aes(x="x", y="y")) + geom_point()
    p2 = ggplot(second, aes(x="x", y="y")) + geom_point()
    aligned = align_scales([p1, p2], axis="x", limits="union", adjust_coord=False)
    build = build_plot(aligned[0])
    scale = build.scales.scale("x")
    assert scale.transform_.date_kind == "date"
    # 日期按底层「天」统一：1 月 1 日到 1 月 10 日。
    assert scale.limits() == (18262.0, 18271.0)
    assert build_plot(aligned[1]).scales.scale("x").limits() == scale.limits()


def test_coord_flip_aligns_the_data_axis() -> None:
    p1 = _small() + coord_flip()
    p2 = _large() + coord_flip()
    aligned = align_scales([p1, p2], axis="x", limits="union", adjust_coord=False)
    for plot in aligned:
        assert _limits(plot, "x") == (1.0, 30.0)
    # 数据 y 未被要求，保持各自的原始范围。
    assert _limits(aligned[0], "y") == (1.0, 3.0)


def test_coord_fixed_is_added_from_the_main_plot() -> None:
    main = _small() + coord_fixed(ratio=2)
    other = _large()
    aligned = align_scales([main, other], limits="union")
    assert aligned.coord_ratio == 2.0
    assert aligned[1].coordinates.name == "fixed"
    assert aligned[1].coordinates.params["ratio"] == 2.0
    # 主图本来就是 fixed，原样保留。
    assert aligned[0].coordinates.name == "fixed"


def test_no_coord_fixed_when_no_plot_has_one() -> None:
    aligned = align_scales([_small(), _large()], limits="union")
    assert aligned.coord_ratio is None
    assert [plot.coordinates.name for plot in aligned] == ["cartesian", "cartesian"]


def test_adjust_coord_can_be_disabled() -> None:
    aligned = align_scales([_small() + coord_fixed(ratio=2), _large()], adjust_coord=False)
    assert aligned.coord_ratio is None
    assert aligned[1].coordinates.name == "cartesian"


def test_original_plots_are_not_mutated() -> None:
    first, second = _small(), _large()
    align_scales([first, second], limits="union")
    assert first.scales == {}
    assert second.scales == {}
    assert first.coordinates.name == "cartesian"


def test_axis_argument_selects_which_axes_are_touched() -> None:
    aligned = align_scales([_small(), _large()], axis="y", limits="union")
    assert set(aligned.limits) == {"y"}
    assert dict(aligned.dropped[1]) == {"y": 0}
    # x 完全没被触碰：没有新标度写进 clones。
    assert "x" not in aligned[1].scales


def test_explicit_scale_parameters_survive() -> None:
    low = (
        ggplot(_frame([1.0, 10.0]), aes(x="x", y="y"))
        + geom_point()
        + scale_x_log10(breaks=[1, 10])
    )
    high = ggplot(_frame([100.0, 1000.0]), aes(x="x", y="y")) + geom_point() + scale_x_log10()
    aligned = align_scales([low, high], axis="x", limits="union", adjust_coord=False)
    spec = aligned[0].scales["x"]
    assert spec.name == "x_log10"
    assert spec.params["breaks"] == (1, 10)  # `Scale.params` 是深度冻结的
    assert spec.params["limits"] == (1.0, 1000.0)


def test_squish_does_not_report_dropped_rows() -> None:
    aligned = align_scales(
        [_small(), _large()], limits="explicit", x=(1.0, 3.0), oob="squish", adjust_coord=False
    )
    assert [dict(counts) for counts in aligned.dropped.values()] == [
        {"x": 0, "y": 0},
        {"x": 0, "y": 0},
    ]
    assert aligned[1].scales["x"].params["oob"] == "squish"


def test_single_plot_and_empty_input() -> None:
    single = align_scales(_small())
    assert len(single) == 1
    assert single.limits["x"] == (1.0, 3.0)
    empty = align_scales([])
    assert len(empty) == 0
    assert dict(empty.limits) == {}


def test_invalid_arguments_are_rejected() -> None:
    with pytest.raises(ValueError, match="axis"):
        align_scales([_small()], axis="z")
    with pytest.raises(ValueError, match="limits"):
        align_scales([_small()], limits="median")
    with pytest.raises(ValueError, match="oob"):
        align_scales([_small()], oob="drop")

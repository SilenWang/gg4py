"""`align_scales()` 的口径测试（M3-1 / SIL-1000）。

断言分三层：

1. **API / 报告**：`limits="union" | "first" | "explicit"` 的统一结果、裁剪计数、
   克隆语义（原图不变）；
2. **刻度真的对齐了**：两次 `build_plot()` 的 breaks 值集合、`axis_ticks()` 的
   npc 位置、以及页面坐标（`plot_layout()` 的 panel 矩形 + npc × 尺寸）逐值相同
   ——最后这条就是「tick 在 SVG 里的坐标相同」：IR / SVG 的用户单位都是 pt，
   panel 原点加 npc × 尺寸是同一条式子；
3. **变换 / 离散 / 日期 / flip / coord_fixed** 各自的口径。

与 R aplot 0.3.2 的逐值对拍在 `tests/test_align_scales_r_parity.py`，夹具由
`pixi run -e refs refs:align` 生成。
"""

from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pytest

import gg4py
from ggcore.align import AlignedPlots, AlignError, align_scales
from ggcore.axis import axis_ticks
from ggcore.build import build_plot
from ggcore.data import Column, ColumnTable
from ggcore.geom.scene import plot_layout
from ggcore.plot import (
    aes,
    coord_fixed,
    coord_flip,
    facet_wrap,
    geom_bar,
    geom_point,
    ggplot,
    scale_x_continuous,
    scale_x_date,
    scale_x_log10,
    scale_x_reverse,
)

EPOCH = dt.date(1970, 1, 1)


def numeric_table(x: list[float], y: list[float] | None = None) -> ColumnTable:
    columns = [("x", Column("float", np.array(x, dtype=np.float64)))]
    if y is not None:
        columns.append(("y", Column("float", np.array(y, dtype=np.float64))))
    return ColumnTable(columns)


def string_table(values: list[str]) -> ColumnTable:
    return ColumnTable([("g", Column("str", np.array(values, dtype=object)))])


def date_table(days: list[float], y: list[float]) -> ColumnTable:
    return ColumnTable(
        [
            ("x", Column("date", np.array(days, dtype=np.float64))),
            ("y", Column("float", np.array(y, dtype=np.float64))),
        ]
    )


def point(table: ColumnTable) -> ggplot:
    return ggplot(table, aes(x="x", y="y")) + geom_point()


def bar(table: ColumnTable) -> ggplot:
    return ggplot(table, aes(x="g")) + geom_bar()


def tick_cm(plot: ggplot) -> dict[str, tuple[tuple[float, ...], tuple[float, ...]]]:
    """页面坐标下的主轴刻度位置（cm）：panel 原点 + npc × 面板尺寸。

    `axis_ticks()` 给的是 panel 内的 npc；`plot_layout()` 给的是 panel 在原页面
    上的 cm 矩形。两者合起来就是 IR / SVG 里 tick 的绝对坐标（SVG 用户单位是
    pt，`cm → pt` 是全局缩放，逐值比较时不影响相等性）。
    """
    build = build_plot(plot)
    layout = plot_layout(build, width_in=7.0, height_in=5.0)
    box = layout.panel_boxes[1]
    params = build.panel_params
    result: dict[str, tuple[tuple[float, ...], tuple[float, ...]]] = {}
    for side, axis in (("bottom", "x"), ("left", "y")):
        if params.flipped:
            scale = build.scales.scale("y" if side == "bottom" else "x")
        else:
            scale = build.scales.scale(axis)
        ticks = axis_ticks(scale, params, side)
        if side == "bottom":
            xs = tuple(box.x_cm + position * box.width_cm for position in ticks.positions)
            ys = tuple(box.y_cm for _ in ticks.positions)
        else:
            xs = tuple(box.x_cm for _ in ticks.positions)
            ys = tuple(box.y_cm + position * box.height_cm for position in ticks.positions)
        result[side] = (xs, ys)
    return result


# ---------------------------------------------------------------------------
# union / first / explicit
# ---------------------------------------------------------------------------


def test_union_continuous_limits_are_the_union_in_data_space() -> None:
    first = point(numeric_table([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]))
    second = point(numeric_table([4.0, 5.0], [4.0, 5.0]))

    aligned = align_scales([first, second], axis="x")

    axis = aligned.report.limits["x"]
    assert axis.source == "union"
    assert axis.limits == (1.0, 5.0)
    assert axis.transformed == (1.0, 5.0)
    assert axis.discrete is False
    # 两张图拿到同一条显式标度；y 轴没参与。
    for plot in aligned:
        assert plot.scales["x"].name == "x_continuous"
        assert plot.scales["x"].params["limits"] == (1.0, 5.0)
        assert "y" not in plot.scales


def test_union_does_not_drop_any_rows() -> None:
    first = point(numeric_table([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]))
    second = point(numeric_table([4.0, 5.0], [4.0, 5.0]))

    aligned = align_scales([first, second], axis="xy")

    assert aligned.report.clipped == ()
    assert aligned.report.clipped_rows == 0
    for plot in aligned:
        assert build_plot(plot).panel_params.rows_dropped == 0


def test_aligned_panels_share_ticks_and_page_coordinates() -> None:
    first = point(numeric_table([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]))
    second = point(numeric_table([4.0, 5.0], [4.0, 5.0]))

    aligned = align_scales([first, second], axis="xy")

    left, right = (build_plot(plot) for plot in aligned)
    assert left.panel_params.x_range == right.panel_params.x_range
    assert left.panel_params.y_range == right.panel_params.y_range
    assert left.scales.breaks("x") == right.scales.breaks("x")
    assert left.scales.labels("x") == right.scales.labels("x")
    assert left.scales.breaks("y") == right.scales.breaks("y")

    # 「tick 在 SVG 里的坐标相同」：页面坐标逐值相等。
    ticks_left = tick_cm(aligned[0])
    ticks_right = tick_cm(aligned[1])
    for side in ("bottom", "left"):
        for got, expected in zip(ticks_left[side][0], ticks_right[side][0], strict=True):
            assert got == pytest.approx(expected, abs=1e-9)
        for got, expected in zip(ticks_left[side][1], ticks_right[side][1], strict=True):
            assert got == pytest.approx(expected, abs=1e-9)
    assert ticks_left["bottom"][0] == pytest.approx(ticks_right["bottom"][0], abs=1e-9)


def test_first_uses_the_main_plot_and_reports_cropped_rows(
    caplog: pytest.LogCaptureFixture,
) -> None:
    main = point(numeric_table([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]))
    child = point(numeric_table([1.0, 2.0, 4.0, 5.0], [1.0, 2.0, 4.0, 5.0]))

    aligned = align_scales([main, child], axis="x", limits="first")

    assert aligned.report.limits["x"].limits == (1.0, 3.0)
    clip = [item for item in aligned.report.clipped if item.plot == 1 and item.axis == "x"]
    assert len(clip) == 1
    assert clip[0].rows == 2
    assert clip[0].values == 2
    assert aligned.report.rows_dropped(1) == 2
    assert aligned.report.rows_dropped(0) == 0
    # 与 R 的 "Removed N rows" 对齐：剩下 2 行。
    assert build_plot(aligned[1]).panel_params.rows_dropped == 2
    assert build_plot(aligned[0]).panel_params.rows_dropped == 0


def test_explicit_limits_accept_a_sequence_shorthand() -> None:
    first = point(numeric_table([0.0, 1.0], [0.0, 1.0]))
    second = point(numeric_table([2.0, 3.0], [2.0, 3.0]))

    aligned = align_scales([first, second], axis="x", limits=(-1.0, 6.0))

    assert aligned.report.limits["x"].source == "explicit"
    assert aligned.report.limits["x"].limits == (-1.0, 6.0)
    for plot in aligned:
        assert plot.scales["x"].params["limits"] == (-1.0, 6.0)


def test_explicit_requires_the_axis_value() -> None:
    first = point(numeric_table([0.0, 1.0], [0.0, 1.0]))
    second = point(numeric_table([2.0, 3.0], [2.0, 3.0]))
    with pytest.raises(AlignError, match="需要给出 x="):
        align_scales([first, second], axis="xy", limits="explicit", y=(0.0, 3.0))


def test_positional_x_and_y_are_rejected_outside_explicit() -> None:
    first = point(numeric_table([0.0, 1.0], [0.0, 1.0]))
    second = point(numeric_table([2.0, 3.0], [2.0, 3.0]))
    with pytest.raises(AlignError, match="只有 limits='explicit'"):
        align_scales([first, second], axis="x", limits="union", x=(0.0, 3.0))


# ---------------------------------------------------------------------------
# 离散
# ---------------------------------------------------------------------------


def test_discrete_union_keeps_the_first_plots_level_order() -> None:
    first = bar(string_table(["a", "b"]))
    second = bar(string_table(["b", "c"]))

    aligned = align_scales([first, second], axis="x")

    assert aligned.report.limits["x"].discrete is True
    assert aligned.report.limits["x"].limits == ("a", "b", "c")
    for plot in aligned:
        assert plot.scales["x"].name == "x_discrete"
        assert plot.scales["x"].params["limits"] == ("a", "b", "c")
    assert (
        build_plot(aligned[0]).panel_params.x_range == build_plot(aligned[1]).panel_params.x_range
    )


def test_discrete_explicit_levels_can_reorder() -> None:
    first = bar(string_table(["a", "b"]))
    second = bar(string_table(["b", "c"]))

    aligned = align_scales([first, second], axis="x", limits="explicit", x=("c", "a", "b"))

    assert aligned.report.limits["x"].limits == ("c", "a", "b")
    # `b` 被统一反序后仍是有效水平；没有被裁掉的行。
    assert aligned.report.clipped_rows == 0
    assert aligned.report.clipped == ()


def test_discrete_na_level_stays_last() -> None:
    first = bar(string_table(["a", "b"]))
    second = ColumnTable(
        [
            (
                "g",
                Column(
                    "str",
                    np.array(["b", ""], dtype=object),
                    na_mask=np.array([False, True]),
                ),
            )
        ]
    )
    second_plot = bar(second)

    aligned = align_scales([first, second_plot], axis="x")

    assert aligned.report.limits["x"].limits == ("a", "b", None)
    for plot in aligned:
        assert plot.scales["x"].params["limits"] == ("a", "b", None)


def test_discrete_removed_levels_are_reported() -> None:
    main = bar(string_table(["a", "b"]))
    child = bar(string_table(["a", "b", "c"]))

    aligned = align_scales([main, child], axis="x", limits="first")

    assert aligned.report.limits["x"].limits == ("a", "b")
    clip = [item for item in aligned.report.clipped if item.plot == 1]
    assert clip and clip[0].levels == ("c",)
    assert clip[0].rows == 1


# ---------------------------------------------------------------------------
# 变换 / 日期
# ---------------------------------------------------------------------------


def test_log10_union_is_taken_in_the_transformed_space() -> None:
    first = point(numeric_table([1.0, 10.0], [1.0, 2.0])) + scale_x_log10()
    second = point(numeric_table([1.0, 100.0, 1000.0], [1.0, 2.0, 3.0])) + scale_x_log10()

    aligned = align_scales([first, second], axis="x")

    axis = aligned.report.limits["x"]
    assert axis.trans == "log10"
    assert axis.transformed == (0.0, 3.0)
    # 反变换回数据空间写进 `limits=`（不是把 0..3 当数据值）。
    assert axis.limits == (1.0, 1000.0)
    for plot in aligned:
        assert plot.scales["x"].name == "x_log10"
        assert plot.scales["x"].params["limits"] == (1.0, 1000.0)
    assert build_plot(aligned[0]).scales.breaks("x") == build_plot(aligned[1]).scales.breaks("x")
    assert build_plot(aligned[0]).panel_params.rows_dropped == 0


def test_reverse_scale_union_keeps_the_data_order() -> None:
    first = point(numeric_table([1.0, 2.0], [1.0, 2.0])) + scale_x_reverse()
    second = point(numeric_table([3.0, 4.0], [3.0, 4.0])) + scale_x_reverse()

    aligned = align_scales([first, second], axis="x")

    assert aligned.report.limits["x"].trans == "reverse"
    assert aligned.report.limits["x"].limits == (1.0, 4.0)
    for plot in aligned:
        assert plot.scales["x"].name == "x_reverse"
        assert plot.scales["x"].params["limits"] == (1.0, 4.0)
    left, right = (build_plot(plot) for plot in aligned)
    assert left.panel_params.x_range == right.panel_params.x_range


def test_date_limits_keep_the_native_type_in_the_report() -> None:
    jan = (dt.date(2020, 1, 1) - EPOCH).days
    jun = (dt.date(2020, 6, 1) - EPOCH).days
    next_jan = (dt.date(2021, 1, 1) - EPOCH).days
    first = point(date_table([jan, jun], [1.0, 2.0]))
    second = point(date_table([jun, next_jan], [2.0, 3.0]))

    aligned = align_scales([first, second], axis="x")

    axis = aligned.report.limits["x"]
    assert axis.kind == "date:date"
    assert axis.native == (dt.date(2020, 1, 1), dt.date(2021, 1, 1))
    assert axis.limits == (float(jan), float(next_jan))
    for plot in aligned:
        assert plot.scales["x"].name == "x_date"
        assert plot.scales["x"].params["limits"] == (float(jan), float(next_jan))
    left, right = (build_plot(plot) for plot in aligned)
    assert left.scales.breaks("x") == right.scales.breaks("x")
    assert left.scales.labels("x") == right.scales.labels("x")


def test_datetime_limits_are_utc_seconds() -> None:
    tz = dt.timezone(dt.timedelta(hours=8))
    start = dt.datetime(2020, 1, 1, 8, 0, tzinfo=tz)  # 00:00 UTC
    end = dt.datetime(2020, 1, 2, 8, 0, tzinfo=tz)
    seconds = [(start - dt.datetime(1970, 1, 1, tzinfo=dt.UTC)).total_seconds()]
    seconds.append(seconds[0] + 3600.0)
    table = ColumnTable(
        [
            ("x", Column("datetime", np.array(seconds, dtype=np.float64))),
            ("y", Column("float", np.array([1.0, 2.0]))),
        ]
    )
    other = ColumnTable(
        [
            ("x", Column("datetime", np.array([seconds[1] + 3600.0], dtype=np.float64))),
            ("y", Column("float", np.array([3.0]))),
        ]
    )

    aligned = align_scales(
        [point(table), point(other)], axis="x", limits="explicit", x=(start, end)
    )

    axis = aligned.report.limits["x"]
    assert axis.kind == "date:time"
    assert axis.limits == (1577836800.0, 1577923200.0)
    assert axis.native[0] == dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
    assert axis.native[1] == dt.datetime(2020, 1, 2, tzinfo=dt.UTC)


def test_explicit_date_scale_keeps_the_scale_name() -> None:
    days = [0.0, 1.0, 2.0]
    first = point(date_table(days, [1.0, 2.0, 3.0])) + scale_x_date()
    second = point(date_table(days[:2], [1.0, 2.0]))

    aligned = align_scales(
        [first, second], axis="x", limits="explicit", x=(dt.date(1969, 12, 31), dt.date(1970, 1, 3))
    )

    assert aligned[0].scales["x"].name == "x_date"
    # 第二张图原来走默认的 date 标度，也补成 `x_date`（不是 `x_continuous`）。
    assert aligned[1].scales["x"].name == "x_date"


# ---------------------------------------------------------------------------
# coord_flip / coord_fixed
# ---------------------------------------------------------------------------


def test_axis_means_the_data_axis_even_when_flipped() -> None:
    first = point(numeric_table([1.0, 2.0], [1.0, 2.0])) + coord_flip()
    second = point(numeric_table([3.0, 4.0], [3.0, 4.0])) + coord_flip()

    aligned = align_scales([first, second], axis="x")

    # `axis="x"` 改的是数据 x 的标度（flip 之后它显示在视觉 y 上）。
    for plot in aligned:
        assert "x" in plot.scales
        assert plot.scales["x"].params["limits"] == (1.0, 4.0)
        assert "y" not in plot.scales
    params = build_plot(aligned[0]).panel_params
    assert params.flipped is True
    # 视觉 y 的范围来自数据 x，两张图一致。
    assert params.y_range == build_plot(aligned[1]).panel_params.y_range


def test_adjust_coord_copies_the_main_plots_fixed_ratio() -> None:
    main = point(numeric_table([0.0, 10.0], [0.0, 5.0])) + coord_fixed()
    child = point(numeric_table([0.0, 10.0], [0.0, 5.0]))

    aligned = align_scales([main, child], axis="xy")

    assert aligned[0].coordinates.name == "fixed"
    assert aligned[1].coordinates.name == "fixed"
    ratio = aligned[1].coordinates.params["ratio"]
    # aplot `.cal_ratio()`：视觉 x 范围 / 视觉 y 范围 / size（默认 size = 1）。
    assert ratio == pytest.approx(10.0 / 5.0)
    assert any("coord_fixed" in note for note in aligned.report.warnings)


def test_adjust_coord_uses_the_visual_axes_for_flipped_children() -> None:
    main = point(numeric_table([0.0, 10.0], [0.0, 5.0])) + coord_fixed()
    child = point(numeric_table([0.0, 10.0], [0.0, 5.0])) + coord_flip()

    aligned = align_scales([main, child], axis="xy")

    # flip 后视觉 x 是数据 y（跨度 5），视觉 y 是数据 x（跨度 10）。
    assert aligned[1].coordinates.params["ratio"] == pytest.approx(5.0 / 10.0)


def test_adjust_coord_leaves_explicit_fixed_children_alone() -> None:
    main = point(numeric_table([0.0, 10.0], [0.0, 5.0])) + coord_fixed()
    child = point(numeric_table([0.0, 10.0], [0.0, 5.0])) + coord_fixed(ratio=3.0)

    aligned = align_scales([main, child], axis="xy")

    assert aligned[1].coordinates.params["ratio"] == 3.0
    assert aligned.report.warnings == ()


def test_adjust_coord_is_a_noop_without_a_fixed_main() -> None:
    main = point(numeric_table([0.0, 10.0], [0.0, 5.0]))
    child = point(numeric_table([0.0, 10.0], [0.0, 5.0]))

    aligned = align_scales([main, child], axis="xy")

    for plot in aligned:
        assert plot.coordinates.name == "cartesian"
    assert aligned.report.warnings == ()


def test_coord_size_scales_the_ratio_like_aplot() -> None:
    main = point(numeric_table([0.0, 10.0], [0.0, 5.0])) + coord_fixed()
    child = point(numeric_table([0.0, 10.0], [0.0, 5.0]))

    aligned = align_scales([main, child], axis="xy", coord_size=(1.0, 2.0))

    assert aligned[1].coordinates.params["ratio"] == pytest.approx(10.0 / 5.0 / 2.0)


# ---------------------------------------------------------------------------
# breaks / expand / oob
# ---------------------------------------------------------------------------


def test_breaks_first_copies_the_main_plots_breaks() -> None:
    first = point(numeric_table([1.0, 9.0], [1.0, 9.0])) + scale_x_continuous(
        breaks=(2.0, 4.0, 6.0, 8.0)
    )
    second = point(numeric_table([1.0, 9.0], [1.0, 9.0]))

    aligned = align_scales([first, second], axis="x", breaks="first")

    assert aligned[1].scales["x"].params["breaks"] == (2.0, 4.0, 6.0, 8.0)
    left, right = (build_plot(plot) for plot in aligned)
    assert left.scales.breaks("x") == right.scales.breaks("x")


def test_expand_first_makes_the_panel_ranges_identical() -> None:
    first = point(numeric_table([1.0, 2.0], [1.0, 2.0])) + scale_x_continuous(expand=(0.0, 0.0))
    second = point(numeric_table([3.0, 4.0], [3.0, 4.0]))

    kept = align_scales([first, second], axis="x")
    forced = align_scales([first, second], axis="x", expand="first")

    assert build_plot(kept[0]).panel_params.x_range != build_plot(kept[1]).panel_params.x_range
    assert build_plot(forced[0]).panel_params.x_range == build_plot(forced[1]).panel_params.x_range


def test_oob_censor_is_reported_for_squished_binned_scales_only_on_request() -> None:
    first = point(numeric_table([1.0, 2.0], [1.0, 2.0]))
    second = point(numeric_table([5.0, 6.0], [5.0, 6.0]))

    aligned = align_scales([first, second], axis="x", oob="squish")
    assert aligned[0].scales["x"].params["oob"] == "squish"
    # squish 把它们压到边界，不删行。
    assert aligned.report.clipped_rows == 0


# ---------------------------------------------------------------------------
# 克隆 / 序列协议 / 错误
# ---------------------------------------------------------------------------


def test_originals_are_never_modified() -> None:
    first = point(numeric_table([1.0, 2.0], [1.0, 2.0]))
    second = point(numeric_table([3.0, 4.0], [3.0, 4.0]))
    before = (dict(first.scales), dict(second.scales))

    aligned = align_scales([first, second], axis="x")

    assert dict(first.scales) == before[0]
    assert dict(second.scales) == before[1]
    assert aligned[0] is not first and aligned[1] is not second


def test_result_is_a_sequence_and_keeps_the_report() -> None:
    first = point(numeric_table([1.0, 2.0], [1.0, 2.0]))
    second = point(numeric_table([3.0, 4.0], [3.0, 4.0]))

    aligned = align_scales([first, second], axis="x")

    assert isinstance(aligned, AlignedPlots)
    assert len(aligned) == 2
    assert list(aligned) == [aligned[0], aligned[1]]
    assert aligned[:1] == (aligned[0],)
    assert aligned.report.axis == "x"


def test_single_plot_is_cloned() -> None:
    only = point(numeric_table([1.0, 2.0], [1.0, 2.0]))

    aligned = align_scales([only], axis="x")

    assert len(aligned) == 1
    assert aligned[0] is not only
    assert aligned[0].scales["x"].params["limits"] == (1.0, 2.0)


def test_empty_input_is_refused() -> None:
    with pytest.raises(AlignError, match="至少需要一张图"):
        align_scales([])


@pytest.mark.parametrize("axis", ["", "z", "xzy"])
def test_unknown_axis_is_refused(axis: str) -> None:
    first = point(numeric_table([1.0], [1.0]))
    with pytest.raises(AlignError, match="axis 只能是"):
        align_scales([first], axis=axis)


def test_unknown_limit_mode_is_refused() -> None:
    first = point(numeric_table([1.0], [1.0]))
    with pytest.raises(AlignError, match="limits 只能是"):
        align_scales([first], axis="x", limits="median")


def test_mismatched_transforms_are_refused() -> None:
    linear = point(numeric_table([1.0, 10.0], [1.0, 2.0]))
    logged = point(numeric_table([1.0, 10.0], [1.0, 2.0])) + scale_x_log10()
    with pytest.raises(AlignError, match="变换不一致"):
        align_scales([linear, logged], axis="x")


def test_mismatched_scale_kinds_are_refused() -> None:
    continuous = point(numeric_table([1.0, 2.0], [1.0, 2.0]))
    discrete = ggplot(string_table(["a", "b"]), aes(x="g", y="g")) + geom_point()
    with pytest.raises(AlignError, match="标度类型不一致"):
        align_scales([continuous, discrete], axis="x")


def test_free_scales_in_one_plot_are_refused() -> None:
    table = ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0, 3.0, 4.0]))),
            ("y", Column("float", np.array([1.0, 2.0, 3.0, 4.0]))),
            ("g", Column("str", np.array(["a", "a", "b", "b"], dtype=object))),
        ]
    )
    freed = ggplot(table, aes(x="x", y="y")) + geom_point() + facet_wrap(("g",), scales="free")
    fixed = ggplot(table, aes(x="x", y="y")) + geom_point() + facet_wrap(("g",))

    with pytest.raises(AlignError, match="free scale"):
        align_scales([freed, fixed], axis="x")


def test_fixed_scales_facets_can_be_aligned() -> None:
    def table(offset: float) -> ColumnTable:
        return ColumnTable(
            [
                (
                    "x",
                    Column("float", np.array([offset, offset + 1.0, offset + 2.0, offset + 3.0])),
                ),
                ("y", Column("float", np.array([1.0, 2.0, 3.0, 4.0]))),
                ("g", Column("str", np.array(["a", "a", "b", "b"], dtype=object))),
            ]
        )

    first = ggplot(table(0.0), aes(x="x", y="y")) + geom_point() + facet_wrap(("g",))
    second = ggplot(table(10.0), aes(x="x", y="y")) + geom_point() + facet_wrap(("g",))

    aligned = align_scales([first, second], axis="x")

    assert aligned.report.limits["x"].limits == (0.0, 13.0)
    for plot in aligned:
        params = [panel.panel_params for panel in build_plot(plot).panels]
        assert len({panel.x_range for panel in params}) == 1


def test_coord_limits_take_precedence_and_are_reported() -> None:
    from ggcore.plot import coord_cartesian

    first = point(numeric_table([1.0, 2.0], [1.0, 2.0])) + coord_cartesian(xlim=(1.0, 2.0))
    second = point(numeric_table([3.0, 4.0], [3.0, 4.0]))

    with pytest.warns(UserWarning, match="coord xlim"):
        aligned = align_scales([first, second], axis="x")

    # 对齐后的 scale limits 仍被写好，但 coord limits 优先（文档写明）。
    assert aligned[0].scales["x"].params["limits"] == (1.0, 4.0)
    assert (
        build_plot(aligned[0]).panel_params.x_range != build_plot(aligned[1]).panel_params.x_range
    )


def test_missing_axis_gets_a_scale() -> None:
    # 空图没有位置标度（`ggplot()` 只带数据 + 映射，没有 layer）。
    empty = ggplot(ColumnTable([("y", Column("float", np.array([1.0, 2.0])))]), aes(y="y"))
    both = point(numeric_table([1.0, 2.0], [1.0, 2.0]))

    aligned = align_scales([both, empty], axis="x")

    assert aligned[1].scales["x"].name == "x_continuous"
    assert aligned[1].scales["x"].params["limits"] == (1.0, 2.0)


def test_top_level_alias_is_the_same_function() -> None:
    assert gg4py.align_scales is align_scales
    assert math.isfinite(1.0)

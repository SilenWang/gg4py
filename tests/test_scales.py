"""M1-4 标度：色板 / expand / 断点 / 默认解析 / 离散水平 / transform。

口径见 `docs/notes/scales.md`。这里只跑内存里的小表，不依赖 R；与 ggplot2
4.0.3 的逐项对拍在 `tests/test_scales_r_parity.py`（夹具
`tests/fixtures/scales_r_reference.json`）。
"""

from __future__ import annotations

import itertools
import math

import numpy as np
import pytest

from ggcore.build import ScaleSet, build_plot
from ggcore.components import Scale
from ggcore.data import Column, ColumnTable
from ggcore.plot import (
    aes,
    geom_col,
    geom_point,
    ggplot,
    scale_colour_continuous,
    scale_colour_discrete,
    scale_shape_discrete,
    scale_size_continuous,
    scale_x_continuous,
    scale_x_discrete,
    scale_x_log10,
)
from ggcore.registry import SCALE_SPECS
from ggcore.scales import (
    DISCRETE_EXPANSION,
    Expansion,
    GradientScale,
    HueScale,
    PositionContinuousScale,
    PositionDiscreteScale,
    ScaleError,
    SizeScale,
    expand_range,
    extended_breaks,
    format_numbers,
    gradient_pal,
    hex_to_lab,
    hue_pal,
    lab_to_hex,
    scale_from_component,
)

# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def column(values, kind: str | None = None) -> Column:
    """测试用列：None → NA。"""
    items = list(values)
    missing = np.array([item is None for item in items], dtype=bool)
    if kind is None:
        kind = "str" if any(isinstance(item, str) for item in items) else "float"
    if kind == "str":
        data = np.array(["" if item is None else str(item) for item in items], dtype=object)
        return Column("str", data, na_mask=missing)
    data = np.array([np.nan if item is None else float(item) for item in items], dtype=np.float64)
    return Column("float", np.where(missing, 0.0, data), na_mask=missing)


def table(**columns) -> ColumnTable:
    return ColumnTable([(name, column(values)) for name, values in columns.items()])


def trained(scale, values) -> object:
    """按上游顺序：先 transform、再 train。"""
    col = column(values)
    scale.train(scale.transform(col))
    return scale


# ---------------------------------------------------------------------------
# 色板：hue 与 Lab gradient 的十六进制值必须与 R 逐字节相同
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (2, ["#F8766D", "#00BFC4"]),
        (3, ["#F8766D", "#00BA38", "#619CFF"]),
        (6, ["#F8766D", "#B79F00", "#00BA38", "#00BFC4", "#619CFF", "#F564E3"]),
        (7, ["#F8766D", "#C49A00", "#53B400", "#00C094", "#00B6EB", "#A58AFF", "#FB61D7"]),
    ],
)
def test_hue_palette_matches_r_byte_for_byte(n: int, expected: list[str]) -> None:
    assert hue_pal()(n) == expected


def test_hue_palette_honours_direction_and_start() -> None:
    assert hue_pal(direction=-1)(3) == list(reversed(hue_pal()(3)))
    # h.start = 90 的整体旋转：R 4.0.3 实测值，逐字节钉住（不是「只要长度对」）。
    assert hue_pal(h_start=90)(2) == ["#7CAE00", "#C77CFF"]
    assert hue_pal(h_start=90)(3) == ["#7CAE00", "#00B4F0", "#FF64B0"]
    # h = c(0, 360) 的整圈：n 个色相等距
    ring = hue_pal(h=(0.0, 360.0))(4)
    assert len(ring) == 4 and len(set(ring)) == 4


def test_gradient_matches_r_at_three_points() -> None:
    """默认 low/high 在 0 / 0.5 / 1 的取值（R: #132B43 / #336A98 / #56B1F7）。"""
    palette = gradient_pal()
    assert palette([0.0, 0.5, 1.0]) == ["#132B43", "#336A98", "#56B1F7"]
    assert palette([0.0, 0.25, 0.5, 0.75, 1.0]) == [
        "#132B43",
        "#22496C",
        "#336A98",
        "#448DC6",
        "#56B1F7",
    ]


def test_lab_round_trip_is_stable() -> None:
    for text in ("#132B43", "#F8766D", "#FFFFFF", "#000000", "#336A98"):
        assert lab_to_hex(hex_to_lab(text)) == text


# ---------------------------------------------------------------------------
# expand
# ---------------------------------------------------------------------------


def test_expand_range_continuous_default_is_five_percent() -> None:
    assert expand_range(1.0, 7.0) == (0.7, 7.3)
    assert expand_range(0.0, 100.0) == (-5.0, 105.0)


def test_expand_range_discrete_default_is_add_0_6() -> None:
    """离散 n 个水平 → 面板 0.4 .. n + 0.6（不是 0.5..n+0.5）。"""
    assert expand_range(1.0, 3.0, 0, 0.6) == (0.4, 3.6)
    assert DISCRETE_EXPANSION.apply(1.0, 3.0) == (0.4, 3.6)


def test_expand_range_zero_width_uses_unit_width() -> None:
    assert expand_range(5.0, 5.0) == pytest.approx((4.95, 5.05))
    assert expand_range(5.0, 5.0, 0, 0.6) == pytest.approx((4.4, 5.6))


def test_expansion_from_param_shapes() -> None:
    """参数按上游 `rep_len(expand, 4)` 解释（R: expand = 0.1 → 0.1 0.1 0.1 0.1）。"""
    assert Expansion.from_param(None, default=DISCRETE_EXPANSION) == DISCRETE_EXPANSION
    assert Expansion.from_param(0, default=DISCRETE_EXPANSION).as_tuple() == (0.0, 0.0, 0.0, 0.0)
    assert Expansion.from_param([0, 0], default=DISCRETE_EXPANSION).as_tuple() == (
        0.0,
        0.0,
        0.0,
        0.0,
    )
    assert Expansion.from_param(0.1, default=DISCRETE_EXPANSION).as_tuple() == (
        0.1,
        0.1,
        0.1,
        0.1,
    )
    assert Expansion.from_param([0.1, 0.2], default=DISCRETE_EXPANSION).as_tuple() == (
        0.1,
        0.2,
        0.1,
        0.2,
    )
    assert Expansion.from_param([0.1, 0.2, 0.3, 0.4], default=DISCRETE_EXPANSION).as_tuple() == (
        0.1,
        0.2,
        0.3,
        0.4,
    )
    assert Expansion.from_param({"mult": 0.1, "add": 1}, default=DISCRETE_EXPANSION).as_tuple() == (
        0.1,
        1.0,
        0.1,
        1.0,
    )


# ---------------------------------------------------------------------------
# labeling::extended
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dmin", "dmax", "n", "expected"),
    [
        (1.0, 7.0, 5, (1, 2, 3, 4, 5, 6, 7)),
        (0.7, 7.3, 5, (0, 2, 4, 6, 8)),
        (0.0, 100.0, 5, (0, 25, 50, 75, 100)),
        (-5.0, 105.0, 5, (0, 25, 50, 75, 100)),
        (-0.1, 2.1, 5, (0, 0.5, 1, 1.5, 2)),
        (-1.1, 1.1, 5, (-1, -0.5, 0, 0.5, 1)),
        (0.0, 1.0, 5, (0, 0.25, 0.5, 0.75, 1)),
        (1e5, 1e6, 5, (0, 250000, 500000, 750000, 1000000)),
        (0.001, 0.005, 5, (0.001, 0.002, 0.003, 0.004, 0.005)),
        (-3.0, 3.0, 5, (-3, -2, -1, 0, 1, 2, 3)),
        (2.5, 17.3, 5, (0, 4, 8, 12, 16)),
        (0.0, 0.001, 5, (0, 0.00025, 0.0005, 0.00075, 0.001)),
        (-1.0, 1.0, 5, (-1, -0.5, 0, 0.5, 1)),
        (0.0, 1.0, 3, (0, 0.5, 1)),
        (0.0, 100.0, 3, (0, 50, 100)),
        (5.0, 5.5, 5, (5, 5.1, 5.2, 5.3, 5.4, 5.5)),
        (100.0, 1000.0, 5, (0, 250, 500, 750, 1000)),
        (-0.5, 0.5, 5, (-0.5, -0.25, 0, 0.25, 0.5)),
        (0.225, 0.775, 5, (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)),
    ],
)
def test_extended_breaks_match_r(dmin, dmax, n, expected) -> None:
    """`labeling::extended()` 的 19 组范围（值来自 R 4.5.3 / labeling 0.4.3）。"""
    assert extended_breaks(dmin, dmax, n) == pytest.approx(expected, abs=1e-12)


# ---------------------------------------------------------------------------
# 标签格式化（R 的 format(trim = TRUE)）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([0, 0.25, 0.5, 0.75, 1], ["0.00", "0.25", "0.50", "0.75", "1.00"]),
        ([1, 1.5, 2, 2.5, 3], ["1.0", "1.5", "2.0", "2.5", "3.0"]),
        ([0, 50, 100], ["0", "50", "100"]),
        ([0.3, 0.4, 0.5], ["0.3", "0.4", "0.5"]),
        ([1e5, 2e5, 3e5], ["1e+05", "2e+05", "3e+05"]),
        ([1e-4, 2e-4], ["1e-04", "2e-04"]),
        ([0, 0.00025, 0.0005], ["0.00000", "0.00025", "0.00050"]),
        ([1234.5, 1234.6], ["1234.5", "1234.6"]),
        ([-1, -0.5, 0, 0.5, 1], ["-1.0", "-0.5", "0.0", "0.5", "1.0"]),
        ([None, 2.0, 4.0], [None, "2", "4"]),
    ],
)
def test_format_numbers_matches_r(values, expected) -> None:
    assert format_numbers(values) == expected


# ---------------------------------------------------------------------------
# 默认标度解析
# ---------------------------------------------------------------------------


def test_default_scale_resolution() -> None:
    from ggcore.scales import AlphaScale, ShapeScale

    numeric = column([1.0, 2.0])
    text = column(["a", "b"])
    boolean = Column("bool", np.array([True, False]))

    def resolved(aesthetic: str, col: Column) -> object:
        scales = ScaleSet()
        scales.train(col, aesthetic)
        return scales.scale(aesthetic)

    assert isinstance(resolved("x", numeric), PositionContinuousScale)
    assert isinstance(resolved("x", text), PositionDiscreteScale)
    assert isinstance(resolved("x", boolean), PositionDiscreteScale)
    assert isinstance(resolved("colour", numeric), GradientScale)
    assert isinstance(resolved("colour", text), HueScale)
    assert isinstance(resolved("fill", text), HueScale)
    assert isinstance(resolved("size", numeric), SizeScale)
    assert isinstance(resolved("alpha", numeric), AlphaScale)
    assert isinstance(resolved("shape", text), ShapeScale)
    # 不在标度范围内的美学（group / PANEL / weight）不建标度
    assert resolved("group", numeric) is None


def test_position_aliases_share_the_axis_scale() -> None:
    scales = ScaleSet()
    scales.train(column([1.0, 2.0, 3.0]), "x")
    assert scales.scale("xmin") is scales.scale("x")
    assert scales.scale("xmax") is scales.scale("x")
    assert scales.scale("ymin") is not scales.scale("x")
    # 数值 xmin 原样通过（柱子的锚点不被离散 x 标度吃掉）
    scales.train(column(["a", "b"]), "y")
    mapped = scales.map(Column("float", np.array([0.5, 1.5])), "ymin")
    assert mapped.values.tolist() == [0.5, 1.5]


def test_plot_scales_override_defaults() -> None:
    t = table(x=[1.0, 10.0, 100.0], y=[1.0, 2.0, 3.0])
    plot = ggplot(t, aes(x="x", y="y")) + geom_point() + scale_x_log10()
    build = build_plot(plot)
    scale = build.scales.scale("x")
    assert scale is not None and scale.transform_.name == "log10"
    assert build.scales.limits("x") == (0.0, 2.0)
    assert build.layers[0].data.column("x").values.tolist() == [0.0, 1.0, 2.0]


def test_explicit_discrete_scale_wins_over_column_type() -> None:
    t = table(x=[1.0, 2.0], y=[1.0, 2.0])
    plot = ggplot(t, aes(x="x", y="y")) + geom_point() + scale_x_discrete()
    build = build_plot(plot)
    assert isinstance(build.scales.scale("x"), PositionDiscreteScale)


# ---------------------------------------------------------------------------
# log10
# ---------------------------------------------------------------------------


def test_log10_maps_zero_and_negative_to_na_and_counts() -> None:
    scale = scale_from_component(Scale("x_log10", "x", {}))
    with_zeros = scale.transform(column([1.0, 10.0, 100.0, 0.0, -1.0]))
    scale.train(with_zeros)
    assert scale.non_finite_count == 2
    assert with_zeros.na_mask.tolist() == [False, False, False, True, True]
    assert scale.limits() == (0.0, 2.0)
    mapped = scale.map(scale.transform(column([1.0, 10.0, 100.0, 0.0, -1.0])))
    assert mapped.values.tolist() == [0.0, 1.0, 2.0, 0.0, 0.0]
    assert mapped.na_mask.tolist() == [False, False, False, True, True]


def test_log10_breaks_and_labels_are_in_data_space() -> None:
    scale = scale_from_component(Scale("x_log10", "x", {}))
    scale.train(scale.transform(column([1.0, 10.0, 100.0])))
    assert scale.breaks() == (None, 0.0, 1.0, 2.0, None)
    assert scale.labels() == (None, "1", "10", "100", None)
    assert scale.expanded_limits() == pytest.approx((-0.1, 2.1), abs=1e-12)


def test_log10_explicit_limits_are_transformed() -> None:
    """显式 limits 是数据空间的值；R 的 `get_limits()` 存变换后的 (0, 2)。

    回归 SIL-681：之前把 `limits = c(1, 100)` 原样当成变换后的值，于是
    `expanded = (-3.95, 104.95)`、`breaks = (NA, 18, 40, 62, 84)`、
    `labels = (NA, "1e+18", …)`，200 也被当成界内值。
    """
    scale = scale_from_component(Scale("x_log10", "x", {"limits": [1, 100]}))
    scale.train(scale.transform(column([1.0, 10.0, 100.0, 200.0])))
    assert scale.limits() == (0.0, 2.0)
    assert scale.expanded_limits() == pytest.approx((-0.1, 2.1), abs=1e-12)
    assert scale.breaks() == (None, 0.0, 1.0, 2.0, None)
    assert scale.labels() == (None, "1", "10", "100", None)
    mapped = scale.map(scale.transform(column([1.0, 10.0, 100.0, 200.0])))
    assert mapped.values.tolist() == [0.0, 1.0, 2.0, 0.0]
    assert mapped.na_mask.tolist() == [False, False, False, True]


def test_log10_single_sided_limits_keep_the_trained_side() -> None:
    """单侧 None：显式一侧先变换，另一侧取训练范围（已是变换后的值，不再变换）。"""
    scale = scale_from_component(Scale("x_log10", "x", {"limits": [1, None]}))
    scale.train(scale.transform(column([1.0, 10.0, 100.0, 200.0])))
    assert scale.limits() == pytest.approx((0.0, math.log10(200.0)), abs=1e-12)

    upper = scale_from_component(Scale("x_log10", "x", {"limits": [None, 100]}))
    upper.train(upper.transform(column([1.0, 10.0, 100.0, 200.0])))
    assert upper.limits() == pytest.approx((0.0, 2.0), abs=1e-12)


def test_reverse_check_log10_versus_plain() -> None:
    """反向对照（issue 验收）：1/10/100 → 0/1/2；不写 log10 时值不变。"""
    t = table(x=[1.0, 10.0, 100.0], y=[1.0, 2.0, 3.0])
    plain = build_plot(ggplot(t, aes(x="x", y="y")) + geom_point())
    logged = build_plot(ggplot(t, aes(x="x", y="y")) + geom_point() + scale_x_log10())
    assert plain.layers[0].data.column("x").values.tolist() == [1.0, 10.0, 100.0]
    assert logged.layers[0].data.column("x").values.tolist() == [0.0, 1.0, 2.0]


def test_unsupported_transforms_raise_with_task_name() -> None:
    for trans in ("reverse", "sqrt", "log2", "exp", "pseudo_log"):
        with pytest.raises(ScaleError, match="尚未实现"):
            scale_from_component(Scale("x_continuous", "x", {"trans": trans}))
    with pytest.raises(ScaleError, match="reverse"):
        scale_from_component(Scale("x_continuous", "x", {"trans": "reverse"}))
    with pytest.raises(ScaleError, match="未知的 trans"):
        scale_from_component(Scale("x_continuous", "x", {"trans": "nope"}))


def test_oob_squish_is_rejected() -> None:
    with pytest.raises(ScaleError, match="squish"):
        scale_from_component(Scale("x_continuous", "x", {"oob": "squish"}))


# ---------------------------------------------------------------------------
# 连续标度：limits / expand / breaks / labels
# ---------------------------------------------------------------------------


def test_continuous_limits_censor_and_expand() -> None:
    scale = scale_from_component(Scale("x_continuous", "x", {"limits": [2, 6]}))
    scale.train(scale.transform(column([1.0, 3.0, 7.0])))
    assert scale.limits() == (2.0, 6.0)
    assert scale.expanded_limits() == pytest.approx((1.8, 6.2))
    assert scale.breaks() == (2.0, 3.0, 4.0, 5.0, 6.0)
    mapped = scale.map(scale.transform(column([1.0, 3.0, 7.0])))
    assert mapped.na_mask.tolist() == [True, False, True]


def test_continuous_expand_zero_disables_padding() -> None:
    scale = scale_from_component(Scale("x_continuous", "x", {"expand": [0, 0]}))
    scale.train(scale.transform(column([1.0, 7.0])))
    assert scale.expanded_limits() == (1.0, 7.0)
    assert scale.breaks() == (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0)


def test_continuous_manual_breaks_and_labels() -> None:
    params = {"breaks": [2, 4, 6], "labels": ["low", "mid", "high"]}
    scale = scale_from_component(Scale("x_continuous", "x", params))
    scale.train(scale.transform(column([1.0, 7.0])))
    assert scale.breaks() == (2.0, 4.0, 6.0)
    assert scale.labels() == ("low", "mid", "high")


def test_labels_accept_mapping_and_format_string() -> None:
    params = {"breaks": [2, 4], "labels": {2: "two"}}
    mapping = scale_from_component(Scale("x_continuous", "x", params))
    mapping.train(mapping.transform(column([1.0, 7.0])))
    assert mapping.labels() == ("two", None)

    fmt = scale_from_component(Scale("x_continuous", "x", {"breaks": [2, 4], "labels": "%.1f"}))
    fmt.train(fmt.transform(column([1.0, 7.0])))
    assert fmt.labels() == ("2.0", "4.0")


def test_n_breaks_controls_default_break_count() -> None:
    scale = scale_from_component(Scale("x_continuous", "x", {"n_breaks": 3}))
    scale.train(scale.transform(column([0.0, 100.0])))
    assert scale.breaks() == (0.0, 50.0, 100.0)


def test_non_position_scales_have_no_panel_range() -> None:
    gradient = scale_from_component(Scale("colour_continuous", "colour", {}))
    gradient.train(gradient.transform(column([0.0, 1.0])))
    assert gradient.expanded_limits() is None
    assert gradient.breaks() == (0.0, 0.25, 0.5, 0.75, 1.0)


# ---------------------------------------------------------------------------
# 离散标度
# ---------------------------------------------------------------------------


def test_discrete_levels_sorted_with_na_last() -> None:
    scale = scale_from_component(Scale("x_discrete", "x", {}))
    scale.train(column(["b", "a", "c", "a"]))
    assert scale.limits() == ("a", "b", "c")
    assert scale.expanded_limits() == pytest.approx((0.4, 3.6))
    mapped = scale.map(column(["a", "b", "c", "z", None]))
    assert mapped.values.tolist() == [1.0, 2.0, 3.0, 0.0, 0.0]
    assert mapped.na_mask.tolist() == [False, False, False, True, True]


def test_discrete_na_is_a_level_when_trained_with_missing() -> None:
    scale = scale_from_component(Scale("x_discrete", "x", {}))
    scale.train(column(["a", None, "b"]))
    assert scale.limits() == ("a", "b", None)
    assert scale.expanded_limits() == pytest.approx((0.4, 3.6))
    mapped = scale.map(column(["a", None, "b"]))
    assert mapped.values.tolist() == [1.0, 3.0, 2.0]


def test_discrete_explicit_limits_and_unknown_values() -> None:
    scale = scale_from_component(Scale("x_discrete", "x", {"limits": ["b", "a", "z"]}))
    scale.train(column(["a", "b", "c"]))
    assert scale.limits() == ("b", "a", "z")
    assert scale.map(column(["a", "b", "c"])).values.tolist() == [2.0, 1.0, 0.0]


def test_discrete_drop_false_keeps_unused_levels() -> None:
    levels = ("b", "a", "c")
    categorical = Column("categorical", np.array([1], dtype=np.int32), levels=levels)
    scale = scale_from_component(Scale("x_discrete", "x", {"drop": False}))
    scale.train(categorical)
    assert scale.limits() == ("b", "a", "c")
    assert scale.map(column(["a", "b", "c"])).values.tolist() == [2.0, 1.0, 3.0]

    dropped = scale_from_component(Scale("x_discrete", "x", {}))
    dropped.train(categorical)
    assert dropped.limits() == ("a",)


def test_hue_scale_maps_levels_and_na_value() -> None:
    scale = scale_from_component(Scale("colour_discrete", "colour", {}))
    scale.train(column(["a", "b", "c", "a"]))
    mapped = scale.map(column(["a", "b", "c", None]))
    assert mapped.values.tolist() == ["#F8766D", "#00BA38", "#619CFF", "grey50"]
    assert not mapped.na_mask.any()

    custom = scale_from_component(Scale("colour_discrete", "colour", {"na.value": "red"}))
    custom.train(column(["a", "b"]))
    assert custom.map(column(["a", None])).values.tolist() == ["#F8766D", "red"]


def test_manual_values_palette_requires_enough_colours() -> None:
    scale = scale_from_component(
        Scale("colour_discrete", "colour", {"values": ["red", "#00FF00", "blue"]})
    )
    scale.train(column(["a", "b", "c"]))
    assert scale.map(column(["a", "b", "c"])).values.tolist() == ["red", "#00FF00", "blue"]

    short = scale_from_component(Scale("colour_discrete", "colour", {"values": ["red"]}))
    short.train(column(["a", "b"]))
    with pytest.raises(ScaleError, match="不允许循环补齐"):
        short.map(column(["a", "b"]))


def test_manual_values_mapping_is_looked_up_by_level_name() -> None:
    """`values` 传 dict 时按**水平名**取色（R 的 named manual palette）。

    之前把 dict 当颜色列表迭代 key，`{"a": "red"}` 会静默输出 `"a"`。
    """
    scale = scale_from_component(
        Scale("colour_discrete", "colour", {"values": {"a": "red", "b": "blue"}})
    )
    scale.train(column(["a", "b", "c"]))
    assert scale.map(column(["a", "b", "c"])).values.tolist() == ["red", "blue", "grey50"]

    custom = scale_from_component(
        Scale(
            "colour_discrete",
            "colour",
            {"values": {"b": "blue"}, "na.value": "black"},
        )
    )
    custom.train(column(["a", "b"]))
    assert custom.map(column(["a", "b"])).values.tolist() == ["black", "blue"]

    # 名字与水平完全对不上：整列 na.value，并像上游一样发 warning（不静默）。
    other = scale_from_component(Scale("colour_discrete", "colour", {"values": {"x": "red"}}))
    other.train(column(["a", "b"]))
    with pytest.warns(UserWarning, match="没有交集"):
        assert other.map(column(["a", "b"])).values.tolist() == ["grey50", "grey50"]


def test_palette_parameter_accepts_callable_and_sequence() -> None:
    calls: list[int] = []

    def fixed(n: int) -> list[str]:
        calls.append(n)
        return ["#111111", "#222222"][:n]

    callable_scale = scale_from_component(Scale("colour_discrete", "colour", {"palette": fixed}))
    callable_scale.train(column(["a", "b"]))
    assert callable_scale.map(column(["a", "b"])).values.tolist() == ["#111111", "#222222"]
    assert calls == [2]

    sequence_scale = scale_from_component(
        Scale("colour_discrete", "colour", {"palette": ["#333333", "#444444"]})
    )
    sequence_scale.train(column(["a", "b"]))
    assert sequence_scale.map(column(["b", "a"])).values.tolist() == ["#444444", "#333333"]


def test_every_registered_scale_name_has_an_implementation() -> None:
    """`registry.SCALE_SPECS` 是唯一的名字表：13 个注册名都能建成标度对象。

    回归 SIL-681：`scales.SCALE_NAMES` 曾是第二份名字表且无人使用，已删除；
    这条断言守住「注册表 ↔ 实现」不漂移。
    """
    for name, aesthetic, _defaults in SCALE_SPECS:
        scale = scale_from_component(Scale(name, aesthetic, {}))
        assert scale.aesthetic == aesthetic
        assert scale.discrete is (name.endswith("_discrete"))


def test_shape_and_size_palettes() -> None:
    shape = scale_from_component(Scale("shape_discrete", "shape", {}))
    shape.train(column(["a", "b", "c"]))
    assert shape.map(column(["a", "b", "c"])).values.tolist() == [16.0, 17.0, 15.0]

    size = scale_from_component(Scale("size_continuous", "size", {}))
    size.train(size.transform(column([1.0, 4.0])))
    assert size.map(size.transform(column([1.0, 2.0, 4.0]))).values.tolist() == pytest.approx(
        [1.0, 3.8867513459481287, 6.0]
    )


# ---------------------------------------------------------------------------
# ScaleSet 与流水线
# ---------------------------------------------------------------------------


def test_scale_set_keeps_the_trained_levels_view() -> None:
    """`ScaleSet.trained` 仍是「美学 → 离散水平」，M1-3 的测试与夹具靠它。"""
    t = table(cls=["compact", "compact", "midsize", "suv"], value=[1.0, 2.0, 3.0, 4.0])
    plot = ggplot(t, aes(x="cls", y="value")) + geom_col()
    build = build_plot(plot)
    assert build.scales.trained["x"] == ("compact", "midsize", "suv")
    assert build.scales.levels("x") == ("compact", "midsize", "suv")
    assert build.scales.limits("x") == ("compact", "midsize", "suv")


def test_build_maps_every_supported_aesthetic() -> None:
    t = ColumnTable(
        [
            ("x", column([1.0, 2.0])),
            ("y", column([1.0, 2.0])),
            ("colour_value", column(["a", "b"])),
            ("fill_value", column(["p", "q"])),
            ("size_value", column([1.0, 2.0])),
            ("shape_value", column(["r", "s"])),
            ("alpha_value", column([1.0, 2.0])),
        ]
    )
    plot = (
        ggplot(
            t,
            aes(
                x="x",
                y="y",
                colour="colour_value",
                fill="fill_value",
                size="size_value",
                shape="shape_value",
                alpha="alpha_value",
            ),
        )
        + geom_point()
    )
    data = build_plot(plot).layers[0].data
    assert data.column("colour").values.tolist() == ["#F8766D", "#00BFC4"]
    assert data.column("fill").values.tolist() == ["#F8766D", "#00BFC4"]
    assert data.column("size").values.tolist() == pytest.approx([1.0, 6.0])
    assert data.column("shape").values.tolist() == pytest.approx([16.0, 17.0])
    assert data.column("alpha").values.tolist() == pytest.approx([0.1, 1.0])


def test_build_is_deterministic_with_scales() -> None:
    t = table(x=[1.0, 10.0, 100.0], y=[1.0, 2.0, 3.0], g=["a", "b", "a"])
    plot = ggplot(t, aes(x="x", y="y", colour="g")) + geom_point() + scale_x_log10()
    first = build_plot(plot)
    second = build_plot(plot)
    assert first.layers[0].data == second.layers[0].data
    assert first.scales.breaks("x") == second.scales.breaks("x")
    assert first.scales.labels("colour") == second.scales.labels("colour")


def test_registry_names_cover_every_scale_implementation() -> None:
    from ggcore.registry import SCALE_SPECS

    for name, aesthetic, defaults in SCALE_SPECS:
        scale = scale_from_component(Scale(name, aesthetic, defaults))
        assert scale.aesthetic == aesthetic, name


def test_scale_colour_helpers_are_registered_aliases() -> None:
    """`scale_colour_discrete` 是 hue、`scale_colour_continuous` 是 gradient。"""
    hue = scale_colour_discrete()
    gradient = scale_colour_continuous()
    assert hue.name == "colour_discrete" and gradient.name == "colour_continuous"
    size = scale_size_continuous()
    shape = scale_shape_discrete()
    assert size.name == "size_continuous" and shape.name == "shape_discrete"
    continuous = scale_x_continuous()
    assert continuous.name == "x_continuous"


def test_minor_breaks_are_the_midpoints_of_major_breaks() -> None:
    """`panel.grid.minor` 的次断点：连续标度 = 主断点中点（变换后的空间）。"""
    scale = scale_from_component(Scale("x_continuous", "x", {"limits": [0, 6], "expand": [0, 0]}))
    scale.train(column([0.0, 6.0]))
    assert scale.breaks() == (0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0)
    assert scale.minor_breaks() == (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)

    log = scale_from_component(Scale("x_log10", "x", {"limits": [1, 100]}))
    log.train(column([1.0, 100.0]))
    # 断点在 log10 空间；中点也在 log10 空间（R 的 get_breaks_minor 同口径）。
    major = [value for value in log.breaks() if value is not None]
    minor = log.minor_breaks()
    expected = [(first + second) / 2.0 for first, second in itertools.pairwise(major)]
    assert minor == pytest.approx(expected)


def test_minor_breaks_discrete_and_single_break() -> None:
    discrete = scale_from_component(Scale("x_discrete", "x", {}))
    discrete.train(column(["a", "b", "c"]))
    assert discrete.minor_breaks() == ()

    scale = scale_from_component(Scale("x_continuous", "x", {"breaks": [2.0], "expand": [0, 0]}))
    scale.train(column([0.0, 4.0]))
    assert scale.minor_breaks() == ()


def test_minor_breaks_use_the_uncensored_major_breaks() -> None:
    """SIL-725：次断点取**未过滤**主断点序列的中点，再按面板范围过滤。

    修前先 `breaks()` 再求中点，越界端点被置 `None`，最外两个半区间整个丢掉：
    x [2, 30] 只剩 15/25，y [2.34, 5.50] 只剩 3.5/4.5。R 的
    `get_breaks_minor()` 拿到的是未 censor 的主断点序列（"major breaks are not
    censored"），所以次断点是 5/15/25（35 在面板范围外不画）与
    2.5/3.5/4.5/5.5。
    """
    x = PositionContinuousScale("x")
    x.train(column([2.0, 30.0]))
    assert x.breaks() == (None, 10.0, 20.0, 30.0)
    assert x.minor_breaks() == (5.0, 15.0, 25.0)

    y = PositionContinuousScale("y")
    y.train(column([2.336968, 5.498689]))
    assert y.breaks() == (None, 3.0, 4.0, 5.0, None)
    assert y.minor_breaks() == (2.5, 3.5, 4.5, 5.5)


def test_minor_breaks_drop_midpoints_outside_the_panel_range() -> None:
    """落在面板范围外的半区间不画：x [2, 30] 的第 4 段中点是 35 > 31.4。"""
    scale = PositionContinuousScale("x")
    scale.train(column([2.0, 30.0]))
    low, high = scale.expanded_limits()
    assert 35.0 not in scale.breaks()  # 越界端点本身就是 None
    assert 35.0 not in scale.minor_breaks()
    assert all(low <= value <= high for value in scale.minor_breaks())


def test_minor_breaks_extend_towards_the_panel_edge_like_r() -> None:
    """R 的 `regular_minor_breaks()` 先按 limits 两端各补一个 bd 再取中点。

    limits [0.6, 9] 在主断点 2 之前 / 8 之后都还剩空白，R 会补 0 与 10 并画出
    1 / 9 两处的次网格；只对主断点配对（3/5/7）会少这两条。
    """
    scale = scale_from_component(
        Scale(
            "x_continuous",
            "x",
            {"breaks": [2.0, 4.0, 6.0, 8.0], "limits": [0.6, 9.0], "expand": [0, 0]},
        )
    )
    scale.train(column([1.0, 8.0]))
    assert scale.minor_breaks() == (1.0, 3.0, 5.0, 7.0, 9.0)


def test_minor_breaks_log10_midpoints_are_in_log_space() -> None:
    """`scale_x_log10()` 的中点在对数空间：0.5 / 1.5（数据空间会是 1 / 10）。"""
    scale = scale_from_component(Scale("x_log10", "x", {"limits": [1, 100]}))
    scale.train(column([1.0, 100.0]))
    assert scale.breaks() == (None, 0.0, 1.0, 2.0, None)
    minor = scale.minor_breaks()
    assert minor == (0.5, 1.5)
    # 数据空间的中点（1 / 10）会是另一组值：这条断言在实现退回数据空间时变红。
    assert 10.0**0.5 not in minor and 1.0 not in minor


def test_sec_axis_is_rejected_on_both_entry_points() -> None:
    """`sec.axis` 不再静默：`+` 入口与方法链入口都点名报错（修前两条都静默）。"""
    table = ColumnTable(
        [("x", Column("float", np.array([1.0, 2.0]))), ("y", Column("float", np.array([1.0, 2.0])))]
    )
    plot = ggplot(table, aes(x="x", y="y")) + geom_point()
    with pytest.raises(ScaleError, match=r"sec[._]axis.*未实现"):
        plot + scale_x_continuous(**{"sec.axis": "x"})
    with pytest.raises(ScaleError, match=r"sec[._]axis.*未实现"):
        plot.scale_x_continuous(**{"sec.axis": "x"})
    with pytest.raises(ScaleError, match=r"sec[._]axis.*未实现"):
        plot.scale_y_continuous(**{"sec_axis": 1})
    # 直接构造组件也要在同一条解析路径上报错（plotspec / 反序列化入口）。
    with pytest.raises(ScaleError, match=r"sec[._]axis"):
        scale_from_component(Scale("x_continuous", "x", {"sec.axis": "x"}))


def test_other_unimplemented_scale_messages_are_intact() -> None:
    """`guide_bins` 与 `geom_line(arrow=)` 的既有报错文案没被这次改动动到。"""
    from ggcore import registry
    from ggcore.geom.line import LineRenderer
    from ggcore.theme import theme_void

    table = ColumnTable(
        [("x", Column("float", np.array([1.0, 2.0]))), ("y", Column("float", np.array([1.0, 2.0])))]
    )
    plot = (
        ggplot(table, aes(x="x", y="y")) + registry.geom_line(arrow={"length": 0.1}) + theme_void()
    )
    from ggcore.geom.scene import scene_from_plot

    with pytest.raises(ValueError, match=r"arrow.*无法表达"):
        scene_from_plot(plot, width_in=4, height_in=3)
    assert LineRenderer.name == "line"

    from ggcore.guide import build_guides

    base = ggplot(table, aes(x="x", y="y", colour="x")) + geom_point()
    with pytest.raises(Exception, match="guide_bins"):
        build_guides(build_plot(base + registry.scale_colour_continuous(guide="bins")))

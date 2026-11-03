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

from ggcore import registry
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
    LinetypeScale,
    LinewidthScale,
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


def test_sqrt_and_reverse_transforms_are_implemented() -> None:
    sqrt = scale_from_component(Scale("x_sqrt", "x", {}))
    trained = sqrt.transform(column([0.0, 4.0, 9.0, -1.0]))
    sqrt.train(trained)
    assert sqrt.non_finite_count == 1
    assert sqrt.limits() == (0.0, 3.0)
    assert sqrt.map(sqrt.transform(column([0.0, 4.0, 9.0]))).values.tolist() == [0.0, 2.0, 3.0]

    reverse = scale_from_component(Scale("x_reverse", "x", {}))
    values = reverse.transform(column([1.0, 3.0, 7.0]))
    reverse.train(values)
    assert reverse.limits() == (-7.0, -1.0)
    assert reverse.map(values).values.tolist() == [-1.0, -3.0, -7.0]
    # 断点在变换后的空间里倒序（R 的 get_breaks 口径）。
    assert reverse.breaks() == (None, -2.0, -4.0, -6.0, None)
    assert reverse.labels() == (None, "2", "4", "6", None)


def test_unsupported_transforms_still_raise() -> None:
    # log2 / exp 已在 SIL-790 实现（见下面两节），这里只剩真正没做的名字。
    for trans in ("log1p", "pseudo_log", "logit"):
        with pytest.raises(ScaleError, match="尚未实现"):
            scale_from_component(Scale("x_continuous", "x", {"trans": trans}))
    with pytest.raises(ScaleError, match="未知的 trans"):
        scale_from_component(Scale("x_continuous", "x", {"trans": "nope"}))


def test_oob_censor_squish_keep_and_squish_infinite() -> None:
    """`oob` 四态与 R 一致（SIL-731）：censor / squish / squish_infinite / keep。"""

    def mapped(oob):
        scale = scale_from_component(Scale("x_continuous", "x", {"limits": [2, 6], "oob": oob}))
        scale.train(scale.transform(column([1.0, 3.0, 7.0])))
        return scale.map(scale.transform(column([1.0, 3.0, 7.0])))

    censored = mapped("censor")
    assert censored.na_mask.tolist() == [True, False, True]

    squished = mapped("squish")
    assert squished.values.tolist() == [2.0, 3.0, 6.0]
    assert not squished.na_mask.any()

    kept = mapped("keep")
    assert kept.values.tolist() == [1.0, 3.0, 7.0]

    infinite = scale_from_component(
        Scale("x_continuous", "x", {"limits": [2, 6], "oob": "squish_infinite"})
    )
    infinite.train(infinite.transform(column([1.0, 3.0, 7.0])))
    result = infinite.map(column([1.0, 3.0, math.inf, -math.inf]))
    assert result.values.tolist()[:2] == [1.0, 3.0]
    assert result.values.tolist()[2:] == [6.0, 2.0]
    with pytest.raises(ScaleError, match="oob"):
        scale_from_component(Scale("x_continuous", "x", {"oob": "nope"}))


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


#: 必填颜色的族：`gradientn` / `stepsn` 在上游没有默认 colours。
_REQUIRED_COLOURS = ("gradientn", "stepsn")


def _required_params(name: str) -> dict:
    if name.endswith(_REQUIRED_COLOURS):
        return {"colours": ("#0000FF", "#FFFFFF", "#FF0000")}
    return {}


#: R 里**构造即 abort** 的标度（连续变量不能映射到 shape / linetype）。它们仍然
#: 占着 NAMESPACE 的名字，所以留在注册表里，只是解析时抛 `ScaleError`。
_ABORT_SCALES = frozenset({"shape_continuous", "linetype_continuous"})

#: 离散标度的名字（`DiscreteScale` 族）。这份表是**规格**，不是从实现反推的：
#: 加新名字时要么进这里、要么进连续一侧，逼着作者想清楚是哪一边。
_DISCRETE_SCALES = frozenset(
    {
        "x_discrete",
        "y_discrete",
        "colour_discrete",
        "fill_discrete",
        "colour_hue",
        "color_hue",
        "fill_hue",
        "colour_brewer",
        "color_brewer",
        "fill_brewer",
        "colour_grey",
        "color_grey",
        "fill_grey",
        "colour_ordinal",
        "color_ordinal",
        "fill_ordinal",
        "colour_manual",
        "color_manual",
        "fill_manual",
        "colour_identity",
        "color_identity",
        "fill_identity",
        "colour_viridis_d",
        "color_viridis_d",
        "fill_viridis_d",
        "shape",
        "shape_discrete",
        "shape_ordinal",
        "shape_manual",
        "linetype",
        "linetype_discrete",
        "linetype_manual",
        "linetype_identity",
        "size_discrete",
        "size_ordinal",
        "size_manual",
        "alpha_discrete",
        "alpha_ordinal",
        "alpha_manual",
        "linewidth_discrete",
        "linewidth_ordinal",
        "linewidth_manual",
        "discrete_manual",
        "discrete_identity",
        # SIL-745：`scale_color_discrete` 是 `scale_colour_discrete` 的漏登记别名。
        "color_discrete",
    }
)


def test_every_registered_scale_name_has_an_implementation() -> None:
    """`registry.SCALE_SPECS` 是唯一的名字表：每个注册名都能建成标度对象。

    回归 SIL-681：`scales.SCALE_NAMES` 曾是第二份名字表且无人使用，已删除；
    这条断言守住「注册表 ↔ 实现」不漂移。M2-4 A + B 合起来 129 个注册名，
    离散 / 连续的分类单列成 `_DISCRETE_SCALES`；`gradientn` / `stepsn` 在 R 里
    也必须给 `colours`，所以这里补上这一条必填参数。
    """
    names = [name for name, _aesthetic, _defaults in SCALE_SPECS]
    assert len(names) == len(set(names)), "SCALE_SPECS 里有重名"
    assert set(names) - _DISCRETE_SCALES - _ABORT_SCALES  # 连续一侧非空
    for name, aesthetic, _defaults in SCALE_SPECS:
        if name in _ABORT_SCALES:
            with pytest.raises(ScaleError):
                scale_from_component(Scale(name, aesthetic, {}))
            continue
        scale = scale_from_component(Scale(name, aesthetic, _required_params(name)))
        assert scale.aesthetic == aesthetic
        assert scale.discrete is (name in _DISCRETE_SCALES), name


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
        if name in _ABORT_SCALES:
            continue
        params = {**defaults, **_required_params(name)}
        scale = scale_from_component(Scale(name, aesthetic, params))
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


def test_sec_axis_is_accepted_and_validated() -> None:
    """M2-1 起 `sec.axis` 是正式入口：两条写法都收，非 `SecondaryAxis` 报错。"""
    from ggcore.axis import SecondaryAxis, dup_axis, sec_axis

    table = ColumnTable(
        [("x", Column("float", np.array([1.0, 2.0]))), ("y", Column("float", np.array([1.0, 2.0])))]
    )
    plot = ggplot(table, aes(x="x", y="y")) + geom_point()
    plus = plot + scale_x_continuous(**{"sec.axis": sec_axis(lambda v: v * 2)})
    chain = plot.scale_x_continuous(**{"sec.axis": sec_axis(lambda v: v * 2)})
    assert isinstance(plus.scales["x"].params["sec.axis"], SecondaryAxis)
    assert isinstance(chain.scales["x"].params["sec.axis"], SecondaryAxis)
    dup = plot.scale_y_continuous(**{"sec_axis": dup_axis()})
    assert dup.scales["y"].params["sec_axis"].is_identity
    # 不是 sec_axis() / dup_axis() 的结果 → 在同一条解析路径上报错。
    with pytest.raises(ScaleError, match=r"sec[._]axis"):
        plot + scale_x_continuous(**{"sec.axis": "x"})
    with pytest.raises(ScaleError, match=r"sec[._]axis"):
        scale_from_component(Scale("x_continuous", "x", {"sec.axis": "x"}))


def test_other_unimplemented_scale_messages_are_intact() -> None:
    """`guide_bins` 的连续 / 离散错配与 `geom_line(arrow=)` 的报错文案。"""
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

    # M2-S2：分箱 guide 已实现，但仍然只服务连续色标——离散标度要点名报错。
    discrete = ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0]))),
            ("y", Column("float", np.array([1.0, 2.0]))),
            (
                "g",
                Column("categorical", np.array([0, 1], dtype=np.int32), levels=("a", "b")),
            ),
        ]
    )
    base = ggplot(discrete, aes(x="x", y="y", colour="g")) + geom_point()
    with pytest.raises(Exception, match="guide_bins"):
        build_guides(build_plot(base + registry.scale_colour_discrete(guide="bins")))


# ---------------------------------------------------------------------------
# M2-4 B：离散 / 调色板 / manual / identity / 分箱
# ---------------------------------------------------------------------------


def _train(scale, values):
    scale.train(scale.transform(column(values)))
    return scale


def test_brewer_palette_reaches_the_plot_data() -> None:
    """`+ scale_colour_brewer(palette="Set1")` 走到 build 的 colour 列。"""
    from ggcore import registry

    table = ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0, 3.0]))),
            ("y", Column("float", np.array([1.0, 2.0, 3.0]))),
            ("g", Column("str", np.array(["a", "b", "c"], dtype=object))),
        ]
    )
    plot = ggplot(table, aes(x="x", y="y", colour="g")) + geom_point()
    plot = plot + registry.scale_colour_brewer(palette="Set1")
    data = build_plot(plot).layers[0].data
    assert data.column("colour").values.tolist() == ["#E41A1C", "#377EB8", "#4DAF4A"]


def test_viridis_discrete_scale_colours_are_eight_digit_hex() -> None:
    """viridis 的离散色板带 alpha 字节（上游 `rgb(..., alpha = 1)` → `#RRGGBBFF`）。"""
    from ggcore import registry

    scale = _train(
        scale_from_component(Scale("colour_viridis_d", "colour", {"option": "D"})),
        ["a", "b", "c"],
    )
    assert scale.map(column(["a", "b", "c"])).values.tolist() == [
        "#440154FF",
        "#21908CFF",
        "#FDE725FF",
    ]
    assert registry.scale_colour_viridis_d().name == "colour_viridis_d"
    assert registry.scale_color_viridis_d().aesthetic == "colour"


def test_brewer_and_viridis_na_value_is_na() -> None:
    """`na.value` 缺省按各色板函数自己的签名：brewer / viridis 是 NA，hue 是 grey50。"""
    brewer = _train(scale_from_component(Scale("colour_brewer", "colour", {})), ["a", "b"])
    mapped = brewer.map(column(["a", None]))
    assert mapped.na_mask.tolist() == [False, True]

    hue = _train(scale_from_component(Scale("colour_hue", "colour", {})), ["a", "b"])
    assert hue.map(column(["a", None])).values.tolist() == ["#F8766D", "grey50"]


def test_ordinal_scales_warn_and_map_to_their_fallback() -> None:
    """size / alpha / linewidth 的 `_discrete` 是 `_ordinal` 的别名（带警告）。"""
    import warnings as warnings_module

    expected = {
        "size_discrete": [2.0, 4.472135954999580, 6.0],
        "alpha_discrete": [0.1, 0.55, 1.0],
        "linewidth_discrete": [2.0, 4.0, 6.0],
    }
    for name, values in expected.items():
        with warnings_module.catch_warnings(record=True) as caught:
            warnings_module.simplefilter("always")
            aesthetic = name.split("_")[0]
            scale = _train(scale_from_component(Scale(name, aesthetic, {})), ["a", "b", "c"])
        assert any("not advised" in str(item.message) for item in caught), name
        assert scale.map(column(["a", "b", "c"])).values.tolist() == pytest.approx(values)


def test_size_area_and_radius_and_linewidth_ranges() -> None:
    area = _train(scale_from_component(Scale("size_area", "size", {})), [0.0, 4.0])
    assert area.map(column([0.0, 1.0, 4.0])).values.tolist() == pytest.approx([0.0, 3.0, 6.0])

    radius = _train(scale_from_component(Scale("radius", "size", {})), [0.0, 1.0])
    assert radius.map(column([0.0, 0.5, 1.0])).values.tolist() == pytest.approx([1.0, 3.5, 6.0])

    linewidth = _train(scale_from_component(Scale("linewidth", "linewidth", {})), [1.0, 4.0])
    assert linewidth.map(column([1.0, 2.5, 4.0])).values.tolist() == pytest.approx([1.0, 3.5, 6.0])


def test_identity_scales_pass_values_through() -> None:
    colour_identity = scale_from_component(Scale("colour_identity", "colour", {}))
    mapped = colour_identity.map(column(["#FF0000", "#00FF00"]))
    assert mapped.values.tolist() == ["#FF0000", "#00FF00"]
    # 上游的 identity 标度不训练范围：limits 恒为 (0, 1)、断点为空。
    assert colour_identity.limits() == (0.0, 1.0)
    assert colour_identity.breaks() == ()

    size_identity = _train(scale_from_component(Scale("size_identity", "size", {})), [1.0, 3.0])
    assert size_identity.map(column([1.0, 3.0])).values.tolist() == [1.0, 3.0]


def test_binned_scales_cut_then_take_palette_per_bin() -> None:
    """分箱：断点分箱 → 箱中点 → 每箱一个值（`cut(right = TRUE)` 的边界口径）。"""
    binned = _train(scale_from_component(Scale("shape_binned", "shape", {})), [0.0, 1.0])
    assert binned.breaks() == (0.25, 0.5, 0.75)
    assert binned.map(column([0.0, 0.3, 0.8, 1.0])).values.tolist() == [16.0, 17.0, 3.0, 3.0]

    sized = _train(scale_from_component(Scale("size_binned_area", "size", {})), [0.0, 1.0])
    assert sized.map(column([0.0, 0.5, 1.0])).values.tolist() == pytest.approx(
        [2.121320343559643, 3.674234614174767, 5.612486080160912]
    )

    linetypes = _train(scale_from_component(Scale("linetype_binned", "linetype", {})), [0.0, 1.0])
    assert linetypes.map(column([0.0, 0.3, 0.8, 1.0])).values.tolist() == [
        "solid",
        "22",
        "44",
        "44",
    ]


def test_binned_scale_squishes_out_of_range_values() -> None:
    """`binned_scale(oob = squish)`：超出 limits 的值压到两端，不是 NA。"""
    scale = _train(scale_from_component(Scale("shape_binned", "shape", {})), [0.0, 1.0])
    mapped = scale.map(column([-1.0, 2.0]))
    assert mapped.na_mask.tolist() == [False, False]
    assert mapped.values.tolist() == [16.0, 3.0]


def test_binned_scale_expands_data_limits_to_the_outer_breaks() -> None:
    """数据驱动的 limits 会往外扩到相邻断点（上游 `ScaleBinned$get_breaks`）。"""
    scale = _train(scale_from_component(Scale("shape_binned", "shape", {})), [2.0, 20.0])
    limits, breaks = scale._bin_info()
    assert limits == (0.0, 20.0)
    assert breaks == (5.0, 10.0, 15.0)


def test_discrete_manual_scale_takes_an_aesthetics_argument() -> None:
    """跨美学的 `scale_discrete_manual(aesthetics=...)`：美学由参数给。"""
    from ggcore import registry

    component = registry.scale_discrete_manual(aesthetics="linetype", values=["solid", "dashed"])
    assert component.aesthetic == "linetype"
    assert component.key == "linetype"
    with pytest.raises(ValueError, match="aesthetics"):
        registry.scale_discrete_manual(values=["solid"])
    with pytest.raises(ValueError, match="一个美学"):
        registry.scale_discrete_identity(aesthetics=["colour", "fill"])


def test_continuous_shape_and_linetype_scales_abort() -> None:
    """连续变量不能映射到 shape / linetype：上游 cli_abort，这里构造即报错。"""
    from ggcore import registry

    with pytest.raises(ScaleError, match="continuous variable cannot be mapped to the shape"):
        registry.scale_shape_continuous()
    with pytest.raises(ScaleError, match="continuous variable cannot be mapped to the linetype"):
        registry.scale_linetype_continuous()


def test_linetype_and_linewidth_defaults_come_from_the_pipeline() -> None:
    """不写 `scale_*` 时，linetype / linewidth 也有默认标度（上游 add_missing）。"""
    table = ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0, 3.0, 4.0]))),
            ("y", Column("float", np.array([1.0, 2.0, 1.5, 2.5]))),
            ("g", Column("str", np.array(["a", "b", "a", "b"], dtype=object))),
        ]
    )
    plot = ggplot(table, aes(x="x", y="y", linetype="g", linewidth="x")) + registry.geom_line()
    build = build_plot(plot)
    assert isinstance(build.scales.scale("linetype"), LinetypeScale)
    assert isinstance(build.scales.scale("linewidth"), LinewidthScale)
    assert build.scales.limits("linetype") == ("a", "b")
    # `geom_line` 的 setup_data 会按 (PANEL, group, x) 排序，所以按集合比。
    data = build.layers[0].data
    assert sorted(set(data.column("linetype").values.tolist())) == ["22", "solid"]
    assert sorted(data.column("linewidth").values.tolist()) == pytest.approx(
        [1.0, 2.6666666666666665, 4.333333333333333, 6.0]
    )


# ---------------------------------------------------------------------------
# log2 / exp（SIL-790）
# ---------------------------------------------------------------------------


def test_log2_transform_uses_base_two_break_grid() -> None:
    """`transform_log2()` 的断点是 2 的幂，不是整十次幂。

    `numeric-log` 快照：x = 1..1e4 上 expand 后的范围让 `breaks_log(base = 2)` 落到
    `0.5, 8, 128, 2048`，面板里剩 `8 / 128 / 2048`（R 的标签也是这三个）。
    """
    scale = scale_from_component(Scale("x_continuous", "x", {"trans": "log2"}))
    scale.train(scale.transform(column([1.0, 1e4])))
    assert scale.transform_.name == "log2"
    assert scale.limits() == pytest.approx((0.0, math.log2(1e4)), abs=1e-12)
    # `breaks()` 是变换后的空间（log2 值），标签回到数据空间。
    assert scale.breaks() == (None, 3.0, 7.0, 11.0)
    assert scale.labels() == (None, "8", "128", "2048")


def test_exp_transform_is_base_raised_and_keeps_default_breaks_in_data_space() -> None:
    """`transform_exp(2)`：`x → 2**x`，断点仍是数据空间的默认值。

    `numeric-exp` 快照的 x / y 标签都是 1.0…3.0——上游 `transform_exp()` 不传
    `breaks`，所以 `extended_breaks()` 作用在**未变换**的范围上。
    """
    scale = scale_from_component(Scale("x_continuous", "x", {"trans": ("exp", 2)}))
    transformed = scale.transform(column([1.0, 3.0]))
    assert transformed.values.tolist() == [2.0, 8.0]
    scale.train(transformed)
    assert scale.limits() == pytest.approx((2.0, 8.0), abs=1e-12)
    assert scale.labels() == ("1.0", "1.5", "2.0", "2.5", "3.0")


def test_parametric_transforms_reject_unknown_kinds() -> None:
    from ggcore.scales import ScaleError

    with pytest.raises(ScaleError, match="带参数的形式"):
        scale_from_component(Scale("x_continuous", "x", {"trans": ("log1p", 2)}))
    with pytest.raises(ScaleError, match="尚未实现"):
        scale_from_component(Scale("x_continuous", "x", {"trans": "log1p"}))


# ---------------------------------------------------------------------------
# 函数形态的 limits / labels（SIL-790）
# ---------------------------------------------------------------------------


def test_function_limits_are_applied_to_the_trained_range() -> None:
    """`scale_y_continuous(limits = function(lims) ...)`（`functional-limits` 快照）。

    上游 `ScaleContinuous$get_limits()` 把**变换后**的训练范围喂给函数；返回值
    也按变换后空间消费。`limiter(50)` 作用在计数 0..62 上 → 0..100。
    """

    def limiter(by: float):
        def limits(values):
            low, high = values
            return (math.floor(low / by) * by, math.ceil(high / by) * by)

        return limits

    scale = scale_from_component(Scale("y_continuous", "y", {"limits": limiter(50)}))
    scale.train(column([0.0, 62.0]))
    assert scale.limits() == (0.0, 100.0)
    labels = scale.labels()
    assert [label for label in labels if label is not None] == ["0", "25", "50", "75", "100"]


def test_callable_labels_get_untransformed_breaks_and_keep_na_positions() -> None:
    """`labels = function(breaks)`：回调只收未 censor 的断点，NA 位置留空。"""
    seen: list[list[float]] = []

    def labels(values):
        seen.append(list(values))
        return [f"<{value:g}>" for value in values]

    scale = scale_from_component(
        Scale("x_continuous", "x", {"breaks": [1.0, 3.0], "labels": labels})
    )
    scale.train(column([2.0, 3.0]))
    # limits = 2..3 → 1 被 censor 成 None，回调只收到 3。
    assert scale.breaks() == (None, 3.0)
    assert scale.labels() == (None, "<3>")
    assert seen == [[3.0]]

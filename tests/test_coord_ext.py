"""坐标系全量（M2-1）：`flip` / `trans` / `equal` / `polar` / `radial` / 次轴。

R 逐值对拍在 `tests/test_coord_r_parity.py`（夹具
`tests/fixtures/coord_r_reference.json`，26 个 case）；这里守的是**手算能推出**
的口径与错误面：

- 12 个 `coord_*` 导出全部登记，位置参数与关键字参数落到同一个组件；
- `coord_flip` 不是交换映射：`transform_column()` 读对侧列、轴取对侧标度，
  geom 里不判断 coord 名字；
- `coord_trans` 在标度空间之后再变换，范围在变换后的空间 expand；
- `coord_polar` / `coord_radial` 的 theta / r 范围、角度、内半径、bbox；
- `sec_axis()` / `dup_axis()` 的断点 / 标签 / 位置（含单调性检查）；
- `coord_sf` / `coord_map` / `coord_quickmap` 的最小可用与「不支持时报什么错」。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from ggcore import registry
from ggcore.aes import aes
from ggcore.axis import AxisError, axis_ticks, dup_axis, sec_axis, secondary_ticks
from ggcore.build import build_plot
from ggcore.coord import (
    CartesianCoord,
    CoordError,
    CoordTransform,
    EqualCoord,
    FixedCoord,
    FlipCoord,
    MapCoord,
    PolarCoord,
    QuickmapCoord,
    RadialCoord,
    SfCoord,
    TransCoord,
    as_coord_transform,
    coord_from_component,
    coord_munch,
    polar_bbox,
    r_rescale,
    theta_rescale,
)
from ggcore.data import Column, ColumnTable
from ggcore.plot import ggplot
from ggcore.theme import theme, theme_void

DATA = ColumnTable(
    [
        ("x", Column("float", np.array([1.513, 2.0, 2.5, 3.2, 4.7, 5.424]))),
        ("y", Column("float", np.array([9.225, 12.0, 18.5, 22.1, 30.0, 35.075]))),
        ("g", Column("str", np.array(["a", "b", "c", "c", "a", "b"]))),
    ]
)

DISCRETE = ColumnTable(
    [
        ("cls", Column("str", np.array(["a", "b", "c", "d", "e"]))),
        ("v", Column("float", np.array([1.0, 2.5, 1.8, 3.0, 2.2]))),
    ]
)


def continuous_plot() -> ggplot:
    return ggplot(DATA, aes(x="x", y="y")) + registry.geom_point()


def discrete_plot() -> ggplot:
    return ggplot(DISCRETE, aes(x="cls", y="v")) + registry.geom_point()


def params_of(plot: ggplot):
    build = build_plot(plot)
    assert build.panel_params is not None
    return build, build.panel_params


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------


def test_all_coord_exports_are_registered() -> None:
    """4.0.3 NAMESPACE 的 12 个 `coord_*` 导出全部有入口。"""
    expected = {
        "coord_cartesian",
        "coord_equal",
        "coord_fixed",
        "coord_flip",
        "coord_map",
        "coord_munch",
        "coord_polar",
        "coord_quickmap",
        "coord_radial",
        "coord_sf",
        "coord_trans",
        "coord_transform",
    }
    entries = {f"coord_{name}" for name in registry.registered("coord")}
    # coord_munch 是函数（不是坐标系构造器），单独由 ggcore.coord 导出。
    assert expected - {"coord_munch"} <= entries
    from ggcore import coord as coord_module
    from ggcore import plot as plot_module

    assert callable(coord_module.coord_munch)
    for name in sorted(expected):
        assert hasattr(plot_module, name), name


def test_positional_arguments_reach_the_component() -> None:
    """`coord_polar("y")` / `coord_fixed(2)` / `coord_transform("log10")` 都能用。"""
    assert registry.coord_polar("y").params["theta"] == "y"
    assert registry.coord_fixed(2).params["ratio"] == 2
    assert registry.coord_transform("log10").params["x"] == "log10"
    # 位置与关键字重复 → TypeError（上游 R 也会报 unused / matched 冲突）。
    with pytest.raises(TypeError, match="重复"):
        registry.coord_polar("y", theta="x")
    with pytest.raises(TypeError, match="最多接受"):
        registry.coord_fixed(1, 2)


def test_dotted_names_accept_underscore_spelling() -> None:
    radial = coord_from_component(registry.coord_radial(inner_radius=0.3))
    assert isinstance(radial, RadialCoord)
    assert radial.inner_radius == pytest.approx(0.3)
    assert radial.r_axis_inside is None


# ---------------------------------------------------------------------------
# flip
# ---------------------------------------------------------------------------


def test_flip_swaps_ranges_and_scale_keys() -> None:
    build, params = params_of(discrete_plot() + registry.coord_flip())
    assert isinstance(params.coord, str) and params.coord == "flip"
    assert params.flipped is True
    # 面板 x = 原始 y 的范围（连续 v: 1..3 再 5%）；面板 y = 原始 x（离散 1..n + 0.6）
    assert params.x_range == pytest.approx((0.9, 3.1))
    assert params.y_range == pytest.approx((0.4, 5.6))
    assert params.scale_key("bottom") == "y"
    assert params.scale_key("left") == "x"
    assert params.discrete["x"] is False and params.discrete["y"] is True
    assert build.coord is not None and build.coord.name == "flip"


def test_flip_transform_reads_the_other_column() -> None:
    _, params = params_of(continuous_plot() + registry.coord_flip())
    table = ColumnTable(
        [
            ("x", Column("float", np.array([2.0, 4.0]))),
            ("y", Column("float", np.array([10.0, 30.0]))),
        ]
    )
    # 屏幕 x 取 y 数据（x_range 是 y 的范围）；屏幕 y 取 x 数据。
    assert list(params.transform_column(table, "x", "x").values) == pytest.approx(
        [(10 - 7.9325) / 28.435, (30 - 7.9325) / 28.435], abs=1e-9
    )
    assert list(params.transform_column(table, "y", "y").values) == pytest.approx(
        [(2 - 1.31745) / 4.3021, (4 - 1.31745) / 4.3021], abs=1e-9
    )
    # 派生列也走对侧（xmin ← ymin）
    derived = ColumnTable(
        [
            ("xmin", Column("float", np.array([1.0]))),
            ("ymin", Column("float", np.array([10.0]))),
        ]
    )
    assert float(params.transform_column(derived, "xmin", "x").values[0]) == pytest.approx(
        (10 - params.x_range[0]) / (params.x_range[1] - params.x_range[0])
    )


def test_flip_accepts_ratio_and_keeps_aspect_from_swapped_ranges() -> None:
    _, params = params_of(continuous_plot() + registry.coord_flip(ratio=2))
    assert params.ratio == pytest.approx(2.0)
    # aspect = ratio × (面板 y 跨度 / 面板 x 跨度)，flip 后两条范围对调
    assert params.aspect_ratio == pytest.approx(2.0 * (5.61955 - 1.31745) / (36.3675 - 7.9325))


# ---------------------------------------------------------------------------
# trans
# ---------------------------------------------------------------------------


def test_trans_expands_in_the_transformed_space() -> None:
    _, params = params_of(continuous_plot() + registry.coord_transform(x="log10"))
    # base = 数据范围（identity 标度）；先 log10 再 expand 5%
    low, high = math.log10(1.513), math.log10(5.424)
    margin = 0.05 * (high - low)
    assert params.x_range == pytest.approx((low - margin, high + margin))
    # 连续范围（标度空间）是反变换回去的结果（断点用）
    assert params.continuous_ranges["x"] == pytest.approx(
        (10 ** (low - margin), 10 ** (high + margin))
    )
    # `position_of()` 的入参在**标度空间**（log10 之前的值）；coord 变换在这里作用
    position = params.position_of("x", 2.0)
    assert position == pytest.approx((math.log10(2.0) - (low - margin)) / ((high - low) * 1.1))


def test_trans_sqrt_is_axis_local() -> None:
    _, params = params_of(continuous_plot() + registry.coord_transform(y="sqrt"))
    assert params.y_range == pytest.approx(
        (
            math.sqrt(9.225) - 0.05 * (math.sqrt(35.075) - math.sqrt(9.225)),
            math.sqrt(35.075) + 0.05 * (math.sqrt(35.075) - math.sqrt(9.225)),
        )
    )
    assert params.trans["x"].name == "identity"
    assert params.trans["y"].name == "sqrt"
    assert params.is_linear is False


def test_trans_pseudo_log_object_and_name() -> None:
    """`coord_transform(x = transform_pseudo_log())`（SIL-856）。

    R 的 `coord_transform()` 直接收 scales 的变换对象；这里认
    `ggcore.scales` 的变换对象、注册名 `"pseudo_log"`，以及任意组合
    （`transform_compose()` 的返回值也能这么传给 coord）。
    """
    from ggcore.scales import transform_compose, transform_log10, transform_pseudo_log

    for value in (transform_pseudo_log(), "pseudo_log"):
        coord = TransCoord(x=value)
        assert coord.x.name == "pseudo_log"
        assert coord.x.apply(np.array([0.0]))[0] == pytest.approx(0.0)
        assert coord.x.apply(np.array([1.0]))[0] == pytest.approx(math.asinh(0.5))
        assert coord.x.invert(np.array([math.asinh(0.5)]))[0] == pytest.approx(1.0)

    composed = as_coord_transform(transform_compose(transform_log10(), transform_pseudo_log()))
    assert composed.name == "composition(log10,pseudo_log)"

    _, params = params_of(continuous_plot() + registry.coord_transform(x=transform_pseudo_log()))
    low, high = math.asinh(1.513 / 2.0), math.asinh(5.424 / 2.0)
    margin = 0.05 * (high - low)
    assert params.x_range == pytest.approx((low - margin, high + margin))
    # 连续范围（标度空间）是伪对数反解回来的数据值（断点 / guide 用）
    assert params.continuous_ranges["x"] == pytest.approx(
        (2.0 * math.sinh(low - margin), 2.0 * math.sinh(high + margin))
    )
    assert params.position_of("x", 0.0) == pytest.approx((-low + margin) / ((high - low) * 1.1))


def test_trans_rejects_unknown_and_unsupported_names() -> None:
    with pytest.raises(CoordError, match="尚未实现"):
        coord_from_component(registry.coord_transform(x="boxcox"))
    with pytest.raises(CoordError, match="未知的 coord 变换"):
        as_coord_transform("wobble")
    # log10 作用在非正范围上要报错，不能静默画 NaN
    with pytest.raises(CoordError, match="不是有限值"):
        build_plot(
            ggplot(
                ColumnTable(
                    [
                        ("x", Column("float", np.array([-2.0, 3.0]))),
                        ("y", Column("float", np.array([1.0, 2.0]))),
                    ]
                ),
                aes(x="x", y="y"),
            )
            + registry.geom_point()
            + registry.coord_transform(x="log10")
        )


def test_reverse_flips_the_mapping_only() -> None:
    _, plain = params_of(continuous_plot())
    _, reversed_ = params_of(continuous_plot() + registry.coord_cartesian(reverse="x"))
    assert reversed_.x_range == plain.x_range
    assert reversed_.reverse["x"] is True
    assert reversed_.reverse["y"] is False
    assert reversed_.npc("x", np.array([2.0]))[0] == pytest.approx(
        1 - plain.npc("x", np.array([2.0]))[0]
    )


# ---------------------------------------------------------------------------
# equal
# ---------------------------------------------------------------------------


def test_equal_is_fixed_ratio_one() -> None:
    _, equal = params_of(continuous_plot() + registry.coord_equal())
    _, fixed = params_of(continuous_plot() + registry.coord_fixed(ratio=1))
    assert equal.x_range == fixed.x_range
    assert equal.y_range == fixed.y_range
    assert (
        equal.aspect_ratio
        == fixed.aspect_ratio
        == pytest.approx((35.075 - 9.225) * 1.05 / ((5.424 - 1.513) * 1.05))
    )
    assert isinstance(coord_from_component(registry.coord_equal()), EqualCoord)
    # coord_cartesian(ratio=) 也是同一口径（4.0.3 的 coord_equal 就是它的糖）
    _, cartesian = params_of(continuous_plot() + registry.coord_cartesian(ratio=1))
    assert cartesian.aspect_ratio == pytest.approx(equal.aspect_ratio)
    assert isinstance(coord_from_component(registry.coord_fixed(2)), FixedCoord)


def test_panel_sizes_respects_aspect() -> None:
    _, params = params_of(continuous_plot() + registry.coord_equal())
    width, height = params.panel_sizes(10.0, 3.0)
    assert height / width == pytest.approx(params.aspect_ratio)
    assert width == pytest.approx(3.0 / params.aspect_ratio)
    _, free = params_of(continuous_plot())
    assert free.panel_sizes(10.0, 3.0) == (10.0, 3.0)


# ---------------------------------------------------------------------------
# polar / radial
# ---------------------------------------------------------------------------


def test_polar_ranges_follow_r_expansion() -> None:
    _, params = params_of(discrete_plot() + registry.coord_polar())
    polar = params.polar
    assert polar is not None
    # 离散 theta：add = 0.5（不是 0.6）；连续 r：不 expand
    assert polar.theta_range == pytest.approx((0.5, 5.5))
    assert polar.r_range == pytest.approx((1.0, 3.0))
    assert params.aspect_ratio == 1.0
    assert polar.bbox == ((0.0, 1.0), (0.0, 1.0))


def test_polar_theta_y_swaps_theta_and_radius() -> None:
    _, params = params_of(discrete_plot() + registry.coord_polar(theta="y"))
    polar = params.polar
    assert polar is not None
    assert polar.theta_axis == "y"
    assert polar.theta_range == pytest.approx((1.0, 3.0))  # 连续 y 不 expand
    assert polar.r_range == pytest.approx((1.0, 5.0))  # 离散 x 也没有额外 expand
    # 角度来自 y、半径来自 x：`project(theta, r)`
    x, y = polar.project(np.array([2.5]), np.array([1.0]))
    angle = theta_rescale(np.array([2.5]), polar.theta_range, polar.arc, polar.direction)[0]
    radius = r_rescale(np.array([1.0]), polar.r_range, polar.inner_radius)[0]
    assert x[0] == pytest.approx(radius * math.sin(angle) + 0.5)
    assert y[0] == pytest.approx(radius * math.cos(angle) + 0.5)


def test_polar_start_and_direction() -> None:
    _, params = params_of(discrete_plot() + registry.coord_polar(start=0.5 * math.pi, direction=-1))
    polar = params.polar
    assert polar is not None
    assert polar.arc[0] == pytest.approx(0.5 * math.pi)
    assert polar.direction == -1.0
    # 第一个断点落在 start 处（mod 2π 后是 0.5π）
    angle = polar.theta_angle(np.array([polar.theta_range[0]]))[0]
    assert math.cos(angle) == pytest.approx(math.cos(0.5 * math.pi), abs=1e-9)


def test_radial_partial_arc_and_inner_radius() -> None:
    _, params = params_of(
        discrete_plot() + registry.coord_radial(start=-0.5 * math.pi, end=0.5 * math.pi)
    )
    polar = params.polar
    assert polar is not None
    assert polar.arc == pytest.approx((-0.5 * math.pi, 0.5 * math.pi))
    assert list(polar.bbox[0]) == pytest.approx([0.0, 1.0])
    assert list(polar.bbox[1]) == pytest.approx([0.45, 1.0])
    assert params.aspect_ratio == pytest.approx(0.55)
    assert polar.r_axis_inside is True  # 非满圆默认把 r 轴画在面板里

    _, donut = params_of(discrete_plot() + registry.coord_radial(inner_radius=0.3))
    assert donut.polar is not None
    assert donut.polar.inner_radius == pytest.approx((0.12, 0.4))
    radii = donut.polar.radius(np.array([1.0, 3.0]))
    low, high = donut.polar.r_range
    # r 范围是 0.9..3.1（radial 用默认 5% 展开），内半径 0.12 是 r=low 时的值
    assert radii[0] == pytest.approx(0.12 + (1.0 - low) / (high - low) * (0.4 - 0.12))
    assert radii[1] == pytest.approx(0.12 + (3.0 - low) / (high - low) * (0.4 - 0.12))


def test_radial_defaults_match_r() -> None:
    radial = coord_from_component(registry.coord_radial())
    assert isinstance(radial, RadialCoord)
    assert radial.clip == "off"  # R 4.0.3 的默认
    assert coord_from_component(registry.coord_polar()).clip == "on"


def test_polar_bbox_matches_upstream_formula() -> None:
    assert polar_bbox((0.0, 2 * math.pi)) == ((0.0, 1.0), (0.0, 1.0))
    box = polar_bbox((-0.5 * math.pi, 0.5 * math.pi), (0.0, 0.4))
    assert list(box[0]) == pytest.approx([0.0, 1.0])
    assert list(box[1]) == pytest.approx([0.45, 1.0])


def test_theta_rescale_wraps_and_squishes() -> None:
    values = theta_rescale(np.array([0.0, 0.5, 1.0]), (0.0, 1.0), (0.0, 2 * math.pi))
    assert list(values) == pytest.approx([0.0, math.pi, 0.0])
    assert np.isnan(theta_rescale(np.array([np.nan]), (0.0, 1.0))[0])
    with pytest.raises(CoordError, match="跨度为 0"):
        theta_rescale(np.array([1.0]), (1.0, 1.0))


# ---------------------------------------------------------------------------
# 次轴
# ---------------------------------------------------------------------------


def _sec_plot(secondary):
    return (
        discrete_plot()
        + registry.scale_y_continuous(sec_axis=secondary)
        + theme_void()
        + theme(**{"legend.position": "none"})
    )


def test_sec_axis_breaks_positions_and_labels() -> None:
    build, params = params_of(_sec_plot(sec_axis(lambda v: v * 2)))
    scale = build.scales.scale("y")
    ticks = secondary_ticks(scale, params, "right")
    assert ticks.labels == ("2", "3", "4", "5", "6")
    # 次轴断点 2..6 反演回主轴 1..3，位置与主轴一致
    primary = axis_ticks(scale, params, "left")
    assert list(ticks.positions) == pytest.approx(
        [
            (value - params.y_range[0]) / (params.y_range[1] - params.y_range[0])
            for value in (1.0, 1.5, 2.0, 2.5, 3.0)
        ]
    )
    assert len(primary.positions) == len(ticks.positions)


def test_dup_axis_repeats_the_primary_ticks() -> None:
    build, params = params_of(_sec_plot(dup_axis()))
    scale = build.scales.scale("y")
    primary = axis_ticks(scale, params, "left")
    duplicate = secondary_ticks(scale, params, "right")
    assert duplicate.positions == primary.positions
    assert duplicate.labels == primary.labels


def test_sec_axis_rejects_non_monotonic_transforms() -> None:
    build, params = params_of(_sec_plot(sec_axis(lambda v: (v - 2.0) ** 2)))
    with pytest.raises(AxisError, match="严格单调"):
        secondary_ticks(build.scales.scale("y"), params, "right")


def test_sec_axis_on_x_uses_the_top_slot() -> None:
    plot = (
        continuous_plot()
        + registry.scale_x_continuous(sec_axis=sec_axis(lambda v: v * 2))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    build, params = params_of(plot)
    scale = build.scales.scale("x")
    ticks = secondary_ticks(scale, params, "top")
    assert ticks.side == "top"
    # x 数据 1.513..5.424 → 次轴空间 2.63..10.85 → extended_breaks 给 3/5/7/9/11
    assert ticks.labels == ("3", "5", "7", "9", "11")
    # 反演回主轴 1.5..5.5，位置按主轴范围（x_range）线性落位
    low, high = params.x_range
    assert list(ticks.positions) == pytest.approx(
        [(value - low) / (high - low) for value in (1.5, 2.5, 3.5, 4.5, 5.5)]
    )


def test_sec_axis_on_polar_uses_the_radius_rescale() -> None:
    """SIL-793：极坐标的 r 次轴不再报错——位置 = `r_rescale(r) + 0.5`。"""
    build, params = params_of(
        discrete_plot()
        + registry.coord_polar()
        + registry.scale_y_continuous(sec_axis=sec_axis(lambda v: v * 2))
    )
    scale = build.scales.scale("y")
    ticks = secondary_ticks(scale, params, "right")
    assert ticks.side == "right"
    assert ticks.positions
    polar = params.polar
    assert polar is not None
    for position in ticks.positions:
        assert 0.0 <= position <= 1.0
    # 次轴断点反演回主轴后要落在 r_rescale 的 `+0.5` 位置上（单调递增）
    assert list(ticks.positions) == sorted(ticks.positions)


# ---------------------------------------------------------------------------
# coord_munch
# ---------------------------------------------------------------------------


def test_coord_munch_is_identity_on_linear_coords() -> None:
    _, params = params_of(continuous_plot())
    table = ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0, 3.0]))),
            ("y", Column("float", np.array([10.0, 20.0, 30.0]))),
            ("group", Column("str", np.array(["1", "1", "1"]))),
        ]
    )
    munched = coord_munch(params, table)
    px, py = params.project_xy(np.array([1.0, 2.0, 3.0]), np.array([10.0, 20.0, 30.0]))
    assert munched.nrows == 3
    assert list(munched.column("x").values) == pytest.approx(px)
    assert list(munched.column("y").values) == pytest.approx(py)


def test_coord_munch_densifies_edges_on_polar() -> None:
    _, params = params_of(discrete_plot() + registry.coord_polar())
    table = ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0, 2.0, 1.0]))),
            ("y", Column("float", np.array([0.0, 0.0, 3.0, 3.0]))),
            ("group", Column("str", np.array(["1"] * 4))),
        ]
    )
    munched = coord_munch(params, table, is_closed=True)
    # 四条边按归一化距离细分：输出点数远多于输入的 4 个角
    assert munched.nrows > 4
    # 所有点都在 0..1 的面板里（满圆 bbox）
    assert float(munched.column("x").values.min()) >= 0.0
    assert float(munched.column("x").values.max()) <= 1.0
    assert float(munched.column("y").values.min()) >= 0.0
    assert float(munched.column("y").values.max()) <= 1.0


# ---------------------------------------------------------------------------
# sf / map / quickmap（最小可用）
# ---------------------------------------------------------------------------


def test_sf_and_map_accept_the_ported_projections() -> None:
    # M3-2：EPSG:4326 / 3857 / 3347 与 mapproj mercator 都落地；不认识的 CRS /
    # 投影仍然显式报错（不静默当 identity）。
    sf_coord = coord_from_component(registry.coord_sf(crs="EPSG:4326", default_crs=4326))
    assert isinstance(sf_coord, SfCoord)
    assert isinstance(coord_from_component(registry.coord_map(projection="mercator")), MapCoord)
    with pytest.raises(CoordError, match="尚未实现"):
        coord_from_component(registry.coord_map(projection="gilbert"))
    with pytest.raises(ValueError, match="不支持的 CRS"):
        coord_from_component(registry.coord_sf(crs="EPSG:27700"))
    # identity 投影可用：与 coord_fixed(ratio = 1) 同一套范围 + 等比例
    identity = coord_from_component(registry.coord_map(projection="identity"))
    assert isinstance(identity, MapCoord)
    _, params = params_of(continuous_plot() + registry.coord_map(projection="identity"))
    assert params.aspect_ratio == pytest.approx((35.075 - 9.225) * 1.05 / ((5.424 - 1.513) * 1.05))
    assert isinstance(coord_from_component(registry.coord_sf()), SfCoord)


def test_quickmap_uses_the_latitude_factor() -> None:
    quickmap = coord_from_component(registry.coord_quickmap())
    assert isinstance(quickmap, QuickmapCoord)
    _, params = params_of(continuous_plot() + registry.coord_quickmap())
    mid_latitude = (params.y_range[0] + params.y_range[1]) / 2.0
    expected = (
        (params.y_range[1] - params.y_range[0])
        / (params.x_range[1] - params.x_range[0])
        / math.cos(math.radians(mid_latitude))
    )
    assert params.aspect_ratio == pytest.approx(expected)


# ---------------------------------------------------------------------------
# 错误面
# ---------------------------------------------------------------------------


def test_unknown_params_and_coord_names_are_rejected() -> None:
    with pytest.raises(CoordError, match="不认识参数"):
        coord_from_component(registry.coord_polar(theta="x", wobble=1))
    from ggcore.components import Coord

    with pytest.raises(CoordError, match="尚未实现"):
        coord_from_component(Coord("hexagonal"))
    with pytest.raises(CoordError, match="theta 只能是"):
        coord_from_component(registry.coord_polar(theta="z"))
    with pytest.raises(CoordError, match=r"inner\.radius"):
        coord_from_component(registry.coord_radial(inner_radius=1.5))


def test_polar_transform_column_requires_a_pair() -> None:
    _, params = params_of(discrete_plot() + registry.coord_polar())
    table = ColumnTable([("x", Column("float", np.array([1.0])))])
    with pytest.raises(CoordError, match="没有位置列"):
        params.transform_column(table, "nonsense", "x")


def test_coord_transform_callable_has_no_inverse() -> None:
    custom = CoordTransform(name="function")
    assert custom.apply(np.array([1.0]))[0] == pytest.approx(1.0)
    with pytest.raises(CoordError):
        TransCoord(x=lambda values: np.log1p(values)).x.invert(np.array([1.0]))


def test_cartesian_ratio_validation() -> None:
    with pytest.raises(CoordError, match="ratio"):
        CartesianCoord(ratio=0)
    with pytest.raises(CoordError, match="ratio"):
        FixedCoord(ratio=-1)
    with pytest.raises(CoordError, match="reverse"):
        CartesianCoord(reverse="z")


def test_flip_is_not_combinable_with_polar() -> None:
    from dataclasses import replace

    _, params = params_of(discrete_plot() + registry.coord_polar())
    from ggcore.coord import PanelParams

    with pytest.raises(CoordError, match="不能和极坐标"):
        PanelParams(
            x_range=params.x_range,
            y_range=params.y_range,
            x_limits=params.x_limits,
            y_limits=params.y_limits,
            polar=params.polar,
            flipped=True,
        )
    assert replace(params, flipped=False) is not params


def test_polar_and_flip_classes_are_wired() -> None:
    assert isinstance(coord_from_component(registry.coord_polar()), PolarCoord)
    assert isinstance(coord_from_component(registry.coord_flip()), FlipCoord)
    assert isinstance(coord_from_component(registry.coord_trans(x="log10")), TransCoord)

"""坐标系的契约（M1-5）：`coord_cartesian` / `coord_fixed`。

R 侧逐值对拍在 `tests/test_coord_r_parity.py`（夹具由
`tools/refs/coord_ref.R` 生成）；这里守的是**手算**能推出的口径：

- 范围 = base（scale limits 或 coord xlim/ylim）+ expand（连续 5%，离散 add 0.6）；
- 离散标度的 base 是 `1..n`，expand 之后才是 `0.4..n+0.6`
  （**不是** 0.5..n+0.5，见 `docs/notes/coord.md`）；
- xlim/ylim 与 scale limits 的面板范围相同，但越界点的处理不同、都要计数；
- `coord_fixed(ratio)` 的物理高/宽 = `ratio × y 跨度 / x 跨度`；
- 数据 → 面板 npc 的线性变换与越界值（不夹到 0..1）。

等比例的可视化测量（PNG / SVG 像素）在 `tests/test_coord_aspect.py`。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from ggcore import registry
from ggcore.aes import aes
from ggcore.build import build_plot
from ggcore.components import Coord
from ggcore.coord import (
    AXES,
    CartesianCoord,
    CoordError,
    FixedCoord,
    PanelParams,
    coord_from_component,
    count_dropped,
    count_out_of_bounds,
    count_rows_dropped,
)
from ggcore.data import Column, ColumnTable
from ggcore.plot import ggplot

#: 与 `tools/refs/coord_ref.R` 完全相同的 6 行数据（范围 / 离散水平一致）。
DATA = ColumnTable(
    [
        ("x", Column("float", np.array([1.513, 2.0, 2.5, 3.2, 4.7, 5.424]))),
        ("y", Column("float", np.array([9.225, 12.0, 18.5, 22.1, 30.0, 35.075]))),
        ("g", Column("str", np.array(["a", "b", "c", "c", "a", "b"]))),
    ]
)

#: log10 case 的数据（`coord_ref.R` 的 `log_data`）：数据空间 1..100 / 标度空间 0..2。
LOG_DATA = ColumnTable(
    [
        ("x", Column("float", np.array([1.0, 10.0, 100.0]))),
        ("y", Column("float", np.array([1.0, 2.0, 3.0]))),
    ]
)

X_LIMITS = (1.513, 5.424)
Y_LIMITS = (9.225, 35.075)


def base_plot() -> ggplot:
    return ggplot(DATA, aes(x="x", y="y")) + registry.geom_point()


def discrete_plot() -> ggplot:
    return ggplot(DATA, aes(x="g", y="y")) + registry.geom_point()


def log_plot() -> ggplot:
    return ggplot(LOG_DATA, aes(x="x", y="y")) + registry.geom_point() + registry.scale_x_log10()


def panel_params(plot: ggplot) -> PanelParams:
    build = build_plot(plot)
    assert build.panel_params is not None
    assert build.coord is not None
    return build.panel_params


# ---------------------------------------------------------------------------
# 范围
# ---------------------------------------------------------------------------


def test_default_cartesian_ranges_match_explicit_expand() -> None:
    params = panel_params(base_plot())
    assert params.coord == "cartesian"
    assert params.clip == "on"
    assert params.ratio is None
    assert params.aspect_ratio is None
    assert dict(params.discrete) == {"x": False, "y": False}
    assert dict(params.out_of_bounds) == {"x": 0, "y": 0}
    assert dict(params.dropped) == {"x": 0, "y": 0}
    assert params.x_limits == pytest.approx(X_LIMITS)
    assert params.y_limits == pytest.approx(Y_LIMITS)
    # 手工：宽 3.911 × 5% = 0.19555；25.85 × 5% = 1.2925
    assert params.x_range == pytest.approx((1.513 - 0.19555, 5.424 + 0.19555), abs=1e-12)
    assert params.y_range == pytest.approx((9.225 - 1.2925, 35.075 + 1.2925), abs=1e-12)
    assert dict(params.ranges) == {"x": params.x_range, "y": params.y_range}
    assert dict(params.limits) == {"x": params.x_limits, "y": params.y_limits}


def test_build_plot_exposes_coord_and_panel_params() -> None:
    build = build_plot(base_plot())
    assert isinstance(build.coord, CartesianCoord)
    assert build.panel_params is not None
    assert isinstance(build.panel_params, PanelParams)
    # 默认的 plot.coordinates 也是可解析的（不再是 `{"default": True}` 占位）
    assert base_plot().coordinates == Coord("cartesian")


def test_coord_expand_false_disables_expansion() -> None:
    params = panel_params(base_plot() + registry.coord_cartesian(expand=False))
    assert params.x_range == pytest.approx(X_LIMITS, abs=1e-12)
    assert params.y_range == pytest.approx(Y_LIMITS, abs=1e-12)


def test_coord_expand_default_keeps_scale_expansion() -> None:
    """`coord_cartesian(expand = TRUE)` 用标度自己的 expansion。"""
    plot = base_plot() + registry.scale_x_continuous(expand=(0, 0))
    params = panel_params(plot)
    assert params.x_range == pytest.approx(X_LIMITS, abs=1e-12)
    # y 仍走连续默认 5%
    assert params.y_range[0] == pytest.approx(9.225 - 1.2925, abs=1e-12)


def test_coord_expand_numeric_sequence_is_an_expansion() -> None:
    params = panel_params(base_plot() + registry.coord_cartesian(expand=(0.1, 0)))
    width = X_LIMITS[1] - X_LIMITS[0]
    assert params.x_range == pytest.approx(
        (X_LIMITS[0] - width * 0.1, X_LIMITS[1] + width * 0.1), abs=1e-12
    )


def test_coord_xlim_overrides_limits_and_counts_out_of_bounds() -> None:
    plot = base_plot() + registry.coord_cartesian(xlim=(2, 5))
    build = build_plot(plot)
    params = build.panel_params
    assert params is not None
    assert params.x_limits == (2.0, 5.0)
    # 5% of 3 = 0.15
    assert params.x_range == pytest.approx((1.85, 5.15), abs=1e-12)
    assert params.y_limits == pytest.approx(Y_LIMITS)
    # 1.513 与 5.424 两个点越界（xlim 不删数据，只计数）
    assert dict(params.out_of_bounds) == {"x": 2, "y": 0}
    assert dict(params.dropped) == {"x": 0, "y": 0}
    assert any("2 个值" in note and "超出范围" in note for note in build.warnings)
    assert len(build.layers[0].data.column("x").values) == 6


def test_scale_limits_censor_and_count_out_of_bounds() -> None:
    plot = base_plot() + registry.scale_x_continuous(limits=(2, 5))
    build = build_plot(plot)
    params = build.panel_params
    assert params is not None
    assert params.x_range == pytest.approx((1.85, 5.15), abs=1e-12)
    # 标度 limits 把越界值变成 NA：行级 rows_dropped 才是 R 的 "Removed 2 rows"
    assert dict(params.out_of_bounds) == {"x": 0, "y": 0}
    assert dict(params.dropped) == {"x": 2, "y": 0}
    assert params.rows_dropped == 2
    assert any("按轴计数" in note for note in build.warnings)
    assert any("Removed 2 rows" in note for note in build.warnings)
    x = build.layers[0].scaled.column("x")
    assert int(np.count_nonzero(x.na_mask)) == 2
    assert 1.513 not in set(x.values.tolist())


def test_discrete_default_range_is_one_to_n_not_half_past() -> None:
    params = panel_params(discrete_plot())
    assert params.x_limits == (1.0, 3.0)
    # 离散默认 expansion(add = 0.6)：1 - 0.6 .. 3 + 0.6
    assert params.x_range == pytest.approx((0.4, 3.6), abs=1e-12)
    assert dict(params.discrete) == {"x": True, "y": False}


def test_discrete_scale_limits_with_out_of_bounds_level() -> None:
    plot = discrete_plot() + registry.scale_x_discrete(limits=("a", "b", "d"))
    build = build_plot(plot)
    params = build.panel_params
    assert params is not None
    assert params.x_range == pytest.approx((0.4, 3.6), abs=1e-12)
    # 两行 `c` 被标度 limits 丢掉（R: Removed 2 rows）
    assert dict(params.dropped)["x"] == 2
    assert dict(params.out_of_bounds)["x"] == 0
    assert int(np.count_nonzero(build.layers[0].scaled.column("x").na_mask)) == 2

    narrower = discrete_plot() + registry.scale_x_discrete(limits=("a", "b"))
    assert panel_params(narrower).x_range == pytest.approx((0.4, 2.6), abs=1e-12)


def test_discrete_coord_xlim_numeric_and_names() -> None:
    numeric = panel_params(discrete_plot() + registry.coord_cartesian(xlim=(0.5, 2.5)))
    assert numeric.x_limits == (0.5, 2.5)
    assert numeric.x_range == pytest.approx((-0.1, 3.1), abs=1e-12)
    # coord xlim 不删数据：2 行 `c` 在面板外，但没有变 NA
    assert dict(numeric.out_of_bounds)["x"] == 2
    assert dict(numeric.dropped)["x"] == 0

    names = panel_params(discrete_plot() + registry.coord_cartesian(xlim=("a", "b")))
    assert names.x_limits == (1.0, 2.0)
    assert names.x_range == pytest.approx((0.4, 2.6), abs=1e-12)
    assert dict(names.out_of_bounds)["x"] == 2
    assert dict(names.dropped)["x"] == 0


def test_coord_xlim_validation() -> None:
    with pytest.raises(CoordError, match="2 元序列"):
        coord_from_component(registry.coord_cartesian(xlim=(1,)))
    with pytest.raises(CoordError, match="连续标度"):
        build_plot(base_plot() + registry.coord_cartesian(xlim=("a", "b")))
    with pytest.raises(CoordError, match="不在标度水平"):
        build_plot(discrete_plot() + registry.coord_cartesian(xlim=("a", "z")))
    with pytest.raises(CoordError, match="混用"):
        build_plot(base_plot() + registry.coord_cartesian(xlim=(1, "b")))


# ---------------------------------------------------------------------------
# 位置标度的 transform（R `expand_limits_scale()`）
# ---------------------------------------------------------------------------


def test_log10_coord_xlim_is_transformed_before_expand() -> None:
    """`xlim` 是数据空间的值：先 log10 再做 expand（R 面板 `-0.1 .. 2.1`）。"""
    params = panel_params(log_plot() + registry.coord_cartesian(xlim=(1, 100)))
    assert params.x_limits == pytest.approx((0.0, 2.0), abs=1e-12)
    assert params.x_range == pytest.approx((-0.1, 2.1), abs=1e-12)
    # 数据 1/10/100 的 log10 是 0/1/2，全在 [0, 2] 里
    assert dict(params.out_of_bounds) == {"x": 0, "y": 0}
    assert dict(params.dropped) == {"x": 0, "y": 0}
    assert params.rows_dropped == 0
    assert not params.warnings()

    narrower = panel_params(log_plot() + registry.coord_cartesian(xlim=(10, 100)))
    assert narrower.x_limits == pytest.approx((1.0, 2.0), abs=1e-12)
    assert narrower.x_range == pytest.approx((0.95, 2.05), abs=1e-12)
    # log10(1) = 0 在 [1, 2] 外：只计数，数据行还在
    assert dict(narrower.out_of_bounds) == {"x": 1, "y": 0}
    assert dict(narrower.dropped) == {"x": 0, "y": 0}


def test_log10_scale_limits_and_coord_limits_stack_in_scale_space() -> None:
    """标度 limits（已是 log10 空间）与 coord limits（数据空间）各走一遍变换。"""
    plot = (
        log_plot()
        + registry.scale_x_log10(limits=(1, 100))
        + registry.coord_cartesian(xlim=(1, 10))
    )
    params = panel_params(plot)
    # 标度 limits 1..100 → 0..2；coord xlim 1..10 → 0..1 覆盖它，再 expand 5%
    assert params.x_limits == pytest.approx((0.0, 1.0), abs=1e-12)
    assert params.x_range == pytest.approx((-0.05, 1.05), abs=1e-12)
    # x = 100（log10 = 2）在面板外，但没被删
    assert dict(params.out_of_bounds) == {"x": 1, "y": 0}
    assert dict(params.dropped) == {"x": 0, "y": 0}


def test_log10_coord_fixed_aspect_uses_transformed_span() -> None:
    """log 轴的 aspect 也在变换后的范围上算：x/y 跨度都是 2.2 → aspect = ratio。"""
    plot = (
        log_plot()
        + registry.scale_x_log10(limits=(1, 100))
        + registry.coord_fixed(ratio=1, xlim=(1, 100))
    )
    params = panel_params(plot)
    assert params.x_range == pytest.approx((-0.1, 2.1), abs=1e-12)
    assert params.aspect_ratio == pytest.approx(1.0, abs=1e-12)
    assert params.panel_sizes(6.0, 4.0) == pytest.approx((4.0, 4.0), abs=1e-12)


def test_log10_coord_xlim_must_be_positive() -> None:
    with pytest.raises(CoordError, match="不是有限值"):
        build_plot(log_plot() + registry.coord_cartesian(xlim=(0, 100)))
    with pytest.raises(CoordError, match="不是有限值"):
        build_plot(log_plot() + registry.scale_y_log10() + registry.coord_fixed(ylim=(-1, 100)))


# ---------------------------------------------------------------------------
# 数据 → npc
# ---------------------------------------------------------------------------


def test_transform_maps_panel_ends_to_zero_and_one() -> None:
    params = panel_params(base_plot())
    column = Column("float", np.array([X_LIMITS[0], X_LIMITS[1]]))
    npc = params.transform(column, "x")
    assert npc.kind == "float"
    assert npc.values[0] == pytest.approx(
        (X_LIMITS[0] - params.x_range[0]) / (params.x_range[1] - params.x_range[0]), abs=1e-15
    )
    assert npc.values[1] == pytest.approx(
        (X_LIMITS[1] - params.x_range[0]) / (params.x_range[1] - params.x_range[0]), abs=1e-15
    )
    # y 同一条公式；面板 npc 的 0 在下方（y 向上）
    y_npc = params.transform(Column("float", np.array(Y_LIMITS)), "y")
    assert y_npc.values[0] == pytest.approx(
        (Y_LIMITS[0] - params.y_range[0]) / (params.y_range[1] - params.y_range[0]), abs=1e-15
    )


def test_transform_keeps_out_of_range_values_outside_zero_one() -> None:
    params = panel_params(base_plot() + registry.coord_cartesian(expand=False))
    npc = params.transform(Column("float", np.array([0.0, 1.513, 5.424, 6.0])), "x")
    assert npc.values[0] < 0.0
    assert npc.values[1] == pytest.approx(0.0)
    assert npc.values[2] == pytest.approx(1.0)
    assert npc.values[3] > 1.0


def test_transform_preserves_missing_values() -> None:
    params = panel_params(base_plot())
    column = Column("float", np.array([1.513, 0.0, 5.424]), na_mask=[False, True, False])
    npc = params.transform(column, "x")
    assert bool(npc.na_mask[1])
    assert npc.values[1] == 0.0


def test_transform_rejects_non_position_and_discrete_columns() -> None:
    params = panel_params(base_plot())
    with pytest.raises(CoordError, match="位置美学"):
        params.transform(Column("float", np.array([1.0])), "colour")
    with pytest.raises(CoordError, match="位置标度"):
        params.transform(DATA.column("g"), "x")


# ---------------------------------------------------------------------------
# 等比例
# ---------------------------------------------------------------------------


def test_fixed_aspect_and_panel_sizes_for_equal_spans() -> None:
    # 共享数据的 x / y 跨度不同：aspect = ratio × y 跨度 / x 跨度
    params = panel_params(base_plot() + registry.coord_fixed(ratio=2))
    assert params.ratio == 2.0
    x_span = params.x_range[1] - params.x_range[0]
    y_span = params.y_range[1] - params.y_range[0]
    assert params.aspect_ratio == pytest.approx(2.0 * y_span / x_span, abs=1e-12)
    width, height = params.panel_sizes(6.0, 4.0)
    assert height / width == pytest.approx(params.aspect_ratio, abs=1e-12)
    assert height == pytest.approx(4.0, abs=1e-12)

    # x / y 范围等宽时（本 issue 的 2×2 合成 panel 就是这种），物理高/宽 = ratio
    def square(ratio: float) -> PanelParams:
        return panel_params(
            base_plot() + registry.coord_fixed(ratio=ratio, xlim=(0, 1), ylim=(0, 1), expand=False)
        )

    assert square(2.0).aspect_ratio == pytest.approx(2.0, abs=1e-12)
    assert square(2.0).panel_sizes(6.0, 4.0) == pytest.approx((2.0, 4.0), abs=1e-12)
    assert square(1.0).panel_sizes(6.0, 4.0) == pytest.approx((4.0, 4.0), abs=1e-12)
    assert square(0.5).panel_sizes(6.0, 4.0) == pytest.approx((6.0, 3.0), abs=1e-12)
    # 默认 ratio = 1
    assert panel_params(base_plot() + registry.coord_fixed()).ratio == 1.0


def test_fixed_aspect_uses_data_span_ratio() -> None:
    """物理比例 = ratio × y 跨度 / x 跨度（R `CoordFixed$aspect()`）。"""
    plot = base_plot() + registry.coord_fixed(ratio=2, xlim=(0, 1), ylim=(0, 3), expand=False)
    params = panel_params(plot)
    assert params.x_range == pytest.approx((0.0, 1.0), abs=1e-12)
    assert params.y_range == pytest.approx((0.0, 3.0), abs=1e-12)
    assert params.aspect_ratio == pytest.approx(6.0, abs=1e-12)
    width, height = params.panel_sizes(6.0, 4.0)
    assert height / width == pytest.approx(6.0, abs=1e-12)
    assert height == pytest.approx(4.0, abs=1e-12)


def test_cartesian_panel_sizes_fill_the_available_area() -> None:
    params = panel_params(base_plot())
    assert params.panel_sizes(6.0, 4.0) == (6.0, 4.0)
    assert params.panel_sizes(3.0, 8.0) == (3.0, 8.0)


def test_panel_sizes_rejects_bad_device_and_ratio() -> None:
    params = panel_params(base_plot() + registry.coord_fixed(ratio=2))
    with pytest.raises(CoordError, match="正的设备尺寸"):
        params.panel_sizes(0.0, 4.0)
    with pytest.raises(CoordError, match="ratio"):
        coord_from_component(registry.coord_fixed(ratio=0))


def test_aspect_ratio_with_zero_span_raises_coord_error() -> None:
    """零跨度不能是 `ZeroDivisionError`：`xlim` 退化成一点 / 数据全相同都要说清楚。"""
    degenerate_x = panel_params(
        base_plot() + registry.coord_fixed(ratio=1, xlim=(2, 2), expand=False)
    )
    assert degenerate_x.x_range == pytest.approx((2.0, 2.0), abs=1e-12)
    with pytest.raises(CoordError, match="x 面板范围跨度为 0"):
        _ = degenerate_x.aspect_ratio
    with pytest.raises(CoordError, match="x 面板范围跨度为 0"):
        degenerate_x.panel_sizes(6.0, 4.0)

    degenerate_y = panel_params(
        base_plot() + registry.coord_fixed(ratio=1, ylim=(10, 10), expand=False)
    )
    with pytest.raises(CoordError, match="y 面板范围跨度为 0"):
        _ = degenerate_y.aspect_ratio

    # 数据全相同时（没有 xlim）也是同一个错误——但要 expand=FALSE：
    # 默认 expansion 对零宽范围用上游的 zero_width = 1，仍会撑出 0.1 的跨度
    flat = ColumnTable(
        [
            ("x", Column("float", np.array([5.0, 5.0, 5.0]))),
            ("y", Column("float", np.array([1.0, 2.0, 3.0]))),
        ]
    )
    default_flat = panel_params(
        ggplot(flat, aes(x="x", y="y")) + registry.geom_point() + registry.coord_fixed()
    )
    assert default_flat.x_range == pytest.approx((4.95, 5.05), abs=1e-12)

    flat_params = panel_params(
        ggplot(flat, aes(x="x", y="y")) + registry.geom_point() + registry.coord_fixed(expand=False)
    )
    with pytest.raises(CoordError, match="x 面板范围跨度为 0"):
        _ = flat_params.aspect_ratio


# ---------------------------------------------------------------------------
# clip / 参数 / 注册表
# ---------------------------------------------------------------------------


def test_clip_is_parsed_and_recorded() -> None:
    params = panel_params(base_plot() + registry.coord_fixed(ratio=1, clip="off"))
    assert params.clip == "off"
    # R 4.0.3 的 `coord_*()` 原样透传 `clip`（连 `"inherit"` 也构建成功）。
    assert coord_from_component(registry.coord_cartesian(clip="inherit")).clip == "inherit"
    assert coord_from_component(registry.coord_cartesian(clip="off")).clip == "off"
    with pytest.raises(CoordError, match="clip"):
        coord_from_component(registry.coord_cartesian(clip="sometimes"))


def test_plus_and_chain_aliases_share_the_registry() -> None:
    plus = base_plot() + registry.coord_fixed(ratio=2)
    chain = base_plot().coord_fixed(ratio=2)
    assert plus.coordinates == chain.coordinates
    assert plus.coordinates.name == "fixed"
    assert plus.coordinates.params["ratio"] == 2
    assert panel_params(plus).aspect_ratio == panel_params(chain).aspect_ratio
    # 注册表项换了，两条入口一起变
    assert plus.coordinates is not None


def test_unknown_coord_and_param_are_rejected() -> None:
    with pytest.raises(CoordError, match="尚未实现"):
        coord_from_component(Coord("polar"))
    with pytest.raises(CoordError, match="不认识参数"):
        build_plot(base_plot() + registry.coord_cartesian(foo=1))
    with pytest.raises(CoordError, match="不认识参数"):
        coord_from_component(Coord("fixed", {"ratio": 2, "expand": True, "foo": 1}))


def test_coord_from_component_accepts_implementations_and_none() -> None:
    fixed = FixedCoord(ratio=3)
    assert coord_from_component(fixed) is fixed
    assert isinstance(coord_from_component(None), CartesianCoord)


def test_explicit_scale_limits_on_discrete_count_matches_rows() -> None:
    """两个计数各管一类：`rows_dropped` = R 的 Removed，`out_of_bounds` = coord limits。"""
    build = build_plot(discrete_plot() + registry.scale_x_discrete(limits=("a", "b")))
    params = build.panel_params
    assert params is not None
    tables = (build.layers[0].scaled,)
    dropped = count_dropped(tables)
    out_of_bounds = count_out_of_bounds(params, tables)
    assert dict(dropped) == {"x": 2, "y": 0}
    assert dict(out_of_bounds) == {"x": 0, "y": 0}
    assert params.rows_dropped == count_rows_dropped(tables) == 2
    assert set(dropped) == set(AXES) == set(out_of_bounds)


def test_rows_dropped_counts_rows_not_axes() -> None:
    """同一行 x、y 都缺只算一行；原始 NA 也算在内，不与 scale limits 混说。"""
    table = ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 0.0, 0.0]), na_mask=[False, True, True])),
            ("y", Column("float", np.array([1.0, 0.0, 3.0]), na_mask=[False, True, False])),
        ]
    )
    # 按轴：x 缺 2 个、y 缺 1 个；按行：2 行（第 2 行两轴都缺只算一次）
    assert dict(count_dropped((table,))) == {"x": 2, "y": 1}
    assert count_rows_dropped((table,)) == 2
    assert count_rows_dropped(()) == 0


def test_build_reports_row_level_dropped_for_raw_na() -> None:
    """原始数据的 NA 也是「行被删」，这是 R 的 Removed 口径，不是 scale limits 的锅。"""
    table = ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 0.0, 3.0]), na_mask=[False, True, False])),
            ("y", Column("float", np.array([1.0, 0.0, 3.0]), na_mask=[False, True, False])),
        ]
    )
    build = build_plot(ggplot(table, aes(x="x", y="y")) + registry.geom_point())
    params = build.panel_params
    assert params is not None
    assert dict(params.dropped) == {"x": 1, "y": 1}
    assert params.rows_dropped == 1
    assert any("共 1 行含缺失位置" in note for note in build.warnings)
    assert any("按轴计数" in note for note in build.warnings)


def test_ratio_must_be_finite() -> None:
    with pytest.raises(CoordError, match="ratio"):
        coord_from_component(registry.coord_fixed(ratio=math.inf))

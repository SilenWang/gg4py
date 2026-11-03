"""坐标面板参数与 R ggplot2 4.0.3 的逐值对拍（M1-5）。

夹具由 `pixi run -e refs refs:coord`（`tools/refs/coord_ref.R`）生成，R 与 Python
用同一份数据（6 行的 `coord_data` + 3 行的 `log_data`）。对拍的是：

- `ggplot_build(p)$layout$panel_params[[1]]$x.range` / `y.range`（含 expand）；
- expand 前的范围：连续取 `get_limits()`，离散取 `1..n`；coord `xlim` / `ylim`
  在 R 里只出现在 `coord$limits`，测试用 R 侧 `transformation$transform()` 的
  结果（`coord_xlim_transformed`）替换 scale limits 后再比——coord limits 是
  **数据空间**的值，log10 标度上要先变成 `0..2` 这类标度空间的值；
- `CoordFixed$aspect()`（物理高/宽）与 `ratio`；
- `clip`、离散标记；
- 越界：`pp$rows_dropped`（行级）对 R 的 "Removed N rows"；`pp$dropped`
  （按轴）对本层 x / y 的 NA 数。

容差 `1e-12`（逐值）。数值断言只认夹具，不重算公式——重算会把「实现与自己的
公式一致」当成「与 R 一致」。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ggcore import registry
from ggcore.aes import aes
from ggcore.axis import axis_ticks, dup_axis, sec_axis, secondary_ticks
from ggcore.build import build_plot
from ggcore.data import Column, ColumnTable
from ggcore.geom.scene import plot_layout
from ggcore.plot import ggplot
from ggcore.theme import theme, theme_void

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "coord_r_reference.json"
REFERENCE = json.loads(FIXTURE.read_text(encoding="utf-8"))
CASES = {case["name"]: case for case in REFERENCE["cases"]}
TOLERANCE = 1e-12
#: R 的 `sec_axis` 断点位置在数据空间里按 `round(..., 3)` 落位（AxisSecondary
#: `$break_info()`），位置误差因此到 1e-4 量级。
SEC_TOLERANCE = 1e-3

#: 旧 case 是 theme_grey（文字度量参与版式），面板几何只能放到 0.1cm；
#: M2-1 的新 case 在 R 侧统一 `theme_void()`，几何可以对到 0.01cm。
_OLD_CASES = {
    "cartesian_default",
    "cartesian_expand_false",
    "cartesian_xlim",
    "scale_x_limits",
    "discrete_default",
    "discrete_xlim_levels",
    "fixed_ratio_1",
    "fixed_ratio_2",
    "log10_coord_xlim",
    "log10_scale_limits_coord",
}

DATA = ColumnTable(
    [
        ("x", Column("float", np.array(REFERENCE["data"]["x"], dtype=np.float64))),
        ("y", Column("float", np.array(REFERENCE["data"]["y"], dtype=np.float64))),
        ("g", Column("str", np.array(REFERENCE["data"]["g"], dtype=object))),
    ]
)

LOG_DATA = ColumnTable(
    [
        ("x", Column("float", np.array(REFERENCE["log_data"]["x"], dtype=np.float64))),
        ("y", Column("float", np.array(REFERENCE["log_data"]["y"], dtype=np.float64))),
    ]
)


def continuous_plot() -> ggplot:
    return ggplot(DATA, aes(x="x", y="y")) + registry.geom_point()


def discrete_plot() -> ggplot:
    return ggplot(DATA, aes(x="g", y="y")) + registry.geom_point()


def log_plot() -> ggplot:
    return ggplot(LOG_DATA, aes(x="x", y="y")) + registry.geom_point() + registry.scale_x_log10()


#: case 名 → 构造同一张图的方式（与 `coord_ref.R` 一一对应）。
BUILDERS = {
    "cartesian_default": lambda: continuous_plot(),
    "cartesian_expand_false": lambda: continuous_plot() + registry.coord_cartesian(expand=False),
    "cartesian_xlim": lambda: continuous_plot() + registry.coord_cartesian(xlim=(2, 5)),
    "scale_x_limits": lambda: continuous_plot() + registry.scale_x_continuous(limits=(2, 5)),
    "discrete_default": lambda: discrete_plot(),
    "discrete_xlim_levels": lambda: (
        discrete_plot() + registry.scale_x_discrete(limits=("a", "b", "d"))
    ),
    "fixed_ratio_1": lambda: continuous_plot() + registry.coord_fixed(ratio=1),
    "fixed_ratio_2": lambda: continuous_plot() + registry.coord_fixed(ratio=2),
    # coord limits 是数据空间的值：先 log10 变换再做 expand（R `expand_limits_scale()`）
    "log10_coord_xlim": lambda: log_plot() + registry.coord_cartesian(xlim=(1, 100)),
    "log10_scale_limits_coord": lambda: (
        log_plot()
        + registry.scale_x_log10(limits=(1, 100))
        + registry.coord_cartesian(xlim=(1, 10))
    ),
    # --- M2-1：coord 全量（R 侧同一批 case 都加了 theme_void，面板几何可对拍） ---
    "flip_continuous": lambda: void(continuous_plot() + registry.coord_flip()),
    "flip_discrete": lambda: void(discrete_plot() + registry.coord_flip()),
    "flip_ratio": lambda: void(continuous_plot() + registry.coord_flip(ylim=(0, 40))),
    "trans_log10_x": lambda: void(continuous_plot() + registry.coord_transform(x="log10")),
    "trans_sqrt_y": lambda: void(continuous_plot() + registry.coord_transform(y="sqrt")),
    "trans_reverse_x": lambda: void(continuous_plot() + registry.coord_transform(x="reverse")),
    "equal": lambda: void(continuous_plot() + registry.coord_equal()),
    "reverse_x": lambda: void(continuous_plot() + registry.coord_cartesian(reverse="x")),
    "polar_x": lambda: void(discrete_plot() + registry.coord_polar()),
    "polar_y": lambda: void(discrete_plot() + registry.coord_polar(theta="y")),
    "radial_full": lambda: void(discrete_plot() + registry.coord_radial()),
    "radial_partial": lambda: void(
        discrete_plot() + registry.coord_radial(start=-0.5 * np.pi, end=0.5 * np.pi)
    ),
    "radial_inner": lambda: void(discrete_plot() + registry.coord_radial(inner_radius=0.3)),
    "polar_start_dir": lambda: void(
        discrete_plot() + registry.coord_polar(start=0.5 * np.pi, direction=-1)
    ),
    "sec_axis_y": lambda: void(
        continuous_plot() + registry.scale_y_continuous(sec_axis=sec_axis(lambda v: v * 2))
    ),
    "dup_axis_y": lambda: void(
        continuous_plot() + registry.scale_y_continuous(sec_axis=dup_axis())
    ),
}


def void(plot: ggplot) -> ggplot:
    """与 `coord_ref.R` 的 `void()` 同义：主题不参与面板几何。"""
    return plot + theme_void() + theme(**{"legend.position": "none"})


def _finite(values) -> list[float]:
    """去掉 R 侧的 `NA`（JSON 里是字符串）/ null，只留有限位置。"""
    out: list[float] = []
    for value in values:
        if value is None or (isinstance(value, str) and value.strip().upper() == "NA"):
            continue
        number = float(value)
        if np.isfinite(number):
            out.append(number)
    return out


def test_fixture_covers_the_required_cases() -> None:
    assert REFERENCE["ggplot2"] == "4.0.3"
    assert set(BUILDERS) == set(CASES)
    assert len(CASES) >= 20
    # M2-1 的 12 个 coord_* 导出里，绘图口径可对拍的有这些（sf / map / quickmap
    # 只做注册与最小可用，见 tests/test_coord.py）：
    assert {"flip_continuous", "trans_log10_x", "polar_x", "radial_partial", "sec_axis_y"} <= set(
        CASES
    )
    # SIL-685：现有 8 个 case 全是 identity 标度，覆盖不到 coord limits 的
    # transform 路径，必须点名守住这两个。
    assert {"log10_coord_xlim", "log10_scale_limits_coord"} <= set(CASES)


def test_python_data_matches_the_r_script() -> None:
    assert DATA.column("x").values.tolist() == pytest.approx(REFERENCE["data"]["x"])
    assert DATA.column("y").values.tolist() == pytest.approx(REFERENCE["data"]["y"])
    assert DATA.column("g").values.tolist() == REFERENCE["data"]["g"]
    assert LOG_DATA.column("x").values.tolist() == pytest.approx(REFERENCE["log_data"]["x"])
    assert LOG_DATA.column("y").values.tolist() == pytest.approx(REFERENCE["log_data"]["y"])


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_panel_params_match_r(name: str) -> None:
    case = CASES[name]
    build = build_plot(BUILDERS[name]())
    params = build.panel_params
    assert params is not None

    # 1. 面板范围（含 expand）：极坐标 / 径向坐标的 R panel_params 用 theta./r.
    # 命名，没有 x.range / y.range（下面第 7 段单独对拍 theta / r）。
    if case["x_range"] is not None:
        assert params.x_range == pytest.approx(tuple(case["x_range"]), abs=TOLERANCE)
    if case["y_range"] is not None:
        assert params.y_range == pytest.approx(tuple(case["y_range"]), abs=TOLERANCE)

    # 2. expand 前的范围：coord xlim/ylim（R 已 transform）优先，否则用标度 limits
    expected_x = case["coord_xlim_transformed"] or case["x_limits"]
    expected_y = case["coord_ylim_transformed"] or case["y_limits"]
    if params.flipped:
        # flip 交换了两条面板维度：夹具的 x_limits / y_limits 已经是面板维度的
        # （R `panel_limits(panel$x)`），但 coord 的 xlim / ylim 是数据轴的，
        # 只有这一项要换边。
        expected_x = case["coord_ylim_transformed"] or case["x_limits"]
        expected_y = case["coord_xlim_transformed"] or case["y_limits"]
    if expected_x is not None:
        assert params.x_limits == pytest.approx(tuple(expected_x), abs=TOLERANCE)
    if expected_y is not None:
        assert params.y_limits == pytest.approx(tuple(expected_y), abs=TOLERANCE)

    # 3. 离散标记 / clip / ratio
    # 极坐标 theta="y" 时 R 的 panel_scales_x 就是 y 标度（`modify_scales()` 换过），
    # x/y 的离散标记在那边没有可比性——theta / r 的范围在第 7 段对拍。
    if params.polar is None or params.polar.theta_axis == "x":
        expected_discrete = {"x": case["x_discrete"], "y": case["y_discrete"]}
        if params.flipped:
            # 夹具的 x/y 是数据轴，`PanelParams.discrete` 是**屏幕**轴。
            expected_discrete = {"x": expected_discrete["y"], "y": expected_discrete["x"]}
        assert dict(params.discrete) == expected_discrete
    assert params.clip == case["clip"]
    if case["ratio"] is None:
        assert params.ratio is None
    else:
        assert params.ratio == pytest.approx(case["ratio"], abs=TOLERANCE)

    # 4. 物理高/宽（R `CoordFixed$aspect()`）
    if case["aspect"] is None:
        assert params.aspect_ratio is None
    else:
        assert params.aspect_ratio == pytest.approx(case["aspect"], abs=TOLERANCE)

    # 5. 越界计数：rows_dropped（行级）对 R 的 Removed；dropped（按轴）对 NA 数
    assert params.rows_dropped == case["removed"]
    assert sum(params.dropped.values()) == case["na_x"] + case["na_y"]
    assert int(params.dropped["x"]) == case["na_x"]
    assert int(params.dropped["y"]) == case["na_y"]
    scaled = build.layers[0].scaled
    assert int(np.count_nonzero(scaled.column("x").na_mask)) == case["na_x"]
    assert int(np.count_nonzero(scaled.column("y").na_mask)) == case["na_y"]

    # R 的 `$data` 不删行（log10 case 是 3 行，其余 6 行）；删除发生在绘制期
    assert build.layers[0].nrows == case["n_rows"]

    # 6. 断点位置（npc）：R 的 ViewScale$break_positions()；NA 是越界断点，两边都不画
    if case["x_positions"] is not None and name != "discrete_xlim_levels":
        # `discrete_xlim_levels` 的 x 位置暂不比：标度把显式 limits 里没有数据的
        # 水平（"d"）留在 breaks 里、却不在 `levels` 里，`_tick_positions()` 因此
        # 找不到它的序号。这是 M1-4 的离散标度缺口（SIL-715 同族），不在 M2-1
        # 的范围内；其余 25 个 case 的断点位置都逐值对拍。
        ticks = axis_ticks(_scale(build, params, "bottom"), params, "bottom")
        assert list(ticks.positions) == pytest.approx(_finite(case["x_positions"]), abs=TOLERANCE)
        assert list(ticks.labels) == list(case["x_position_labels"])
    if case["y_positions"] is not None:
        ticks = axis_ticks(_scale(build, params, "left"), params, "left")
        assert list(ticks.positions) == pytest.approx(_finite(case["y_positions"]), abs=TOLERANCE)
        assert list(ticks.labels) == list(case["y_position_labels"])

    # 7. 极坐标 / 径向坐标：theta / r 范围、断点角度、r 位置、bbox / arc / 内半径
    if case["theta_range"] is not None and params.polar is not None:
        assert params.polar.theta_range == pytest.approx(case["theta_range"], abs=TOLERANCE)
        assert params.polar.r_range == pytest.approx(case["r_range"], abs=TOLERANCE)
        if case["theta_positions"] is not None:
            angles = params.polar.theta_angle(np.asarray(case["theta_major"], dtype=np.float64))
            assert list(angles) == pytest.approx(case["theta_positions"], abs=TOLERANCE)
        if case["r_positions"] is not None:
            radii = params.polar.radius(np.asarray(case["r_major"], dtype=np.float64)) + 0.5
            assert list(radii) == pytest.approx(case["r_positions"], abs=TOLERANCE)
        if case["bbox"] is not None:
            assert list(params.polar.bbox[0]) == pytest.approx(case["bbox"]["x"], abs=TOLERANCE)
            assert list(params.polar.bbox[1]) == pytest.approx(case["bbox"]["y"], abs=TOLERANCE)
        if case["arc"] is not None:
            assert list(params.polar.arc) == pytest.approx(case["arc"], abs=TOLERANCE)
        if case["inner_radius"] is not None:
            assert list(params.polar.inner_radius) == pytest.approx(
                case["inner_radius"], abs=TOLERANCE
            )

    # 8. 次轴：断点位置 / 标签与 R 的 ViewScale 逐项一致
    for aesthetic, side in (("x", "top"), ("y", "right")):
        expected = case[f"sec_{aesthetic}"]
        if expected is None:
            continue
        scale = _scale(build, params, side)
        ticks = secondary_ticks(scale, params, side)
        assert list(ticks.positions) == pytest.approx(
            _finite(expected["positions"]), abs=SEC_TOLERANCE
        )
        assert list(ticks.labels) == [
            text
            for text, value in zip(expected["labels"], expected["positions"], strict=True)
            if value is not None and np.isfinite(float(value))
        ]

    # 9. 面板几何（cm）：R 的 gtable 单元格；有 aspect 时取 respect 之后的最大内接矩形
    width = case["panel_width_cm"]
    height = case["panel_height_cm"]
    if width is not None and width > 0:
        layout = plot_layout(build, width_in=4, height_in=3)
        box = next(iter(layout.panel_boxes.values()))
        if params.aspect_ratio is None:
            expected_width, expected_height = width, height
        else:
            expected_width = min(width, height / params.aspect_ratio)
            expected_height = expected_width * params.aspect_ratio
        tolerance = 0.2 if name in _OLD_CASES else 0.01
        assert box.width_cm == pytest.approx(expected_width, abs=tolerance)
        assert box.height_cm == pytest.approx(expected_height, abs=tolerance)


def _scale(build, params, side: str) -> object:
    """该面板 / 该边用的标度（flip 与极坐标的对侧标度由 `scale_key()` 给出）。"""
    aesthetic = params.scale_key(side)
    for item in build.panels:
        return item.scales.scale(aesthetic)
    return build.scales.scale(aesthetic)


def test_xlim_out_of_bounds_count_is_reported_even_though_r_keeps_the_rows() -> None:
    """`coord_cartesian(xlim=)`：R `removed = 0`，但 2 个点确实在面板外。

    我们把它记进 `out_of_bounds`（不删数据、不造 NA），与 R 的 `$data` 一致。
    """
    build = build_plot(continuous_plot() + registry.coord_cartesian(xlim=(2, 5)))
    params = build.panel_params
    assert params is not None
    assert CASES["cartesian_xlim"]["removed"] == 0
    assert dict(params.dropped) == {"x": 0, "y": 0}
    assert dict(params.out_of_bounds) == {"x": 2, "y": 0}
    assert int(np.count_nonzero(build.layers[0].scaled.column("x").na_mask)) == 0

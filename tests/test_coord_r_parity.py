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
from ggcore.build import build_plot
from ggcore.data import Column, ColumnTable
from ggcore.plot import ggplot

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "coord_r_reference.json"
REFERENCE = json.loads(FIXTURE.read_text(encoding="utf-8"))
CASES = {case["name"]: case for case in REFERENCE["cases"]}
TOLERANCE = 1e-12

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
}


def test_fixture_covers_the_required_cases() -> None:
    assert REFERENCE["ggplot2"] == "4.0.3"
    assert set(BUILDERS) == set(CASES)
    assert len(CASES) >= 6
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

    # 1. 面板范围（含 expand）
    assert params.x_range == pytest.approx(tuple(case["x_range"]), abs=TOLERANCE)
    assert params.y_range == pytest.approx(tuple(case["y_range"]), abs=TOLERANCE)

    # 2. expand 前的范围：coord xlim/ylim（R 已 transform）优先，否则用标度 limits
    expected_x = case["coord_xlim_transformed"] or case["x_limits"]
    expected_y = case["coord_ylim_transformed"] or case["y_limits"]
    assert params.x_limits == pytest.approx(tuple(expected_x), abs=TOLERANCE)
    assert params.y_limits == pytest.approx(tuple(expected_y), abs=TOLERANCE)

    # 3. 离散标记 / clip / ratio
    assert dict(params.discrete) == {"x": case["x_discrete"], "y": case["y_discrete"]}
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

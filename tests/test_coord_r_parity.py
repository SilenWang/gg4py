"""坐标面板参数与 R ggplot2 4.0.3 的逐值对拍（M1-5）。

夹具由 `pixi run -e refs refs:coord`（`tools/refs/coord_ref.R`）生成，R 与 Python
用同一份 6 行数据。对拍的是：

- `ggplot_build(p)$layout$panel_params[[1]]$x.range` / `y.range`（含 expand）；
- expand 前的范围：连续取 `get_limits()`，离散取 `1..n`；coord `xlim` / `ylim`
  在 R 里只出现在 `coord$limits`，测试用它替换 scale limits 后再比；
- `CoordFixed$aspect()`（物理高/宽）与 `ratio`；
- `clip`、离散标记；
- 越界：`pp$dropped` 对 R 的 "Removed N rows" 与本层 x 的 NA 数。

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


def continuous_plot() -> ggplot:
    return ggplot(DATA, aes(x="x", y="y")) + registry.geom_point()


def discrete_plot() -> ggplot:
    return ggplot(DATA, aes(x="g", y="y")) + registry.geom_point()


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
}


def test_fixture_covers_the_required_cases() -> None:
    assert REFERENCE["ggplot2"] == "4.0.3"
    assert set(BUILDERS) == set(CASES)
    assert len(CASES) >= 6


def test_python_data_matches_the_r_script() -> None:
    assert DATA.column("x").values.tolist() == pytest.approx(REFERENCE["data"]["x"])
    assert DATA.column("y").values.tolist() == pytest.approx(REFERENCE["data"]["y"])
    assert DATA.column("g").values.tolist() == REFERENCE["data"]["g"]


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_panel_params_match_r(name: str) -> None:
    case = CASES[name]
    build = build_plot(BUILDERS[name]())
    params = build.panel_params
    assert params is not None

    # 1. 面板范围（含 expand）
    assert params.x_range == pytest.approx(tuple(case["x_range"]), abs=TOLERANCE)
    assert params.y_range == pytest.approx(tuple(case["y_range"]), abs=TOLERANCE)

    # 2. expand 前的范围：coord xlim/ylim 优先，否则用标度 limits
    expected_x = case["coord_xlim"] or case["x_limits"]
    expected_y = case["coord_ylim"] or case["y_limits"]
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

    # 5. 越界计数：dropped 对 R 的 Removed / NA 数
    assert sum(params.dropped.values()) == case["removed"]
    assert int(params.dropped["x"]) == case["na_x"]
    assert int(params.dropped["y"]) == case["na_y"]
    scaled = build.layers[0].scaled
    assert int(np.count_nonzero(scaled.column("x").na_mask)) == case["na_x"]
    assert int(np.count_nonzero(scaled.column("y").na_mask)) == case["na_y"]

    # R 的 `$data` 不删行（6 行都在）；删除发生在绘制期
    assert build.layers[0].nrows == case["n_rows"] == 6


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

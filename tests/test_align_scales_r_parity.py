"""`align_scales()` 与 aplot 0.3.2 的逐值对拍（SIL-1000）。

夹具 `tests/fixtures/align_scales_r_reference.json` 由
`pixi run -e refs refs:align`（`tools/refs/align_scales_ref.R`）生成：
aplot 0.3.2 + patchwork 1.3.2 + ggplot2 4.0.3，逐 case 跑 `xlim2()` / `ylim2()` /
`adjust_coord()`。CI 不装 R，只读夹具。

对拍口径：

- aplot 的 `xlim2(gg)` 取 `ggfun::xrange(region = "plot")` =
  `panel_params$x$limits`，是**标度空间**的值（log10 下 0..1、reverse 下 -2..-1）；
  这里比 `report.limits[axis].transformed`（同样是标度空间），离散轴比 levels；
- 裁剪量：aplot 侧数 `ggplot_build()` 里由 censor 新产生的 NA（`ggplot_build()`
  不打印 "Removed N rows"）；这里比 `report.clipped` 的 `rows`；
- `coord_flip`：aplot 的 axis 是**视觉**轴，本仓是**数据**轴——同一件事在本仓写作
  `axis="y"`，case 里显式记下这条换算；
- `adjust_coord` 比补出来的 `coord_fixed(ratio=)`。

实现对 aplot 的两处**内部写法**做了等价改写（结果逐值相同，夹具里有断言）：

1. **log10 / reverse**：aplot 把 `panel_params$x$limits`（标度空间，log10 下
   0..1）直接写回 `scale$limits`；gg4py 先反变换回数据空间（1..10）再写回，
   标度会把它再变换一次。两条路径的 `x.range`、breaks、裁剪行数一致。
2. **离散轴**：aplot 的 `set_scale_limits()` 会写 `continuous_limits` 并把
   `expand` 改成 `c(0, 0)`；gg4py 统一 levels 后由 `range_c` 自然重算，
   默认 `expand` 下两者面板范围相同（本夹具的 case 已对拍）。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ggcore.align import align_scales
from ggcore.build import build_plot
from ggcore.coord import coord_from_component
from ggcore.data import Column, ColumnTable
from ggcore.plot import (
    aes,
    coord_fixed,
    coord_flip,
    geom_bar,
    geom_point,
    ggplot,
    scale_x_log10,
    scale_x_reverse,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "align_scales_r_reference.json"
REFERENCE = json.loads(FIXTURE.read_text(encoding="utf-8"))
CASES = {case["name"]: case for case in REFERENCE["cases"]}

#: R 的 `format(digits = 17)` 与 Python 的 float 往返误差。
TOLERANCE = 1e-9


def numeric_table(x: list[float], y: list[float] | None = None) -> ColumnTable:
    if y is None:
        y = list(x)
    return ColumnTable(
        [
            ("x", Column("float", np.array(x, dtype=np.float64))),
            ("y", Column("float", np.array(y, dtype=np.float64))),
        ]
    )


def point(table: ColumnTable) -> ggplot:
    return ggplot(table, aes(x="x", y="y")) + geom_point()


def bar(values: list[str]) -> ggplot:
    return (
        ggplot(ColumnTable([("g", Column("str", np.array(values, dtype=object)))]), aes(x="g"))
        + geom_bar()
    )


def assert_limits(actual: tuple[float, ...], expected: list[float]) -> None:
    assert len(actual) == len(expected)
    for got, want in zip(actual, expected, strict=True):
        assert got == pytest.approx(want, abs=TOLERANCE)


def clip_rows(aligned, plot: int, axis: str) -> int:
    return sum(
        item.rows for item in aligned.report.clipped if item.plot == plot and item.axis == axis
    )


def test_fixture_pins_the_reference_versions() -> None:
    assert REFERENCE["aplot"] == "0.3.2"
    assert REFERENCE["ggplot2"] == "4.0.3"
    assert REFERENCE["patchwork"] == "1.3.2"


def test_continuous_first_matches_aplot() -> None:
    case = CASES["continuous_first"]
    main = point(numeric_table([1.0, 2.0, 3.0]))
    child = point(numeric_table([1.0, 2.0, 4.0, 5.0]))

    aligned = align_scales([main, child], axis="x", limits="first")

    axis = aligned.report.limits["x"]
    assert_limits(axis.transformed, case["main"]["limits"])
    assert_limits(axis.limits, case["aligned"]["limits"])
    assert clip_rows(aligned, 1, "x") == case["removed"] == 2
    # 断点：R 侧的 NA（被 censor 的端点）不参与比较。
    ours = [value for value in build_plot(aligned[1]).scales.breaks("x") if value is not None]
    theirs = [value for value in case["aligned"]["breaks"] if value is not None]
    assert_limits(ours, theirs)


def test_continuous_explicit_matches_aplot() -> None:
    case = CASES["continuous_explicit"]
    main = point(numeric_table([1.0, 2.0, 3.0]))
    child = point(numeric_table([1.0, 2.0, 4.0, 5.0]))

    aligned = align_scales([main, child], axis="x", limits="explicit", x=(-1.0, 6.0))

    axis = aligned.report.limits["x"]
    assert_limits(axis.transformed, case["aligned"]["limits"])
    assert clip_rows(aligned, 1, "x") == case["removed"] == 0
    elems = [value for value in build_plot(aligned[1]).scales.breaks("x") if value is not None]
    theirs = [value for value in case["aligned"]["breaks"] if value is not None]
    assert_limits(elems, theirs)


def test_dual_axis_first_matches_aplot() -> None:
    """双轴同时裁剪：R 的 "Removed N rows" 是 x / y 的行级并集，不是两轴相加。"""
    case = CASES["dual_axis_first"]
    main = point(numeric_table([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]))
    child = point(numeric_table([1.0, 2.0, 4.0, 5.0], [1.0, 5.0, 4.0, 2.0]))

    aligned = align_scales([main, child], axis="xy", limits="first")

    for name in ("x", "y"):
        assert_limits(aligned.report.limits[name].transformed, case["main"][name]["limits"])
        panel = build_plot(aligned[1]).panel_params
        assert_limits(panel.limits[name], case["aligned"][name]["limits"])
        assert_limits(panel.ranges[name], case["aligned"][name]["panel_range"])

    per_axis = {item.axis: item.rows for item in aligned.report.clipped if item.plot == 1}
    assert per_axis == {"x": case["removed_x"], "y": case["removed_y"]}
    assert case["removed_x"] == 2 and case["removed_y"] == 2
    assert aligned.report.clipped_rows == case["removed"] == 3
    assert aligned.report.rows_dropped(1) == case["removed"]
    assert build_plot(aligned[1]).panel_params.rows_dropped == case["removed"]


def test_discrete_first_matches_aplot() -> None:
    case = CASES["discrete_first"]
    main = bar(["a", "b"])
    child = bar(["a", "b", "c"])

    aligned = align_scales([main, child], axis="x", limits="first")

    axis = aligned.report.limits["x"]
    assert axis.discrete is True
    assert list(axis.limits) == case["main"]["limits"]
    assert clip_rows(aligned, 1, "x") == case["removed"] == 1
    breaks = [value for value in build_plot(aligned[1]).scales.breaks("x") if value is not None]
    assert breaks == case["aligned"]["breaks"]


def test_log10_first_matches_aplot() -> None:
    case = CASES["log10_first"]
    main = point(numeric_table([1.0, 10.0])) + scale_x_log10()
    child = point(numeric_table([1.0, 100.0, 1000.0])) + scale_x_log10()

    aligned = align_scales([main, child], axis="x", limits="first")

    axis = aligned.report.limits["x"]
    # aplot 写回的是标度空间（0..1）；我们比同一空间的 transformed。
    assert_limits(axis.transformed, case["main"]["limits"])
    # 写回的是反变换后的数据空间值；标度再变换一次，面板与 aplot 一致。
    assert_limits(axis.limits, (1.0, 10.0))
    assert clip_rows(aligned, 1, "x") == case["removed"] == 2
    assert_limits(build_plot(aligned[0]).panel_params.x_range, case["aligned"]["panel_range"])
    assert_limits(build_plot(aligned[1]).panel_params.x_range, case["aligned"]["panel_range"])


def test_reverse_first_matches_aplot_scale_space_limits() -> None:
    case = CASES["reverse_first"]
    main = point(numeric_table([1.0, 2.0])) + scale_x_reverse()
    child = point(numeric_table([3.0, 4.0])) + scale_x_reverse()

    aligned = align_scales([main, child], axis="x", limits="first")

    axis = aligned.report.limits["x"]
    assert_limits(axis.transformed, case["main"]["limits"])
    assert_limits(axis.limits, (1.0, 2.0))
    assert clip_rows(aligned, 1, "x") == case["removed"] == 2
    # 面板在映射空间（reverse 后）：值逐项相同。ggcore 的 reverse range 保持递减
    # 顺序（坐标自己按 `sorted()` 消费），R 给的是升序，所以先排序再比。
    for plot in aligned:
        assert_limits(
            tuple(sorted(build_plot(plot).panel_params.x_range)),
            case["aligned"]["panel_range"],
        )


def test_date_first_matches_aplot() -> None:
    case = CASES["date_first"]
    days = np.array([18262.0, 18414.0])  # 2020-01-01 / 2020-06-01
    later = np.array([18414.0, 18628.0])  # 2020-06-01 / 2021-01-01
    main = point(
        ColumnTable(
            [("x", Column("date", days.copy())), ("y", Column("float", np.array([1.0, 2.0])))]
        )
    )
    child = point(
        ColumnTable(
            [("x", Column("date", later.copy())), ("y", Column("float", np.array([2.0, 3.0])))]
        )
    )

    aligned = align_scales([main, child], axis="x", limits="first")

    axis = aligned.report.limits["x"]
    assert axis.kind == "date:date"
    assert_limits(axis.transformed, case["main"]["limits"])
    assert clip_rows(aligned, 1, "x") == case["removed"] == 1
    breaks = [value for value in build_plot(aligned[1]).scales.breaks("x") if value is not None]
    theirs = [value for value in case["aligned"]["breaks"] if value is not None]
    assert_limits(breaks, theirs)


def test_coord_flip_case_records_the_data_axis_translation() -> None:
    case = CASES["flip_first"]
    # aplot：xlim2(main) 取视觉 x（= 数据 y）；本仓 axis 指数据轴，所以写 axis="y"。
    assert case["axis"] == "x" and case["prune_axis"] == "y"
    main = point(numeric_table([1.0, 2.0], [10.0, 20.0])) + coord_flip()
    child = point(numeric_table([1.0, 2.0], [5.0, 25.0])) + coord_flip()

    aligned = align_scales([main, child], axis="y", limits="first")

    axis = aligned.report.limits["y"]
    assert_limits(axis.transformed, case["main"]["limits"])
    assert clip_rows(aligned, 1, "y") == case["removed"] == 2
    # 视觉 x 上的刻度（= 数据 y）与 aplot 的 breaks 相同。
    ticks = [value for value in build_plot(aligned[1]).scales.breaks("y") if value is not None]
    theirs = [value for value in case["aligned"]["breaks"] if value is not None]
    assert_limits(ticks, theirs)


def test_adjust_coord_ratio_matches_aplot() -> None:
    case = CASES["adjust_coord_ratio"]
    main = point(numeric_table([0.0, 10.0], [0.0, 5.0])) + coord_fixed()
    child = point(numeric_table([0.0, 10.0], [0.0, 5.0]))

    aligned = align_scales([main, child], axis="xy")

    coord = coord_from_component(aligned[1].coordinates)
    assert getattr(coord, "ratio", None) == pytest.approx(case["ratio"], abs=TOLERANCE)
    assert case["main_was_fixed"] is True

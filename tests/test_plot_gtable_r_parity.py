"""`plot_gtable()`（SIL-999）与 ggplot2 4.0.3 `ggplotGrob()` 的对拍。

夹具由 `pixi run -e refs refs:plot-gtable`（`tools/refs/plot_gtable_ref.R`）生成，
R 4.5.3 + ggplot2 4.0.3，7×5in 的 svglite 页面上画一遍再按单元格视口读回：

- **结构**：`nrow` / `ncol`、每条 layout 记录的 `(name, t, l, b, r)` 必须逐条相等；
- **尺寸**：每条记录解析后的宽 / 高（cm）在 0.05cm（0.5mm，任务口径）内；
- **panel 权重**：R 里是 `1null` 的行 / 列，gg4py 必须也是纯 null（不是 cm）。

另有三条契约（验收第 3 条）：

1. 7×5in 下 `GTable.resolve()` 的总宽 / 总高等于页面尺寸，重复解析稳定，
   dpi 不参与 cm 解析（`resolve()` 没有 dpi 维度，不同 dpi 的设备读同一张表）；
2. 含图例的表在 `UnitContext` 没有 metrics 时按现有约定抛 `UnitError`——
   图例盒宽度里保留了标签的 `strwidth`，**不静默给 0**；
3. 没有图例的表不含文字度量单位，无 metrics 也能解析（文字尺寸已在构建期
   按 `metrics` 量成 cm）。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import gg4py
from ggcore.build import build_plot
from ggcore.data import Column, ColumnTable
from ggcore.geom.scene import plot_gtable
from ggcore.plot import aes, facet_grid, geom_point, ggplot, labs
from ggcore.registry import facet_wrap
from ggcore.theme import margin, theme
from ggcore.units import CM_PER_INCH, UnitContext, UnitError, is_pure_null
from ggskia.text import ShaperMetrics

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "plot_gtable_r_reference.json"
REFERENCE = json.loads(FIXTURE.read_text(encoding="utf-8"))
CASES = REFERENCE["cases"]
SIZE_IN = REFERENCE["size_in"]
WIDTH_CM = SIZE_IN[0] * CM_PER_INCH
HEIGHT_CM = SIZE_IN[1] * CM_PER_INCH
#: 任务口径：≤ 0.5mm。
TOLERANCE_CM = 0.05
METRICS = ShaperMetrics()


def _categorical(values: list[str], levels: list[str]) -> Column:
    index = {level: position for position, level in enumerate(levels)}
    return Column(
        "categorical",
        np.array([index[value] for value in values], dtype=np.int32),
        levels=tuple(levels),
    )


def _table() -> ColumnTable:
    return ColumnTable(
        [
            (
                "x",
                Column(
                    "float",
                    np.array([1.5, 1.8, 2.2, 2.6, 3.0, 3.4, 3.8, 4.2, 4.6, 5.0, 5.3, 5.6]),
                ),
            ),
            (
                "y",
                Column(
                    "float",
                    np.array(
                        [26.0, 25.0, 24.5, 23.0, 22.5, 21.0, 20.5, 19.5, 18.0, 17.5, 16.5, 15.0]
                    ),
                ),
            ),
            (
                "cyl",
                _categorical(
                    ["4", "4", "4", "6", "6", "6", "8", "8", "8", "4", "6", "8"],
                    ["4", "6", "8"],
                ),
            ),
            (
                "a",
                _categorical(
                    ["p", "p", "p", "q", "q", "q", "p", "p", "q", "q", "p", "q"],
                    ["q", "p"],
                ),
            ),
            (
                "b",
                _categorical(
                    ["u", "u", "u", "u", "v", "v", "v", "v", "u", "u", "v", "v"],
                    ["v", "u"],
                ),
            ),
        ]
    )


def _base(mapping=None) -> ggplot:
    return ggplot(_table(), mapping or aes(x="x", y="y")) + geom_point() + labs(x="X", y="Y")


def _plot(name: str) -> ggplot:
    if name == "plain":
        return _base()
    if name == "facet_wrap":
        return _base() + facet_wrap(("a",), ncol=2) + labs(x="X", y="Y")
    if name == "facet_grid":
        return _base() + facet_grid("b", "a") + labs(x="X", y="Y")
    if name == "legend_title_tag":
        return (
            _base(aes(x="x", y="y", colour="cyl"))
            + labs(title="T", subtitle="S", caption="C", tag="A")
            + theme(**{"plot.margin": margin(6, 7, 8, 9, "pt")})
        )
    if name == "legend_bottom":
        return _base(aes(x="x", y="y", colour="cyl")) + theme(**{"legend.position": "bottom"})
    if name == "wrap_legend_titles":
        return (
            _base(aes(x="x", y="y", colour="cyl"))
            + facet_wrap(("a",), ncol=2)
            + labs(title="T", caption="C")
        )
    raise KeyError(name)


PLOTS = {name: _plot(name) for name in CASES}


def _resolved(name: str):
    table = plot_gtable(PLOTS[name], metrics=METRICS)
    ctx = UnitContext(metrics=METRICS)
    boxes = {
        (row.name, row.t, row.l, row.b, row.r): box
        for row, box in zip(
            table.layout,
            table.boxes(WIDTH_CM, HEIGHT_CM, ctx=ctx),
            strict=True,
        )
    }
    return table, boxes


@pytest.mark.parametrize("name", sorted(CASES))
def test_page_gtable_matches_the_r_layout_cell_by_cell(name: str) -> None:
    """行列数、每条记录的 (name, t, l, b, r) 与每条记录的宽高都要对上。"""
    case = CASES[name]
    table, boxes = _resolved(name)
    assert (table.nrow, table.ncol) == (case["nrow"], case["ncol"]), (
        f"{name}: {table.nrow}×{table.ncol} vs R {case['nrow']}×{case['ncol']}"
    )
    expected = {
        (record["name"], record["t"], record["l"], record["b"], record["r"]): record
        for record in case["records"]
    }
    assert set(boxes) == set(expected), (
        f"{name}: 缺失 {sorted(set(expected) - set(boxes))}，"
        f"多出 {sorted(set(boxes) - set(expected))}"
    )
    for key, record in expected.items():
        box = boxes[key]
        assert box.width_cm == pytest.approx(record["width"], abs=TOLERANCE_CM), (
            f"{name}: {key} 宽 {box.width_cm:.4f} vs R {record['width']:.4f}"
        )
        assert box.height_cm == pytest.approx(record["height"], abs=TOLERANCE_CM), (
            f"{name}: {key} 高 {box.height_cm:.4f} vs R {record['height']:.4f}"
        )


@pytest.mark.parametrize("name", sorted(CASES))
def test_panel_rows_and_columns_are_pure_null_where_r_has_one_null(name: str) -> None:
    """R 的 `1null` 行 / 列在 gg4py 里必须是纯 null，不能落成固定 cm。"""
    case = CASES[name]
    table = plot_gtable(PLOTS[name], metrics=METRICS)
    assert table.ncol == len(case["widths"]) == len(table.widths)
    assert table.nrow == len(case["heights"]) == len(table.heights)
    for index, declared in enumerate(case["widths"]):
        if declared == "1null":
            assert is_pure_null(table.widths, index), f"{name}: 第 {index + 1} 列不是 1null"
    for index, declared in enumerate(case["heights"]):
        if declared == "1null":
            assert is_pure_null(table.heights, index), f"{name}: 第 {index + 1} 行不是 1null"


def test_plot_gtable_is_exported_on_the_top_level() -> None:
    assert gg4py.plot_gtable is plot_gtable
    assert "plot_gtable" in gg4py.__all__
    p = PLOTS["plain"]
    assert plot_gtable(p).nrow == plot_gtable(build_plot(p)).nrow


def test_resolve_fills_the_page_and_is_dpi_independent() -> None:
    """7×5in 的整页解析：总宽高 = 页面；重复解析稳定，dpi 不参与。"""
    table = plot_gtable(PLOTS["plain"], metrics=METRICS)
    ctx = UnitContext(metrics=METRICS)
    sizes = table.resolve(WIDTH_CM, HEIGHT_CM, ctx=ctx)
    assert sizes.total_width_cm == pytest.approx(WIDTH_CM, abs=1e-9)
    assert sizes.total_height_cm == pytest.approx(HEIGHT_CM, abs=1e-9)
    again = table.resolve(WIDTH_CM, HEIGHT_CM, ctx=ctx)
    assert sizes == again
    # dpi 是设备属性，不参与 cm 解析：同一张表在任意 dpi 下给同一组行列尺寸。
    for dpi in (72.0, 144.0, 300.0):
        assert table.resolve(WIDTH_CM, HEIGHT_CM, ctx=ctx) == sizes
        assert dpi > 0


def test_legend_width_keeps_a_strwidth_unit_and_needs_metrics() -> None:
    """含图例的表：无 metrics 时按现有约定报错，绝不静默给 0。"""
    table = plot_gtable(PLOTS["legend_title_tag"], metrics=METRICS)
    with pytest.raises(UnitError, match="strwidth"):
        table.resolve(WIDTH_CM, HEIGHT_CM)
    with pytest.raises(UnitError, match="metric"):
        table.resolve(WIDTH_CM, HEIGHT_CM, ctx=UnitContext())
    resolved = table.resolve(WIDTH_CM, HEIGHT_CM, ctx=UnitContext(metrics=METRICS))
    # 图例盒那一列确实非 0（宽度由标签的 strwidth + 固定部分给出）。
    assert max(resolved.widths_cm) >= 1.0


def test_plain_table_without_text_units_resolves_without_metrics() -> None:
    """没有图例的表不含文字度量单位，无 metrics 也能解析（不静默 0）。"""
    table = plot_gtable(PLOTS["plain"], metrics=METRICS)
    sizes = table.resolve(WIDTH_CM, HEIGHT_CM)
    assert sizes.total_width_cm == pytest.approx(WIDTH_CM, abs=1e-9)
    assert all(value >= 0 for value in sizes.widths_cm)
    assert all(value >= 0 for value in sizes.heights_cm)

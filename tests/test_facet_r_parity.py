"""分面与 R ggplot2 4.0.3 的逐值对拍（M1-6）。

夹具由 `pixi run -e refs refs:facet`（`tools/refs/facet_ref.R`）生成，R 与
Python 用同一份 8 行数据（factor levels 故意与出现顺序不同）。对拍的是：

- `ggplot_build(p)$layout$layout` 的 PANEL / ROW / COL / SCALE_X / SCALE_Y
  与分面变量；
- `panel_params[[i]]$x.range` / `y.range`（含 expand，free scales 逐面板）；
- `ggplotGrob(p)` 的 panel 宽高单位（`1null`）、panel / strip 名字，
  以及 strip 的行高 / 列宽（cm，容差 2%：M1-6 用 0.955em 近似 `stringHeight`，
  M1-7 接真实文字度量后收紧）。

数值断言只认夹具，不重算公式。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pytest

from ggcore import registry
from ggcore.aes import aes
from ggcore.build import build_plot
from ggcore.data import Column, ColumnTable
from ggcore.plot import ggplot

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "facet_r_reference.json"
REFERENCE = json.loads(FIXTURE.read_text(encoding="utf-8"))
CASES = {case["name"]: case for case in REFERENCE["cases"]}
TOLERANCE = 1e-12


def categorical(values: list[str], levels: list[str]) -> Column:
    index = {level: position for position, level in enumerate(levels)}
    return Column(
        "categorical",
        np.array([index[value] for value in values], dtype=np.int32),
        levels=tuple(levels),
    )


DATA = ColumnTable(
    [
        ("x", Column("float", np.array(REFERENCE["data"]["x"], dtype=np.float64))),
        ("y", Column("float", np.array(REFERENCE["data"]["y"], dtype=np.float64))),
        ("a", categorical(REFERENCE["data"]["a"], REFERENCE["data"]["a_levels"])),
        ("b", categorical(REFERENCE["data"]["b"], REFERENCE["data"]["b_levels"])),
        ("c", categorical(REFERENCE["data"]["c"], REFERENCE["data"]["c_levels"])),
    ]
)


def base_plot() -> ggplot:
    return ggplot(DATA, aes(x="x", y="y")) + registry.geom_point()


BUILDERS = {
    "wrap_ncol2": lambda: base_plot() + registry.facet_wrap(("a",), ncol=2),
    "wrap_as_table_false": lambda: (
        base_plot() + registry.facet_wrap(("c",), ncol=2, as_table=False)
    ),
    "grid_2x2": lambda: base_plot() + registry.facet_grid(("b",), ("a",)),
    "grid_as_table_false": lambda: (
        base_plot() + registry.facet_grid(("b",), ("a",), as_table=False)
    ),
    "grid_free": lambda: base_plot() + registry.facet_grid(("b",), ("a",), scales="free"),
    "wrap_free": lambda: base_plot() + registry.facet_wrap(("a",), ncol=2, scales="free"),
}


def _records(build) -> list[dict[str, object]]:
    layout = build.layout
    assert layout is not None
    out: list[dict[str, object]] = []
    for index in range(layout.table.nrows):
        record: dict[str, object] = {}
        for name in layout.table.names:
            value = layout.table.column(name).values[index]
            record[name] = value.item() if hasattr(value, "item") else value
        out.append(record)
    return out


def _cm(text: str) -> float:
    match = re.fullmatch(r"([0-9.eE+-]+)cm", text)
    assert match is not None, text
    return float(match.group(1))


def _as_list(value: object) -> list[object]:
    """jsonlite 的 `auto_unbox` 会把长度 1 的数组写成标量。"""
    return value if isinstance(value, list) else [value]


def test_fixture_covers_the_required_cases() -> None:
    assert REFERENCE["ggplot2"] == "4.0.3"
    assert set(BUILDERS) == set(CASES)
    assert {"wrap_ncol2", "grid_2x2", "grid_as_table_false", "grid_free"} <= set(CASES)
    assert DATA.column("a").levels == tuple(REFERENCE["data"]["a_levels"])


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_layout_matches_r(name: str) -> None:
    build = build_plot(BUILDERS[name]())
    assert _records(build) == CASES[name]["layout"]


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_panel_ranges_match_r(name: str) -> None:
    build = build_plot(BUILDERS[name]())
    expected = CASES[name]["panels"]
    assert [panel.panel for panel in build.panels] == [item["PANEL"] for item in expected]
    for panel, case in zip(build.panels, expected, strict=True):
        assert panel.panel_params.x_range == pytest.approx(tuple(case["x_range"]), abs=TOLERANCE)
        assert panel.panel_params.y_range == pytest.approx(tuple(case["y_range"]), abs=TOLERANCE)


def test_free_grid_has_four_distinct_combinations() -> None:
    """2×2 自由刻度：x 按列、y 按行，至少三个面板互不相同（验收口径）。"""
    build = build_plot(BUILDERS["grid_free"]())
    ranges = {(panel.panel_params.x_range, panel.panel_params.y_range) for panel in build.panels}
    assert len(ranges) == 4
    assert len({panel.panel_params.x_range for panel in build.panels}) == 2
    assert len({panel.panel_params.y_range for panel in build.panels}) == 2


@pytest.mark.parametrize("name", ["wrap_ncol2", "grid_2x2"])
def test_gtable_panel_units_match_r(name: str) -> None:
    build = build_plot(BUILDERS[name]())
    table = build.facet_table()
    expected = CASES[name]["gtable"]

    columns = sorted({left for _, _, left, _, _ in table.panels})
    rows = sorted({top for _, top, _, _, _ in table.panels})
    assert [str(table.gtable.widths[column - 1]) for column in columns] == _as_list(
        expected["panel_columns"]
    )
    assert [str(table.gtable.heights[row - 1]) for row in rows] == _as_list(expected["panel_rows"])
    assert (
        sorted(row.name for row in table.gtable.layout if row.name.startswith("panel"))
        == (expected["panel_names"])
    )
    assert (
        sorted(row.name for row in table.gtable.layout if row.name.startswith("strip"))
        == (expected["strip_names"])
    )


@pytest.mark.parametrize("name", ["wrap_ncol2", "grid_2x2"])
def test_gtable_strip_extent_matches_r_within_two_percent(name: str) -> None:
    build = build_plot(BUILDERS[name]())
    table = build.facet_table()
    for strip in CASES[name]["gtable"]["strip_sizes"]:
        if strip["name"].startswith("strip-t"):
            expected = _cm(strip["height"])
        else:
            expected = _cm(strip["width"])
        assert table.strip_height_cm == pytest.approx(expected, rel=0.02)

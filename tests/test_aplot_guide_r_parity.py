"""aplot 0.3.2 guide area / guide layout 的结构对拍（SIL-1003）。

夹具由 `pixi run -e refs refs:aplot-guide` 生成。跨引擎字体尺寸不同，所以
比较 layout 矩阵、锚点和 guide-box 的行列关系；guide-cell 宽度按同面板宽度
的相对值比较。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import gg4py
from ggcore import composition
from ggcore.plot import aes, geom_point, ggplot
from ggcore.units import UnitContext
from ggio.frame import from_dict
from ggskia.text import ShaperMetrics

FIXTURE = Path(__file__).parent / "fixtures" / "aplot_guide_r_reference.json"
METRICS = ShaperMetrics()
CTX = UnitContext(metrics=METRICS)


def _reference() -> dict[str, Any]:
    assert FIXTURE.exists(), "缺少 R 夹具：先跑 `pixi run -e refs refs:aplot-guide`"
    return json.loads(FIXTURE.read_text())


def _legend_plot() -> ggplot:
    values = from_dict(
        {
            "x": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "y": [2.0, 4.0, 3.0, 5.0, 6.0, 3.0],
            "g": ["a", "b", "a", "b", "a", "b"],
            "h": ["c", "c", "d", "d", "c", "d"],
            "s": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        }
    )
    return (
        ggplot(
            values,
            aes(x="x", y="y", colour="g", shape="h", size="s"),
        )
        + geom_point()
    )


def _cell_width(table: Any, row: Any) -> float:
    sizes = table.resolve(7.0 * 2.54, 5.0 * 2.54, ctx=CTX)
    return sum(sizes.widths_cm[row.l - 1 : row.r])


def test_fixture_is_aplot_0_3_2() -> None:
    assert _reference()["aplot"] == "0.3.2"
    assert _reference()["patchwork"] == "1.3.2"
    assert _reference()["ggplot2"] == "4.0.3"


def test_side_strip_matches_aplot_relative_rectangle() -> None:
    ref = _reference()["side_right"]
    combined = gg4py.set_guide_area(
        gg4py.wrap_plots(_legend_plot(), _legend_plot(), ncol=2, guides="collect"),
        "right",
    )
    table = combined.gtable(metrics=METRICS, width_in=7.0, height_in=5.0)
    guide = next(row for row in table.layout if row.name == "panel-area-guide")
    panel = next(row for row in table.layout if row.name == "panel-area-1-1")
    ratio = _cell_width(table, guide) / _cell_width(table, panel)
    assert ratio == pytest.approx(ref["width_to_panel"], abs=1e-9)
    assert ref["mode"] == "side"
    assert ref["strip_width"] == pytest.approx(0.2)


def test_corner_anchor_matches_aplot_layout_rewrite() -> None:
    ref = _reference()["corner_bottom_right"]
    combined = gg4py.set_guide_area(
        gg4py.wrap_plots(_legend_plot(), _legend_plot(), _legend_plot(), ncol=2, guides="collect"),
        "bottom-right",
    )
    units = composition._build_units(combined, metrics=METRICS)
    assert units.guide is not None
    anchor_row = (units.guide.area[0] - composition.PANEL_ROW) // composition.TABLE_ROWS + 1
    anchor_col = (units.guide.area[1] - composition.PANEL_COL) // composition.TABLE_COLS + 1
    assert (anchor_row, anchor_col) == (ref["row"], ref["col"])
    assert ref["mode"] == "corner"

    table = combined.gtable(metrics=METRICS, width_in=7.0, height_in=5.0)
    guide = next(row for row in table.layout if row.name == "panel-area-guide")
    panel = next(row for row in table.layout if row.name == "panel-area-1-1")
    assert _cell_width(table, guide) / _cell_width(table, panel) == pytest.approx(
        ref["width_to_panel"],
        abs=1e-9,
    )


def test_guide_box_grid_matches_aplot_guides_ncol() -> None:
    ref = _reference()["guide_box"]
    combined = gg4py.set_guide_layout(
        gg4py.wrap_plots(_legend_plot(), guides="collect"),
        legend_ncol=ref["legend_ncol"],
        legend_byrow=ref["legend_byrow"],
        legend_direction=ref["legend_direction"],
        legend_keywidth=ref["legend_keywidth_mm"],
        legend_keyheight=ref["legend_keyheight_mm"],
        legend_spacing_x=ref["legend_spacing_x_mm"],
        legend_spacing_y=ref["legend_spacing_y_mm"],
        guides_ncol=ref["guides_ncol"],
        guides_direction=ref["guides_direction"],
    )
    units = composition._build_units(combined, metrics=METRICS)
    assert units.guide is not None
    assert len(units.guide.entries) == ref["count"]
    assert len(units.guide.layout.col_widths_cm) == ref["ncol"] * 2 + 1
    assert len(units.guide.layout.row_heights_cm) == ref["nrow"] * 2 + 1
    assert units.guide.layout.cells == tuple(zip(ref["row"], ref["col"], strict=True))


def test_side_strip_and_guide_grid_are_aplot_only_extensions() -> None:
    """patchwork 的单格 guide_area 不会扩列，collect 也不会排多列 guide。"""
    patchwork_units = composition._build_units(
        gg4py.wrap_plots(_legend_plot(), _legend_plot(), ncol=2, guides="collect"),
        metrics=METRICS,
    )
    aplot_units = composition._build_units(
        gg4py.set_guide_area(
            gg4py.wrap_plots(_legend_plot(), _legend_plot(), ncol=2, guides="collect"),
            "right",
        ),
        metrics=METRICS,
    )
    assert patchwork_units.ncol == 2
    assert aplot_units.ncol == 3

    default_box = composition._build_units(
        gg4py.wrap_plots(_legend_plot(), guides="collect"),
        metrics=METRICS,
    ).guide
    grid_box = composition._build_units(
        gg4py.set_guide_layout(
            gg4py.wrap_plots(_legend_plot(), guides="collect"),
            guides_ncol=2,
        ),
        metrics=METRICS,
    ).guide
    assert default_box is not None and grid_box is not None
    assert len(default_box.layout.col_widths_cm) == 3
    assert len(grid_box.layout.col_widths_cm) == 5

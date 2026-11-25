"""aplot 0.3.2 panel spacing / insert_* 的结构对拍（SIL-1004）。

夹具 `tests/fixtures/aplot_spacing_r_reference.json` 由 `pixi run -e refs
refs:aplot-spacing`（`tools/refs/aplot_spacing_ref.R`）生成，记录：

- `panel_spacing`：aplot `.compute_panel_margins()` 的每格 `(t, r, b, l)` 毫米值，
  以及 spacing = 0 / 10 时 2×2 组合渲染后的 panel 矩形（用增量比较，字体无关）；
- `insert_*`：aplot 自己的 layout 矩阵、width / height 权重、main row / col，外加
  渲染后的 panel 矩形。

跨引擎的绝对 pt 不逐值比较；比较的是 aplot 的真实 spec（layout / 权重 / margin）
与渲染后的关系（顺序、等宽等高、宽高比、spacing 增量）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

import gg4py
from ggcore import composition
from ggcore.composition import Patchwork
from ggcore.plot import aes, geom_point, ggplot
from ggcore.theme import element_rect, theme
from ggcore.units import UnitContext
from ggio.frame import from_dict
from ggskia.text import ShaperMetrics

FIXTURE = Path(__file__).parent / "fixtures" / "aplot_spacing_r_reference.json"
METRICS = ShaperMetrics()
CTX = UnitContext(metrics=METRICS)
MM_TO_PT = 72.0 / 25.4

COLOURS = ("#CC0000", "#00CC00", "#0000CC", "#CCCC00")


def _reference() -> dict[str, Any]:
    assert FIXTURE.exists(), "缺少 R 夹具：先跑 `pixi run -e refs refs:aplot-spacing`"
    return json.loads(FIXTURE.read_text())


def _plots(count: int) -> list[ggplot]:
    values = from_dict(
        {
            "x": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "y": [2.0, 4.0, 3.0, 5.0, 6.0, 3.0],
        }
    )
    return [
        ggplot(values, aes(x="x", y="y"))
        + geom_point()
        + theme(**{"panel.background": element_rect(fill=COLOURS[index], colour=None)})
        for index in range(count)
    ]


def _patchwork_from_layout(layout: list[list[Any]]) -> Patchwork:
    """夹具的 layout（行 → id / None）→ 本仓的显式 design（按 plot id 顺序）。"""
    cells: dict[int, tuple[int, int, int, int]] = {}
    for row, entries in enumerate(layout, start=1):
        for col, value in enumerate(entries, start=1):
            if value is not None:
                cells[int(value)] = (row, col, row, col)
    ids = sorted(cells)
    assert ids == list(range(1, len(ids) + 1))
    return Patchwork(
        plots=tuple(_plots(len(ids))),
        design=tuple(cells[value] for value in ids),
    )


def _layout_matrix(patchwork: Patchwork) -> list[list[Any]]:
    areas, nrow, ncol = composition._grid_areas(patchwork)
    grid: list[list[Any]] = [[None] * ncol for _ in range(nrow)]
    for index, (t, left, _b, _r) in enumerate(areas, start=1):
        assert grid[t - 1][left - 1] is None
        grid[t - 1][left - 1] = index
    return grid


def _margins_mm(patchwork: Patchwork) -> list[tuple[float, float, float, float]]:
    sheets = [
        composition._sheet_plan(plot, METRICS, parent_guides="auto")[0] for plot in patchwork.plots
    ]
    areas, _nrow, _ncol = composition._grid_areas(patchwork)
    applied = composition._apply_panel_spacing(sheets, areas, patchwork.panel_spacing)
    out: list[tuple[float, float, float, float]] = []
    for sheet in applied:
        top = composition._cm(sheet.heights[0], CTX, axis="y")
        bottom = composition._cm(sheet.heights[-1], CTX, axis="y")
        left = composition._cm(sheet.widths[0], CTX, axis="x")
        right = composition._cm(sheet.widths[-1], CTX, axis="x")
        out.append(
            (
                float(np.asarray(top).sum()) * 10.0,
                float(np.asarray(right).sum()) * 10.0,
                float(np.asarray(bottom).sum()) * 10.0,
                float(np.asarray(left).sum()) * 10.0,
            )
        )
    return out


def _panel_boxes(patchwork: Patchwork) -> dict[int, tuple[float, float, float, float]]:
    """`{plot id: (x, y, w, h)}`（pt，y 向上）。"""
    table = patchwork.gtable(metrics=METRICS, width_in=7.0, height_in=5.0)
    sizes = table.resolve(7.0 * 2.54, 5.0 * 2.54, ctx=CTX)
    total_height = sum(sizes.heights_cm)
    boxes: dict[int, tuple[float, float, float, float]] = {}
    for row in table.layout:
        if not row.name.startswith("panel-area-"):
            continue
        if row.name == "panel-area-guide":
            continue
        row_index, col_index = (int(part) for part in row.name[len("panel-area-") :].split("-"))
        area = composition._grid_areas(patchwork)[0]
        plot_id = next(
            index
            for index, (t, left, _b, _r) in enumerate(area, start=1)
            if (t, left) == (row_index, col_index)
        )
        boxes[plot_id] = (
            sum(sizes.widths_cm[: row.l - 1]) * 72.0 / 2.54,
            (total_height - sum(sizes.heights_cm[: row.t])) * 72.0 / 2.54,
            sizes.widths_cm[row.l - 1] * 72.0 / 2.54,
            sizes.heights_cm[row.t - 1] * 72.0 / 2.54,
        )
    return boxes


def test_fixture_is_aplot_0_3_2() -> None:
    reference = _reference()
    assert reference["aplot"] == "0.3.2"
    assert reference["patchwork"] == "1.3.2"
    assert reference["ggplot2"] == "4.0.3"


def test_panel_spacing_margins_match_aplot() -> None:
    reference = _reference()
    for name, case in reference["spacing"].items():
        patchwork = _patchwork_from_layout(case["layout"])
        if case["spacing"] == "asis":
            # `asis` 不覆盖子图自己的 plot.margin；夹具的 margins 全是 null。
            assert all(margin is None for margin in case["margins"])
            asis = _margins_mm(gg4py.set_panel_spacing(patchwork, "asis"))
            plain = _margins_mm(patchwork)
            for got, expected in zip(asis, plain, strict=True):
                assert got == pytest.approx(expected)
            continue
        spacing = float(case["spacing"])
        got = _margins_mm(gg4py.set_panel_spacing(patchwork, spacing))
        assert len(got) == len(case["margins"]), name
        for index, (actual, expected) in enumerate(zip(got, case["margins"], strict=True)):
            assert actual == pytest.approx(
                (expected["t"], expected["r"], expected["b"], expected["l"])
            ), f"{name} id={index + 1}"


def test_panel_spacing_render_delta_matches_aplot() -> None:
    """spacing = 0 → 10 的 panel 增量：内部边 +10mm，panel 宽 / 高各少 5mm。"""
    reference = _reference()
    zero_r = {item["fill"]: item for item in reference["spacing_panels"]["zero"]}
    ten_r = {item["fill"]: item for item in reference["spacing_panels"]["ten"]}

    def h_gap(panels: dict[str, dict[str, float]], left: str, right: str) -> float:
        a, b = panels[left], panels[right]
        return b["x"] - (a["x"] + a["w"])

    def v_gap(panels: dict[str, dict[str, float]], top: str, bottom: str) -> float:
        a, b = panels[top], panels[bottom]
        return b["y"] - (a["y"] + a["h"])

    red, green = COLOURS[0], COLOURS[1]
    blue = COLOURS[2]
    r_h_delta = h_gap(ten_r, red, green) - h_gap(zero_r, red, green)
    r_v_delta = v_gap(ten_r, red, blue) - v_gap(zero_r, red, blue)
    assert r_h_delta == pytest.approx(10.0 * MM_TO_PT, abs=0.15)
    assert r_v_delta == pytest.approx(10.0 * MM_TO_PT, abs=0.15)

    patchwork = _patchwork_from_layout(reference["spacing"]["grid_2x2_10"]["layout"])
    zero = _panel_boxes(gg4py.set_panel_spacing(patchwork, 0))
    ten = _panel_boxes(gg4py.set_panel_spacing(patchwork, 10))

    def our_h_gap(boxes: dict[int, tuple[float, float, float, float]]) -> float:
        a, b = boxes[1], boxes[2]
        return b[0] - (a[0] + a[2])

    def our_v_gap(boxes: dict[int, tuple[float, float, float, float]]) -> float:
        a, b = boxes[1], boxes[3]
        return a[1] - (b[1] + b[3])

    assert our_h_gap(ten) - our_h_gap(zero) == pytest.approx(r_h_delta, abs=0.02)
    assert our_v_gap(ten) - our_v_gap(zero) == pytest.approx(r_v_delta, abs=0.02)
    # 外沿（没有邻居的一侧）的 panel 边不动。
    assert ten[1][0] == pytest.approx(zero[1][0], abs=1e-9)
    assert ten[3][1] == pytest.approx(zero[3][1], abs=1e-9)


def _insert_cases() -> dict[str, Patchwork]:
    base = _plots(1)[0]
    two_rows = gg4py.insert_bottom(base, _plots(1)[0])
    two_cols = gg4py.insert_right(base, _plots(1)[0])
    return {
        "left_single_w2": gg4py.insert_left(base, _plots(1)[0], width=2),
        "right_single_w3": gg4py.insert_right(base, _plots(1)[0], width=3),
        "top_single_h2": gg4py.insert_top(base, _plots(1)[0], height=2),
        "bottom_single_h2": gg4py.insert_bottom(base, _plots(1)[0], height=2),
        "left_two_rows": gg4py.insert_left(two_rows, _plots(1)[0]),
        "top_two_cols": gg4py.insert_top(two_cols, _plots(1)[0], height=2),
        "left_then_bottom": gg4py.insert_bottom(
            gg4py.insert_left(base, _plots(1)[0], width=2), _plots(1)[0], height=3
        ),
        "right_then_top": gg4py.insert_top(
            gg4py.insert_right(base, _plots(1)[0], width=2), _plots(1)[0], height=3
        ),
    }


def test_insert_layout_and_weights_match_aplot() -> None:
    reference = _reference()
    cases = _insert_cases()
    assert set(cases) == set(reference["inserts"])
    for name, expected in reference["inserts"].items():
        combined = cases[name]
        areas, nrow, ncol = composition._grid_areas(combined)
        assert _layout_matrix(combined) == expected["layout"], name
        assert (nrow, ncol) == (len(expected["layout"]), len(expected["layout"][0])), name
        # main 是第一张图（plot id 1）的格子。
        assert (areas[0][0], areas[0][1]) == (expected["main_row"], expected["main_col"]), name
        expected_width = tuple(float(value) for value in np.atleast_1d(expected["width"]))
        expected_height = tuple(float(value) for value in np.atleast_1d(expected["height"]))
        assert combined.layout.widths == pytest.approx(expected_width), name
        assert combined.layout.heights == pytest.approx(expected_height), name


def test_insert_panel_relations_match_aplot() -> None:
    """渲染后的 panel 关系：位置顺序 + 等宽等高关系 + 宽高比，与 R 逐对一致。"""
    reference = _reference()
    cases = _insert_cases()
    fill_to_id = {fill: index + 1 for index, fill in enumerate(COLOURS)}

    def r_box(item: dict[str, float]) -> tuple[float, float, float, float]:
        """R 的 SVG 坐标（y 向下，页面 5in = 360pt）→ 页面 y 向上。"""
        return (item["x"], 360.0 - (item["y"] + item["h"]), item["w"], item["h"])

    for name, expected in reference["inserts"].items():
        r_panels = {fill_to_id[item["fill"]]: r_box(item) for item in expected["panels"]}
        assert set(r_panels) == set(range(1, len(expected["panels"]) + 1))
        ours = _panel_boxes(cases[name])
        assert set(ours) == set(r_panels), name

        for left_id in r_panels:
            for right_id in r_panels:
                if left_id >= right_id:
                    continue
                a_r, b_r = r_panels[left_id], r_panels[right_id]
                a_o, b_o = ours[left_id], ours[right_id]
                # 位置顺序（x / y）一致（R 已换到 y 向上）。
                assert (a_r[0] < b_r[0]) == (a_o[0] < b_o[0]), (name, left_id, right_id)
                assert (a_r[1] < b_r[1]) == (a_o[1] < b_o[1]), (name, left_id, right_id)
                # 宽度 / 高度比一致（panel 尺寸就是 null 权重，字体无关）。
                # SVG 的 rect 坐标有 ~0.02pt 的舍入，比值用 1e-3 的相对容差。
                assert (a_o[2] / b_o[2]) == pytest.approx(a_r[2] / b_r[2], rel=1e-3), (
                    name,
                    left_id,
                    right_id,
                )
                assert (a_o[3] / b_o[3]) == pytest.approx(a_r[3] / b_r[3], rel=1e-3), (
                    name,
                    left_id,
                    right_id,
                )
                # 同一行 / 同一列（R 的 y / h、x / w 相等）在两边等价。
                assert (abs(a_r[1] - b_r[1]) < 0.01) == (abs(a_o[1] - b_o[1]) < 1e-6), (
                    name,
                    left_id,
                    right_id,
                )
                assert (abs(a_r[0] - b_r[0]) < 0.01) == (abs(a_o[0] - b_o[0]) < 1e-6), (
                    name,
                    left_id,
                    right_id,
                )

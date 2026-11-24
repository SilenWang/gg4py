"""组合层与 patchwork 1.3.2 的关系对拍（M3-1 / SIL-1001）。

夹具 `tests/fixtures/composition_r_reference.json` 由 `pixi run -e refs
refs:compose`（`tools/refs/compose_ref.R`）生成，记录 patchwork 渲染后从 SVG
读回的 panel 矩形（pt）。

本仓的字体度量与 R 不同，**绝对 pt 不可逐值比较**；这里比的是本 issue 的验收
口径本身：同一列 x/w 相同、同一行 y/h 相同、嵌套跨层不保证对齐。夹具的每一组
数字同时被断言一遍，所以「我们的关系」与「R 的关系」是同一份判据。
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import pytest

import gg4py
from ggcore.plot import aes, geom_point, ggplot, labs
from ggcore.theme import element_rect, theme
from ggio.frame import from_dict
from ggskia.text import ShaperMetrics

FIXTURE = Path(__file__).parent / "fixtures" / "composition_r_reference.json"
METRICS = ShaperMetrics()

#: 与 refs 脚本同一组 fill（SVG 归一化后的写法都收）。
COLOURS = {
    "#CC0000": ("#CC0000", "#C00", "#cc0000", "#c00"),
    "#00CC00": ("#00CC00", "#0C0", "#00cc00", "#0c0"),
    "#0000CC": ("#0000CC", "#00C", "#0000cc", "#00c"),
    "#CCCC00": ("#CCCC00", "#CC0", "#cccc00", "#cc0"),
}


def _reference() -> dict[str, Any]:
    assert FIXTURE.exists(), "缺少 R 夹具：先跑 `pixi run -e refs refs:compose`"
    return json.loads(FIXTURE.read_text())


def _plots() -> list[ggplot]:
    data = from_dict(
        {
            "x": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
            "y": [2.0, 4.0, 3.0, 5.0, 6.0, 3.0, 4.0, 7.0],
        }
    )

    def mk(fill: str, xlab: str) -> ggplot:
        return (
            ggplot(data, aes(x="x", y="y"))
            + geom_point()
            + labs(x=xlab)
            + theme(**{"panel.background": element_rect(fill=fill, colour=None)})
        )

    # 与 R 夹具同构：p2 的 x 轴标签更长（槽位更宽），p3 / p4 与 p1 同宽。
    return [
        mk("#CC0000", "x"),
        mk("#00CC00", "a-considerably-longer-x-label"),
        mk("#0000CC", "x"),
        mk("#CCCC00", "x"),
    ]


def _rects(panels: list[dict[str, Any]]) -> dict[str, tuple[float, float, float, float]]:
    return {panel["fill"]: (panel["x"], panel["y"], panel["w"], panel["h"]) for panel in panels}


def _svg_rects(plot: Any, path: Path, *, width_in: float, height_in: float) -> dict:
    gg4py.ggsave(plot, path, width=width_in, height=height_in)
    text = path.read_text()
    out: dict[str, tuple[float, float, float, float]] = {}
    for colour, spellings in COLOURS.items():
        for match in re.finditer(r"<rect[^>]*/?>", text):
            line = match.group(0)
            if not any(spelling in line for spelling in spellings):
                continue
            translate = re.search(r"translate\(([0-9.eE+-]+) ([0-9.eE+-]+)\)", line)
            dx = float(translate.group(1)) if translate else 0.0
            dy = float(translate.group(2)) if translate else 0.0

            def number(attr: str, text: str = line) -> float:
                found = re.search(attr + r'="([0-9.eE+-]+)"', text)
                return float(found.group(1)) if found else 0.0

            out[colour] = (
                dx + number("x"),
                dy + number("y"),
                number("width"),
                number("height"),
            )
    return out


def _assert_flat_alignment(rects: dict[str, tuple[float, float, float, float]]) -> None:
    """2×2 平铺：同列 x/w 相同、同行 y/h 相同（R 与我们的同一判据）。"""
    red = rects["#CC0000"]
    green = rects["#00CC00"]
    blue = rects["#0000CC"]
    yellow = rects["#CCCC00"]
    assert math.isclose(red[0], blue[0], abs_tol=1e-6)  # 同列 1 的 x
    assert math.isclose(red[2], blue[2], abs_tol=1e-6)  # 同列 1 的 w
    assert math.isclose(green[0], yellow[0], abs_tol=1e-6)
    assert math.isclose(green[2], yellow[2], abs_tol=1e-6)
    assert math.isclose(red[1], green[1], abs_tol=1e-6)  # 同行 1 的 y
    assert math.isclose(red[3], green[3], abs_tol=1e-6)  # 同行 1 的 h
    assert math.isclose(blue[1], yellow[1], abs_tol=1e-6)
    assert math.isclose(blue[3], yellow[3], abs_tol=1e-6)


def test_r_fixture_is_the_documented_patchwork_behaviour() -> None:
    """夹具自证：patchwork 1.3.2 的平铺对齐 / 嵌套差异确实如此。"""
    ref = _reference()
    assert ref["patchwork"] == "1.3.2"
    flat = _rects(ref["cases"]["flat_2x2"]["panels"])
    _assert_flat_alignment(flat)
    nested = _rects(ref["cases"]["nested"]["panels"])
    assert nested["#0000CC"][2] > nested["#CC0000"][2] * 1.5
    one = _rects(ref["cases"]["one_by_two"]["panels"])
    assert math.isclose(one["#CC0000"][1], one["#00CC00"][1], abs_tol=1e-6)
    assert math.isclose(one["#CC0000"][3], one["#00CC00"][3], abs_tol=1e-6)
    assert one["#00CC00"][0] > one["#CC0000"][0]


def test_our_flat_2x2_matches_the_r_alignment(tmp_path: Path) -> None:
    p1, p2, p3, p4 = _plots()
    combined = (p1 + p2 + p3 + p4) + gg4py.plot_layout(ncol=2)
    ours = _svg_rects(combined, tmp_path / "flat.svg", width_in=6.0, height_in=6.0)
    assert set(ours) == {"#CC0000", "#00CC00", "#0000CC", "#CCCC00"}
    _assert_flat_alignment(ours)


def test_our_one_by_two_matches_the_r_alignment(tmp_path: Path) -> None:
    p1, p2, _, _ = _plots()
    ours = _svg_rects(p1 | p2, tmp_path / "row.svg", width_in=7.0, height_in=5.0)
    red, green = ours["#CC0000"], ours["#00CC00"]
    assert math.isclose(red[1], green[1], abs_tol=1e-6)
    assert math.isclose(red[3], green[3], abs_tol=1e-6)
    assert math.isclose(red[2], green[2], abs_tol=1e-6)
    assert green[0] > red[0]


def test_our_nested_layout_reproduces_the_cross_layer_gap(tmp_path: Path) -> None:
    """嵌套层的 panel 由内层 layout 分配，与下层单 panel 不同宽（与 R 同向）。"""
    p1, p2, p3, _ = _plots()
    ours = _svg_rects((p1 | p2) / p3, tmp_path / "nested.svg", width_in=6.0, height_in=6.0)
    top_left, top_right, bottom = ours["#CC0000"], ours["#00CC00"], ours["#0000CC"]
    assert bottom[2] > top_left[2] * 1.5
    assert bottom[2] > top_right[2] * 1.5
    assert top_left[2] + top_right[2] <= bottom[2] + 0.01


def test_aligned_scales_keeps_tick_geometry_in_the_composition() -> None:
    """`align_scales(expand="first")` 之后，组合层的同列 panel 仍然严格对齐。"""
    p1, p2, _, _ = _plots()
    scaled = gg4py.align_scales([p1, p2], axis="xy", limits="union", expand="first")
    first, second = scaled
    # 不写临时文件：直接读表级 panel 矩形（与 IR / SVG 同一条解析）。
    from ggcore.units import UnitContext

    table = (first | second).gtable(metrics=METRICS, width_in=7.0, height_in=5.0)
    sizes = table.resolve(7.0 * 2.54, 5.0 * 2.54, ctx=UnitContext(metrics=METRICS))
    left = next(row for row in table.layout if row.name == "panel-area-1-1")
    right = next(row for row in table.layout if row.name == "panel-area-1-2")
    assert sizes.widths_cm[left.l - 1] == pytest.approx(sizes.widths_cm[right.l - 1], abs=1e-9)
    assert sum(sizes.heights_cm[: left.t - 1]) == pytest.approx(
        sum(sizes.heights_cm[: right.t - 1]), abs=1e-9
    )

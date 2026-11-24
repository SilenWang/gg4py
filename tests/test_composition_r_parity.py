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
from ggcore.theme import element_rect, element_text, theme
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


def test_default_grid_matches_r(tmp_path: Path) -> None:
    """默认网格（不带 `plot_layout()`）：patchwork 的 3 张图是 1×3（n2mfrow）。"""
    ref = _reference()
    panels = _rects(ref["cases"]["default_three"]["panels"])
    ys = {round(panel[1], 6) for panel in panels.values()}
    hs = {round(panel[3], 6) for panel in panels.values()}
    assert len(ys) == 1 and len(hs) == 1  # R：同一行
    xs = [panels[colour][0] for colour in ("#CC0000", "#00CC00", "#0000CC")]
    assert xs == sorted(xs) and len(set(xs)) == 3  # 一行三列

    p1, p2, p3, _ = _plots()
    ours = _svg_rects(p1 + p2 + p3, tmp_path / "default.svg", width_in=6.0, height_in=6.0)
    left, middle, right = ours["#CC0000"], ours["#00CC00"], ours["#0000CC"]
    assert math.isclose(left[1], middle[1], abs_tol=1e-6)
    assert math.isclose(left[3], middle[3], abs_tol=1e-6)
    assert math.isclose(middle[1], right[1], abs_tol=1e-6)
    assert left[0] < middle[0] < right[0]


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


# ---------------------------------------------------------------------------
# guides="collect" / guide_area()（SIL-1002）
# ---------------------------------------------------------------------------


def _legend_plots() -> tuple[ggplot, ggplot]:
    """与 `compose_ref.R` 的 `l1` / `l3` 同构：同图例 + 一个改了 `legend.text`。"""
    data = from_dict(
        {
            "x": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "y": [2.0, 4.0, 3.0, 5.0, 6.0, 3.0],
            "g": ["a", "b", "a", "b", "a", "b"],
        }
    )
    base = ggplot(data, aes(x="x", y="y", colour="g")) + geom_point() + labs(colour="gear")
    return base, base + theme(**{"legend.text": element_text(size=20)})


def _legend_labels(plot: Any) -> list[str]:
    """渲染后图例里的键文本（`a` / `b`）：R 侧数 SVG 里的 `>aa<` 是同一件事。"""
    scene = plot.to_scene(metrics=METRICS, width_in=7.0, height_in=5.0)
    labels: list[str] = []

    def walk(node: Any) -> None:
        labels.extend(label for label in node.texts if label in ("a", "b", "g"))
        for child in node.children or ():
            walk(child)

    walk(scene.root)
    return labels


def test_r_guides_fixture_is_the_documented_behaviour() -> None:
    """夹具自证：patchwork 1.3.2 的 keep / collect / 主题差异确实如此。"""
    guides = _reference()["guides"]
    assert guides["keep"]["guide_count"] == 2
    assert guides["keep"]["legend_label_count"] == 2
    assert guides["collect"]["guide_count"] == 1
    assert guides["collect"]["legend_label_count"] == 1
    assert guides["different_theme"]["guide_count"] == 2
    # collect 的顶层 guide-box 在 panel 右侧第 5 列、跨 panel 行。
    box = guides["collect"]["guide_box"]
    assert box["col_offset_from_panel"] == 5
    assert box["spans_panel_rows"] is True
    # guide_area()：占用普通 panel 格（与同格 patch 的矩形相同）。
    area = guides["area"]["guide_area"]
    assert area["matches_patch_cell"] is True
    assert area["w"] > 0 and area["h"] > 0


def test_our_guides_collect_matches_r_counts() -> None:
    ref = _reference()["guides"]
    first, third = _legend_plots()
    keep = _legend_labels(gg4py.wrap_plots(first, first, guides="keep"))
    collect = _legend_labels(gg4py.wrap_plots(first, first, guides="collect"))
    different = _legend_labels(gg4py.wrap_plots(first, third, guides="collect"))
    assert keep.count("a") == ref["keep"]["legend_label_count"] == 2
    assert collect.count("a") == ref["collect"]["legend_label_count"] == 1
    assert different.count("a") == ref["different_theme"]["legend_label_count"] == 2


def test_our_guide_box_sits_where_r_puts_it() -> None:
    """关系对拍：盒在 panel 块的右侧图例槽、纵向跨 panel 行。

    绝对偏移不逐值比：本仓 `plot_gtable()` 的 `guide-box-right` 槽比 ggplot2
    4.0.3 少一列（SIL-999 的已知差异，见 `docs/notes/gtable.md`），R 是
    panel 列 + 5，我们是 + 4；「在 panel 右侧的图例槽、跨 panel 行」一致。
    """
    ref = _reference()["guides"]["collect"]
    first, _third = _legend_plots()
    combined = gg4py.wrap_plots(first, first, guides="collect")
    from ggcore import composition
    from ggcore.composition import PANEL_COL, TABLE_COLS

    units = composition._build_units(combined, metrics=METRICS)
    assert units.guide is not None
    t, left, b, right = units.guide.area
    assert left == right
    assert left - (TABLE_COLS + PANEL_COL) > 0
    assert ref["guide_box"]["spans_panel_rows"] is True
    # 单行组合：盒的上下边就是 panel 行（与 R 的 t / b == panel t / b 同一关系）。
    assert t == b == composition._panel_rows(units)[0] + 1
    assert units.guide.layout.width_cm > 0


def test_our_guide_area_matches_the_r_cell() -> None:
    """`guide_area()` 的格就是普通 panel 格（R 的 `matches_patch_cell`）。"""
    first, _third = _legend_plots()
    combined = gg4py.wrap_plots(first, gg4py.guide_area(), guides="collect")
    from ggcore import composition
    from ggcore.composition import PANEL_COL, PANEL_ROW, TABLE_COLS

    units = composition._build_units(combined, metrics=METRICS)
    assert units.guide is not None and units.guide.guide_area
    assert units.guide.area == (
        PANEL_ROW,
        TABLE_COLS + PANEL_COL,
        PANEL_ROW,
        TABLE_COLS + PANEL_COL,
    )
    assert _legend_labels(combined).count("a") == 1


def test_different_data_is_a_documented_known_difference() -> None:
    """已知差异：数据不同、结构相同的图例，patchwork 不合并、本实现合并。

    patchwork 1.3.2 的 `collapse_guides()` 比较渲染后的 guide grob，ggplot2
    4.0.3 的 grob 里带随图层数据变化的字符串；SIL-1002 定的 GuideKey
    （aesthetic + scale spec + breaks/labels + theme 指纹）会合并。夹具把 R 的
    2 份记下来，本测试把差异钉住，避免以后误读成回归。
    """
    ref = _reference()["guides"]["different_data"]
    assert ref["legend_label_count"] == 2  # R：不合并
    first, _third = _legend_plots()
    data = from_dict(
        {
            "x": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "y": [6.0, 5.0, 4.0, 3.0, 2.0, 1.0],
            "g": ["a", "b", "a", "b", "a", "b"],
        }
    )
    other = ggplot(data, aes(x="x", y="y", colour="g")) + geom_point() + labs(colour="gear")
    assert _legend_labels(gg4py.wrap_plots(first, other, guides="collect")).count("a") == 1

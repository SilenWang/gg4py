"""组合矩阵的两条硬约束（SIL-743 / M2-11）。

1. **组合网格没有空格**：`matrix-*` 这批 case 要按三条轴铺满——
   分面（wrap / grid）× 坐标（cartesian / flip / polar / trans / radial）
   10 格、图例位置（right / left / top / bottom）× 排布方向（竖 / 横）×
   图例个数（单 / 双）16 格。缺一格就是「这个组合从来没人验过」。
2. **分面 × 极坐标 × 图例行距**：M1 复验抓到过「分面竖向图例上移」。这里钉
   R 的 guide-box 结构（`guide-box-right` 的 t..b 恰好等于 panel 行）与图例的
   行高 / 键间距，并要求图例块的中心与 panel 行并集的中心重合。

夹具 `tests/fixtures/matrix_r_reference.json` 由
`pixi run -e refs refs:matrix-cases`（`tools/refs/matrix_cases_ref.R`）生成；
参考资料是 ggplot2 4.0.3 的 `ggplotGrob()`（7×7in，与 `plot_layout()` 的缺省
页面同口径），行高按 `convertHeight(..., "cm")` 读回。
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from ggcore.build import build_plot
from ggcore.geom.scene import plot_layout
from ggcore.plotspec import load_plot

REPO = Path(__file__).resolve().parents[1]
CASES = REPO / "docs" / "cases"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "matrix_r_reference.json"
REFERENCE = json.loads(FIXTURE.read_text(encoding="utf-8"))
TAXONOMY = tomllib.loads((CASES / "taxonomy.toml").read_text(encoding="utf-8"))

FACETS = ("facet-wrap", "facet-grid")
COORDS = ("coord-cartesian", "coord-flip", "coord-polar", "coord-trans", "coord-radial")
POSITIONS = ("legend-pos-right", "legend-pos-left", "legend-pos-top", "legend-pos-bottom")
DIRECTIONS = ("guide-direction-vertical", "guide-direction-horizontal")
COUNTS = ("legend-single", "legend-double")

#: 行高里的文字行（标题 / 键）会有字体度量差：R 用 Arimo，我们用受管 DejaVu /
#: Noto，同样 11pt 的标题行差 0.017cm。键行高与间距是几何量，逐值比对。
TEXT_TOLERANCE_CM = 0.02


def _meta() -> dict[str, dict]:
    """`matrix-*` 的 `{case: meta}`（只看组合矩阵这批）。"""
    entries = {}
    for path in sorted(CASES.glob("matrix-*/meta.toml")):
        entries[path.parent.name] = tomllib.loads(path.read_text(encoding="utf-8"))
    return entries


META = _meta()


def test_matrix_cases_exist() -> None:
    """SIL-743 的验收下限：≥ 50 条 matrix case。"""
    assert len(META) >= 50


def test_facet_by_coord_grid_has_no_holes() -> None:
    """分面 × 坐标的 10 格全部有 case。"""
    covered = {
        (facet, coord)
        for meta in META.values()
        for facet in FACETS
        if facet in meta["features"]
        for coord in COORDS
        if coord in meta["features"]
    }
    missing = [
        (facet, coord) for facet in FACETS for coord in COORDS if (facet, coord) not in covered
    ]
    assert missing == []


def test_legend_grid_has_no_holes() -> None:
    """图例位置 × 排布方向 × 图例个数的 16 格全部有 case。

    只算**显式**指定了方向（`guide_legend(direction = ...)`）的 case：默认方向由
    位置推导，不能替「位置 × 方向」的交叉格子作数。
    """
    covered = {
        (position, direction, count)
        for meta in META.values()
        for position in POSITIONS
        if position in meta["features"]
        for direction in DIRECTIONS
        if direction in meta["features"]
        for count in COUNTS
        if count in meta["features"]
    }
    missing = [
        (position, direction, count)
        for position in POSITIONS
        for direction in DIRECTIONS
        for count in COUNTS
        if (position, direction, count) not in covered
    ]
    assert missing == []


def test_every_matrix_case_is_registered_in_taxonomy() -> None:
    """族与特性都登记过：矩阵不会落到「未登记的族 / 特性」一节。"""
    families = set(TAXONOMY["families"])
    features = set(TAXONOMY["features"])
    unregistered_families = {meta["family"] for meta in META.values()} - families
    unregistered_features = {
        feature for meta in META.values() for feature in meta["features"]
    } - features
    assert unregistered_features == set()
    assert unregistered_families == set()


def test_every_matrix_case_is_ci_ok_or_registered_as_a_gap() -> None:
    """`ci = true`，或 `ci = false` 且 `notes` 写明缺口（SIL-715）。"""
    for name, meta in META.items():
        if meta.get("ci", True):
            assert meta["source"].startswith("svglite:"), name
        else:
            assert "SIL-715" in meta.get("notes", ""), name


def _polar_case_layout():
    name = REFERENCE["legend"]["case"]
    build = build_plot(load_plot(CASES / name)["plot"])
    return name, build, plot_layout(build)


def test_guide_box_spans_exactly_the_panel_rows() -> None:
    """R 的结构：`guide-box-right` 的 t..b 就是 panel 行（不分面时也不含 strip 带）。"""
    legend = REFERENCE["legend"]
    assert legend["guide_box_top"] == legend["panel_row_top"]
    assert legend["guide_box_bottom"] == legend["panel_row_bottom"]


def test_polar_facet_legend_row_spacing_matches_r() -> None:
    """2×2 分面 × 极坐标：键行高与键间距对 R 逐值（图例行距的回归钉）。"""
    _, _, layout = _polar_case_layout()
    legend = REFERENCE["legend"]
    expected = [round(value, 10) for value in legend["heights_cm"]]
    ours = [round(value, 10) for value in layout.legend_layouts[0].row_heights_cm]

    assert len(ours) == len(expected)
    # 行数一样、0 行（padding / 键间距）的位置一样
    assert [value == 0 for value in ours] == [value == 0 for value in expected]
    # 键行高是几何量：逐值
    key_rows = [value for value in expected if value > 0][1:]
    assert [value for value in ours if value > 0][1:] == pytest.approx(key_rows, abs=1e-12)
    # 标题行只有文字度量差（Arimo vs 受管字体）
    ours_title = next(value for value in ours if value > 0)
    expected_title = next(value for value in expected if value > 0)
    assert ours_title == pytest.approx(expected_title, abs=TEXT_TOLERANCE_CM)
    # 整块图例的宽高
    assert layout.legend_layouts[0].height_cm == pytest.approx(
        legend["legend_height_cm"], abs=TEXT_TOLERANCE_CM
    )
    assert layout.legend_layouts[0].width_cm == pytest.approx(
        legend["legend_width_cm"], abs=TEXT_TOLERANCE_CM
    )


def test_polar_facet_legend_is_centred_on_the_panel_rows() -> None:
    """图例块的中心 = panel 行并集的中心（M1「分面竖向图例上移」的判据）。"""
    _, build, layout = _polar_case_layout()
    origin = layout.legend_box_origins[0]
    boxes = layout.panel_boxes
    rows_bottom = min(box.y_cm for box in boxes.values())
    rows_top = max(box.top for box in boxes.values())
    assert origin.y_cm + origin.height_cm / 2.0 == pytest.approx(
        (rows_bottom + rows_top) / 2.0, abs=1e-9
    )
    assert build.panels, "分面 case 必须有面板"

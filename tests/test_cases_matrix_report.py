"""组合矩阵的报告口径：默认 expand 下的断点位置（SIL-743 / SIL-715 #7）。

M1 的 61 条 case 里 `labs()` 出现 0 次、几乎都显式 `expand = (0, 0)`，所以
「默认 expand 下断点落在哪」这件事此前没有被钉住。这里对齐两个 report-style
case：

- `matrix-report-default-expand`（单面板）
- `matrix-report-facet-wrap-grey`（2×2 facet_wrap，四个面板共享同一对范围）

夹具 `tests/fixtures/matrix_r_reference.json` 由 `pixi run -e refs refs:matrix-cases`
（`tools/refs/matrix_cases_ref.R`）生成：R 侧跑真正的 ggplot2 4.0.3，记录每个
面板的 `x.range` / `y.range`（含 expand）以及 **实际画出来的刻度位置**（npc）与
标签。位置口径同 `coord_ref.R`：有 `x.major` 时用面板顶层的（坐标变换后），
否则用 `ViewScale$break_positions()`。

像素对拍不在这里：这两条 case 的 `meta.toml` 是 `ci = false`，缺口记在 SIL-715
（字体度量主导的密集图差异），见 `docs/cases/README.md` 的「M2-11」一节。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ggcore.axis import axis_ticks
from ggcore.build import build_plot
from ggcore.plotspec import load_plot

REPO = Path(__file__).resolve().parents[1]
CASES = REPO / "docs" / "cases"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "matrix_r_reference.json"
REFERENCE = json.loads(FIXTURE.read_text(encoding="utf-8"))
REPORT_CASES = {case["name"]: case for case in REFERENCE["report_cases"]}

TOLERANCE = 1e-12

#: 夹具里的 case 名 → `docs/cases/` 下的目录名（R 侧名字不带 `matrix-` 前缀）。
CASE_DIRS = {
    "report_default_expand": "matrix-report-default-expand",
    "report_facet_wrap_grey": "matrix-report-facet-wrap-grey",
}


def _build(name: str):
    """按 case 的 `plot.py` 构建同一张图（走语法层与生产管线）。"""
    return build_plot(load_plot(CASES / CASE_DIRS[name])["plot"])


def _scale(panel, params, side: str):
    """该面板 / 该边用的标度（`scale_key()` 处理 flip / 极坐标的换边）。"""
    return panel.scales.scale(params.scale_key(side))


@pytest.mark.parametrize("name", sorted(REPORT_CASES))
def test_panel_ranges_and_breaks_match_r(name: str) -> None:
    case = REPORT_CASES[name]
    build = _build(name)
    assert len(build.panels) == len(case["panels"])
    for expected in case["panels"]:
        params = build.panel_params_by_panel[expected["panel"]]
        panel = build.panels[expected["panel"] - 1]
        assert params.x_range == pytest.approx(tuple(expected["x_range"]), abs=TOLERANCE)
        assert params.y_range == pytest.approx(tuple(expected["y_range"]), abs=TOLERANCE)

        x_ticks = axis_ticks(_scale(panel, params, "bottom"), params, "bottom")
        assert list(x_ticks.positions) == pytest.approx(expected["x_positions"], abs=TOLERANCE)
        assert list(x_ticks.labels) == expected["x_labels"]

        y_ticks = axis_ticks(_scale(panel, params, "left"), params, "left")
        assert list(y_ticks.positions) == pytest.approx(expected["y_positions"], abs=TOLERANCE)
        assert list(y_ticks.labels) == expected["y_labels"]


def test_default_expand_is_not_the_zero_expand_case() -> None:
    """守住「这条 case 真的在考默认 expand」：面板范围必须比数据范围宽。

    否则把 `expand = (0, 0)` 写回去也会绿——那是 M1 覆盖盲区的原样。
    """
    build = _build("report_default_expand")
    panel = build.panels[0]
    data_x = panel.scales.scale("x").limits()
    data_y = panel.scales.scale("y").limits()
    params = panel.panel_params
    assert params.x_range[0] < min(data_x)
    assert params.x_range[1] > max(data_x)
    assert params.y_range[0] < min(data_y)
    assert params.y_range[1] > max(data_y)

"""设备侧曲线求值的 R 对拍（M0-8）。

夹具由 `pixi run -e refs refs:device` 生成（`tools/refs/device_ref.R`）：

- `xspline`：`xsplineGrob()` → `grid:::xsplinePoints()`，即 R 的
  `src/main/xspline.c` 采样出来的折线；
- `curve`：`curveGrob()` → `grid:::calcCurveGrob()` → 子 xspline 的采样点。

采样密度也是比的对象：步长公式里的页面对角线用的是夹具里的页面尺寸，所以逐点
都能对上，不是“形状差不多”。坐标在夹具里是英寸，这里乘 72 折成 pt。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ggskia.curves import curve_points, xspline_points

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "device_r_reference.json"


def load() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


DATA = load()
PT = 72.0
PAGE = tuple(value * PT for value in DATA["page_in"])
# R 侧是 double，差异只在最后几位；pt 量级上给 1e-9 的余量。
TOLERANCE = 1e-9


@pytest.mark.parametrize("case", DATA["xspline"], ids=lambda case: case["id"])
def test_xspline_matches_r(case: dict) -> None:
    points = np.asarray(case["points"], dtype=float) * PT
    got = xspline_points(points, case["shapes"], open=case["open"], page=PAGE)
    want = np.asarray(case["polyline"], dtype=float) * PT
    assert got.shape == want.shape
    assert np.abs(got - want).max() < TOLERANCE


@pytest.mark.parametrize("case", DATA["curve"], ids=lambda case: case["id"])
def test_curve_matches_r(case: dict) -> None:
    x1, y1, x2, y2 = (value * PT for value in case["ends"])
    got = curve_points(
        x1,
        y1,
        x2,
        y2,
        curvature=case["curvature"],
        angle=case["angle"],
        ncp=case["ncp"],
        shape=case["shape"],
        square=case["square"],
        inflect=case["inflect"],
        open=case["open"],
        page=PAGE,
    )
    want = np.asarray(case["polyline"], dtype=float) * PT
    assert got.shape == want.shape
    assert np.abs(got - want).max() < TOLERANCE


def test_fixture_covers_the_documented_cases() -> None:
    """名单钉死：加/删用例要同时改 R 脚本，避免夹具悄悄少一半。"""
    assert {case["id"] for case in DATA["xspline"]} == {
        "xspline-open-4",
        "xspline-open-5-negative",
        "xspline-closed-5",
        "xspline-open-3-round",
        "xspline-open-6-linear",
        "xspline-open-2",
        "xspline-closed-4-staircase",
        "xspline-open-mixed-shapes",
    }
    assert {case["id"] for case in DATA["curve"]} == {
        "curve-square-default",
        "curve-square-ncp2",
        "curve-curved-angle90",
        "curve-angle60-negative",
        "curve-angle45-curvature2",
        "curve-inflect",
        "curve-inflect-square",
        "curve-closed",
        "curve-aligned-straight",
    }

"""SIL-824 返工 · IR 的逐字节确定性（不依赖宿主 libm / numpy 版本）。

背景：`gate:pyodide` 在本机 515/515 全绿、CI runner 上却有 3 条 `coord_sf` case
两端不一致。差的是**宿主** glibc 的 `sin` / `cos` / `atan2` 末位，经 `1/cos(lat)`
之类的比例放大后写进了 `viewport.transform`。

这些用例把「确定性」钉在源头：不是等 CI 红，而是主动注入 ±1 ULP 的 libm 噪声，
断言 IR 字节不变。全量 515 条的版本是 `pixi run gate:libm-noise`（挂进 `check`）；
这里放几条快的，覆盖量化点在哪儿、以及每个量化函数的边界行为。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools" / "gates"))

import libm_noise

from ggcore import ir
from ggcore.coord import CoordTransform, _canonical_values, as_coord_transform, munch_steps
from ggcore.ir.nodes import PARAM_DECIMALS, _canonical_float, f32
from ggcore.metrics.fallback import default_metrics
from ggcore.plotspec import build_scene, load_plot
from ggcore.sf import st_transform_xy

CASES = REPO / "docs" / "cases"
#: CI 上真实漂过的那三条（`coord_sf` 的 `1/cos(lat)` 比例 + 单点几何的窄范围）。
SF_CASES = (
    "upstream-coord-sf-coord-sf-with-custom-guides",
    "upstream-coord-sf-non-sf-geoms-using-long-lat",
    "upstream-coord-sf-non-sf-geoms-using-projected-coords",
)


def _digest(case: str) -> str:
    import hashlib

    scene = build_scene(load_plot(CASES / case), metrics=default_metrics())
    return hashlib.sha256(ir.encode(scene)).hexdigest()


# ---------------------------------------------------------------------------
# 量化点本身
# ---------------------------------------------------------------------------


def test_param_floats_are_quantised_to_a_fixed_grid() -> None:
    assert PARAM_DECIMALS >= 8, "网格太细就吸收不掉 1 ULP 噪声"
    grid = 10.0**-PARAM_DECIMALS
    assert _canonical_float(1.2345678901234567 + grid / 4) == _canonical_float(1.2345678901234567)
    # 差 1 ULP 的两个值必须落到同一格。
    value = 441.9999333333334
    assert _canonical_float(value) == _canonical_float(math.nextafter(value, math.inf))


def test_param_floats_keep_nan_and_infinity_untouched() -> None:
    assert math.isnan(_canonical_float(float("nan")))
    assert _canonical_float(math.inf) == math.inf
    assert _canonical_float(-math.inf) == -math.inf


def test_f32_buffer_quantises_before_the_float32_rounding() -> None:
    """1 ULP 的 double 差不能翻过 float32 的舍入边界。"""
    value = 445.71942138671875
    nudged = math.nextafter(value, math.inf)
    assert f32([value]).tobytes() == f32([nudged]).tobytes()


def test_f32_buffer_keeps_nan_bit_patterns() -> None:
    """`run_ir.py` 的边角取值 scene 要逐位保留 NaN 的 payload。"""
    bits = np.array([0x7FC00000, 0xFFC00000, 0x7F800001], dtype=np.uint32)
    values = bits.view(np.float32)
    out = f32(values.copy())
    assert out.tobytes() == values.tobytes()


def test_munch_steps_ignores_a_one_ulp_shift() -> None:
    """段数是离散判定：商贴在整数上时，1 ULP 不能让它多一段。"""
    distance = 1.0  # 商恰好是 100
    assert munch_steps(distance, 0.01) == munch_steps(math.nextafter(distance, math.inf), 0.01)


def test_coord_transform_results_are_quantised() -> None:
    log10 = as_coord_transform("log10")
    assert isinstance(log10, CoordTransform)
    # `np.log(1000)/log(10)` 在两端能差 1 ULP，量化后必须都是 3.0。
    out = log10.apply(np.array([1000.0]))
    assert out[0] == 3.0
    assert _canonical_values(np.array([math.nextafter(3.0, math.inf)]))[0] == 3.0


def test_sf_projection_is_quantised_but_NaN_still_propagates() -> None:
    lon = np.array([-81.5, float("nan")])
    lat = np.array([36.2, 36.0])
    x, y = st_transform_xy(lon, lat, 3857, 4326)
    assert math.isnan(x[1]) and math.isnan(y[1])
    # 量化网格 1e-5 m：结果必须落在网格上（乘 1e5 后是整数）。
    assert abs(x[0] * 1e5 - round(x[0] * 1e5)) < 1e-6


# ---------------------------------------------------------------------------
# 端到端：CI 上真实漂过的三条 case，在 libm 噪声下必须逐字节不变
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", libm_noise.MODES)
@pytest.mark.parametrize("case", SF_CASES)
def test_sf_cases_survive_libm_noise(case: str, mode: str) -> None:
    baseline = _digest(case)
    with libm_noise.libm_noise(mode, seed=7):
        assert _digest(case) == baseline


@pytest.mark.parametrize("mode", libm_noise.MODES)
def test_coord_and_polar_cases_survive_libm_noise(mode: str) -> None:
    """极坐标 / coord_trans 曾经因为 `ceil()` 段数与 90° 翻转判定漂过。"""
    cases = (
        "coord-polar-bar",
        "upstream-coord-polar-rose",
        "upstream-coord-transform-reversed",
        "upstream-geom-raster-rectangle-fallback",
    )
    baseline = {case: _digest(case) for case in cases}
    with libm_noise.libm_noise(mode, seed=7):
        for case in cases:
            assert _digest(case) == baseline[case], case

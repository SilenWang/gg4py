"""SIL-824 返工 · IR 的逐字节确定性（不依赖宿主 libm / numpy 版本）。

背景：`gate:pyodide` 在本机 515/515 全绿、CI runner 上却有 3 条 `coord_sf` case
两端不一致。差的是**宿主** glibc 的 `sin` / `cos` / `atan2` 末位，经 `1/cos(lat)`
之类的比例放大后写进了 `viewport.transform`。

这些用例把「确定性」钉在源头：不是等 CI 红，而是主动注入 ±1 ULP 的 libm 噪声，
断言 IR 字节不变。全量 515 条的版本是 `pixi run gate:libm-noise`（挂进 `check`）；
这里放几条快的，覆盖量化点在哪儿、以及每个量化函数的边界行为。

端到端那组按「三种噪声 × 种子」展开：`mixed` 的偏移方向由「取值位模式 ^ seed」定。
SIL-864 起 seed 的低 3 位各选一个字节对齐的抽取位，所以 0–7 是 8 份互不相同的噪声，
`seed & 7` 相同的种子（0 与 8）逐位相同——**seed 空间 = 8 个等价类**，依据是
`pixi run gate:libm-noise:seeds` 打印的 sha256 表（0–7 两两不同、8–15 复现 0–7）；
`up` / `down` 方向写死，种子不参与，各留一条。
"""

from __future__ import annotations

import math
import struct
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

#: 噪声 × 种子的组合。
#:
#: `up` / `down` 的方向写死在模式里（`_direction()` 直接给 ±inf），seed 不参与，
#: 各留一条；`mixed` 的方向是「取值的位模式混合 → 按 seed 选抽取位」，所以要把
#: 整个等价类空间扫一遍。
#:
#: 为什么是 0–7 这 8 条：`_noise_bit()` 用 `seed & 7` 从 64 位混合值里选一个字节
#: 对齐的比特，seed 的高位不参与——`seed & 7` 相同就是同一份噪声（0 与 8 逐位相同），
#: 所以 **seed 空间 = 8 个等价类**，扫 0–7 就覆盖了全部。依据是
#: `pixi run gate:libm-noise:seeds` 的 sha256 表：0–7 两两不同、8–15 分别复现 0–7。
#: `test_mixed_noise_seed_space_has_eight_equivalence_classes` 把这条钉死。
NOISE_VARIANTS = tuple(
    pytest.param(mode, seed, id=f"{mode}-seed{seed}")
    for mode in libm_noise.MODES
    for seed in (tuple(range(libm_noise.SEED_CLASSES)) if mode == "mixed" else (7,))
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
# seed 空间：8 个等价类，而 0–7 各是一份不同的噪声
# ---------------------------------------------------------------------------

#: 混合用的取值语料：覆盖量级、符号与「整齐」的取值，语料本身不调用 libm。
SEED_CORPUS = tuple(
    [i / 7.0 for i in range(1, 300)]
    + [float(i) for i in range(1, 65)]
    + [2.0**i for i in range(-20, 21)]
    + [1.0 + 2.0**-k for k in range(1, 24)]
)


def _noise_field(seed: int) -> tuple[int, ...]:
    """一档 seed 的噪声场：语料里每个取值朝哪一侧偏（+1 / -1）。"""
    return tuple(1 if libm_noise.bit_direction(value, seed) > 0 else -1 for value in SEED_CORPUS)


def test_mixed_noise_seed_space_has_eight_equivalence_classes() -> None:
    """`seed & 7` 决定抽哪个比特：0–7 两两不同，8 与 0 逐位相同。"""
    classes = libm_noise.SEED_CLASSES
    assert classes == 8, "seed 空间变了就同步改 NOISE_VARIANTS 的覆盖范围"
    fields = [_noise_field(seed) for seed in range(classes)]
    assert len(set(fields)) == classes, "seed 0–7 必须给出 8 份不同的噪声"
    for seed in range(classes):
        assert _noise_field(seed + classes) == fields[seed]
        assert _noise_field(seed + 2 * classes) == fields[seed]


def test_mixed_noise_is_one_ulp_and_deterministic() -> None:
    """幅度仍受控：每一处位移恰好 1 ULP，且同一个数两次得到同一方向。"""
    for value in SEED_CORPUS:
        for seed in range(libm_noise.SEED_CLASSES):
            direction = libm_noise.bit_direction(value, seed)
            assert direction in (math.inf, -math.inf)
            assert libm_noise.bit_direction(value, seed) == direction
            moved = math.nextafter(value, direction)
            before = struct.unpack("<q", struct.pack("<d", value))[0]
            after = struct.unpack("<q", struct.pack("<d", moved))[0]
            assert abs(after - before) == 1


def test_mixed_noise_array_and_scalar_paths_agree() -> None:
    """`numpy` 数组走的是向量化的同一套混合；两条路径不能各偏各的。"""
    values = np.array(SEED_CORPUS, dtype=np.float64)
    for seed in range(libm_noise.SEED_CLASSES):
        with libm_noise.libm_noise("mixed", seed=seed):
            vectorised = np.cos(values)
        with libm_noise.libm_noise("mixed", seed=seed):
            scalar = np.array([math.cos(float(value)) for value in values])
        assert np.array_equal(vectorised, scalar), f"seed={seed}"


# ---------------------------------------------------------------------------
# 端到端：CI 上真实漂过的三条 case，在 libm 噪声下必须逐字节不变
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode, seed", NOISE_VARIANTS)
@pytest.mark.parametrize("case", SF_CASES)
def test_sf_cases_survive_libm_noise(case: str, mode: str, seed: int) -> None:
    baseline = _digest(case)
    with libm_noise.libm_noise(mode, seed=seed):
        assert _digest(case) == baseline, f"{case} 在 {mode} / seed={seed} 下漂了"


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

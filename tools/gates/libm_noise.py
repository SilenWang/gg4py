"""把宿主 `libm` 的末位噪声注入进来（模拟「另一台机器」）。

SIL-824 返工的直接原因：`gate:pyodide` 在本机 515/515 全绿，在 CI runner 上却有
3 条 `coord_sf` case 两端 IR 不一致——同一份代码、同一个 Pyodide，差的是**宿主**
`glibc` 的 `sin` / `cos` / `atan2` 末位。这种差异没法在本机复现，只能主动注入：

    from libm_noise import libm_noise

    with libm_noise("mixed"):
        ...  # 这段代码眼里的 math/numpy 三角函数都偏了 ±1 ULP

三种模式：

* `up` / `down`：整体朝一个方向偏 1 ULP（上界，比真实差异更狠）；
* `mixed`：方向由**取值本身的位模式**决定（贴近真实：只有部分取值差 1 ULP）。

`mixed` 不是"随机"而是"按值定方向"：同一个数在哪个进程、哪次调用里都往同一侧偏，
于是失败可复现、探针与门禁看到的是同一份噪声（早期用 `random.Random` 时同一个
种子在两次运行里也可能给不同结果，排查时对不上）。

**seed 空间 = 8 个等价类**（SIL-864）。`mixed` 的方向取的是「取值位模式」与 seed
混合后的一个比特：先做两轮乘加混合（splitmix64 的 finalizer），再从 64 位结果里
按 `seed & 7` 选一个**字节对齐**的比特（第 8×k 位）当方向。于是

* `seed & 7` 相同的种子是同一份噪声（0/8、1/9 … 逐位相同），等价类恰好 8 个；
* `seed & 7` 不同的 8 档各抽一个不同的比特，8 份噪声两两不同
  （`pixi run gate:libm-noise:seeds` 打印的 sha256 表就是证据）。

改这一点的原因：SIL-824 的实现是 `((bits >> 1) ^ (seed & 0xFF)) & 1`，异或后只取
最低位，真正起作用的只有 `seed & 1`——`seed 0/2` 是同一份噪声、`1/3/7` 也是，
「扫 0–3」实际只覆盖两个等价类。现在 seed 的 3 个低位各选一个抽取位。

`0.0` 不动：`nextafter(0.0, ±inf)` 是 denormal，`log(0)` 之类会被放大成 inf，
而真实 libm 不会在 0 上差 1 ULP——那是注入器的假象，不是被测代码的问题。
"""

from __future__ import annotations

import contextlib
import math
import struct
from collections.abc import Iterator

import numpy as np

__all__ = [
    "MATH_FNS",
    "MODES",
    "NP_FNS",
    "SEED_BITS",
    "SEED_CLASSES",
    "bit_direction",
    "install",
    "libm_bias",
    "libm_noise",
    "restore",
]

#: 三种噪声：上界两种 + 按位定方向的一种。
MODES = ("up", "down", "mixed")

#: `mixed` 用到的 seed 位数（低 3 位），因此 seed 空间被切成 8 个等价类。
SEED_BITS = 3
#: seed 空间的等价类数：`seed & (SEED_CLASSES - 1)` 相同的种子给出同一份噪声。
SEED_CLASSES = 1 << SEED_BITS

_MASK64 = (1 << 64) - 1
#: splitmix64 finalizer 的两个乘数：两轮乘加就能把一位输入扩散到全部 64 位。
_MIX_A = 0xBF58476D1CE4E5B9
_MIX_B = 0x94D049BB133111EB
#: 抽取出方向的比特之间隔一个字节：8 个等价类各抽一个互不相同、且各自混匀的位。
_EXTRACT_STRIDE = 8

#: `libm_bias()` 的相对偏移量：1e-4 远大于 IR 的任何量化网格（参数 1e-8 /
#: 坐标 1e-5 / 投影 1e-5 m），所以负向对照里一定会有 case 漂移。
BIAS = 1e-4

#: `math` 里会被投影 / 版式用到的函数。
MATH_FNS = (
    "sin",
    "cos",
    "tan",
    "atan",
    "atan2",
    "asin",
    "acos",
    "sqrt",
    "log",
    "log10",
    "exp",
    "hypot",
    "radians",
    "degrees",
)
#: `numpy` 的同一组（ufunc 名与 math 不同：`arctan2` / `deg2rad` …）。
NP_FNS = (
    "sin",
    "cos",
    "tan",
    "arctan",
    "arctan2",
    "arcsin",
    "arccos",
    "sqrt",
    "log",
    "log10",
    "exp",
    "hypot",
    "radians",
    "degrees",
)

_ORIGINAL_MATH = {name: getattr(math, name) for name in MATH_FNS if hasattr(math, name)}
_ORIGINAL_NP = {name: getattr(np, name) for name in NP_FNS if hasattr(np, name)}


def _noise_bit(bits: int, seed: int) -> int:
    """`mixed` 的方向位：0 = 朝 +∞ 偏，1 = 朝 -∞ 偏。

    `bits` 是该 float64 的 64 位表示。两轮乘加（splitmix64 finalizer）把取值的
    全部位混匀，再按 `seed & (SEED_CLASSES - 1)` 选一个字节对齐的比特：seed 的
    低位不同 → 抽的比特不同 → 噪声场不同；低位相同（0 与 8）→ 逐位相同。
    """
    x = bits ^ (bits >> 17)
    x = ((x ^ (x >> 30)) * _MIX_A) & _MASK64
    x = ((x ^ (x >> 27)) * _MIX_B) & _MASK64
    x ^= x >> 31
    return (x >> (_EXTRACT_STRIDE * (seed & (SEED_CLASSES - 1)))) & 1


def _noise_up(bits: np.ndarray, seed: int) -> np.ndarray:
    """`_noise_bit()` 的 numpy 版：uint64 数组 → 布尔数组（True = 朝 +∞ 偏）。"""
    shift = np.uint64(_EXTRACT_STRIDE * (seed & (SEED_CLASSES - 1)))
    x = bits ^ np.right_shift(bits, np.uint64(17))
    x = (x ^ np.right_shift(x, np.uint64(30))) * np.uint64(_MIX_A)
    x = (x ^ np.right_shift(x, np.uint64(27))) * np.uint64(_MIX_B)
    x = x ^ np.right_shift(x, np.uint64(31))
    return ((x >> shift) & np.uint64(1)) == 0


def _bit_sign(value: float, seed: int) -> float:
    """按取值的位模式决定朝哪一侧偏：同一个数永远得到同一个方向。"""
    bits = struct.unpack("<Q", struct.pack("<d", value))[0]
    return math.inf if _noise_bit(bits, seed) == 0 else -math.inf


def bit_direction(value: float, seed: int = 0) -> float:
    """`mixed` 模式下 `value` 朝哪一侧偏 1 ULP（+inf / -inf）。

    给单测与 `gate:libm-noise:seeds` 的证据表用：不装补丁也能看到噪声场。
    """
    return _bit_sign(value, seed)


def _direction(mode: str, value: float, seed: int) -> float:
    if mode == "up":
        return math.inf
    if mode == "down":
        return -math.inf
    if mode == "mixed":
        return _bit_sign(value, seed)
    raise ValueError(f"未知的 libm 噪声模式：{mode!r}（可用：up / down / mixed）")


def _noisy_scalar(out, mode: str, seed: int):
    if isinstance(out, float) and out != 0.0 and math.isfinite(out):
        return math.nextafter(out, _direction(mode, out, seed))
    return out


def _noisy_array(out, mode: str, seed: int):
    if isinstance(out, np.ndarray):
        if mode == "mixed":
            # float32 也按 float64 的位模式定方向：两条路径看到的是同一份噪声。
            bits = np.ascontiguousarray(out, dtype=np.float64).view(np.uint64)
            up = _noise_up(bits, seed)
        else:
            up = np.full(out.shape, mode == "up", dtype=bool)
        moved = np.nextafter(out, np.where(up, np.inf, -np.inf))
        return np.where(out == 0.0, out, moved)
    if isinstance(out, (float, np.floating)):
        value = float(out)
        if value == 0.0 or not math.isfinite(value):
            return value
        return np.nextafter(value, _direction(mode, value, seed))
    return out


def _install(scalar, array) -> None:
    """把 `math` / `numpy` 的函数换成 `scalar` / `array` 包过的版本。"""
    for name, original in _ORIGINAL_MATH.items():

        def wrapper(*args, _fn=original, **kwargs):
            return scalar(_fn(*args, **kwargs))

        setattr(math, name, wrapper)

    for name, original in _ORIGINAL_NP.items():

        def wrapper(*args, _fn=original, **kwargs):
            return array(_fn(*args, **kwargs))

        setattr(np, name, wrapper)


def install(mode: str = "mixed", *, seed: int = 0) -> None:
    """把 `math` / `numpy` 里那组函数换成偏 ±1 ULP 的版本。"""
    if mode not in MODES:
        raise ValueError(f"未知的 libm 噪声模式：{mode!r}（可用：up / down / mixed）")
    _install(
        lambda out: _noisy_scalar(out, mode, seed),
        lambda out: _noisy_array(out, mode, seed),
    )


def restore() -> None:
    """还原原函数（幂等）。"""
    for name, original in _ORIGINAL_MATH.items():
        setattr(math, name, original)
    for name, original in _ORIGINAL_NP.items():
        setattr(np, name, original)


@contextlib.contextmanager
def libm_noise(mode: str = "mixed", *, seed: int = 0) -> Iterator[None]:
    install(mode, seed=seed)
    try:
        yield
    finally:
        restore()


def _biased(value, factor: float):
    if isinstance(value, np.ndarray):
        return np.where(np.isfinite(value), value * factor, value)
    if isinstance(value, float) and value != 0.0 and math.isfinite(value):
        return value * factor
    return value


@contextlib.contextmanager
def libm_bias(factor: float = 1.0 + BIAS) -> Iterator[None]:
    """负向对照：把 libm 输出整体乘 `factor`（默认 +1e-4 相对）。

    幅度远超 IR 的量化网格（参数 1e-8 / 坐标 1e-5），所以只要门禁真的在看字节，
    就一定会有 case 漂移。`check_libm_noise.py --expect-diff` 用它证明自己没瞎：
    一个永远绿的噪声门禁和「什么都没比」是同义词。
    """
    _install(lambda out: _biased(out, factor), lambda out: _biased(out, factor))
    try:
        yield
    finally:
        restore()

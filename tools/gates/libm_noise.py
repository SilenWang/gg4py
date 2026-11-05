"""把宿主 `libm` 的末位噪声注入进来（模拟「另一台机器」）。

SIL-824 返工的直接原因：`gate:pyodide` 在本机 515/515 全绿，在 CI runner 上却有
3 条 `coord_sf` case 两端 IR 不一致——同一份代码、同一个 Pyodide，差的是**宿主**
`glibc` 的 `sin` / `cos` / `atan2` 末位。这种差异没法在本机复现，只能主动注入：

    from libm_noise import libm_noise

    with libm_noise("random"):
        ...  # 这段代码眼里的 math/numpy 三角函数都偏了 ±1 ULP

三种模式：

* `up` / `down`：整体朝一个方向偏 1 ULP（上界，比真实差异更狠）；
* `mixed`：方向由**取值本身的位模式**决定（贴近真实：只有部分取值差 1 ULP）。

`mixed` 不是"随机"而是"按值定方向"：同一个数在哪个进程、哪次调用里都往同一侧偏，
于是失败可复现、探针与门禁看到的是同一份噪声（早期用 `random.Random` 时同一个
种子在两次运行里也可能给不同结果，排查时对不上）。`seed` 只用来翻转某一位的选择。

`0.0` 不动：`nextafter(0.0, ±inf)` 是 denormal，`log(0)` 之类会被放大成 inf，
而真实 libm 不会在 0 上差 1 ULP——那是注入器的假象，不是被测代码的问题。
"""

from __future__ import annotations

import contextlib
import math
import struct
from collections.abc import Iterator

import numpy as np

__all__ = ["MATH_FNS", "MODES", "NP_FNS", "install", "libm_noise", "restore"]

#: 三种噪声：上界两种 + 按位定方向的一种。
MODES = ("up", "down", "mixed")

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


def _bit_sign(value: float, seed: int) -> float:
    """按取值的位模式决定朝哪一侧偏：同一个数永远得到同一个方向。"""
    bits = struct.unpack("<Q", struct.pack("<d", value))[0]
    return math.inf if ((bits >> 1) ^ (seed & 0xFF)) & 1 == 0 else -math.inf


def _direction(mode: str, value: float, seed: int) -> float:
    if mode == "up":
        return math.inf
    if mode == "down":
        return -math.inf
    if mode == "mixed":
        return _bit_sign(value, seed)
    raise ValueError(f"未知的 libm 噪声模式：{mode!r}（可用：up / down / mixed）")


def install(mode: str = "mixed", *, seed: int = 0) -> None:
    """把 `math` / `numpy` 里那组函数换成偏 ±1 ULP 的版本。"""
    if mode not in ("up", "down", "mixed"):
        raise ValueError(f"未知的 libm 噪声模式：{mode!r}（可用：up / down / mixed）")

    for name, original in _ORIGINAL_MATH.items():

        def wrapper(*args, _fn=original, **kwargs):
            out = _fn(*args, **kwargs)
            if isinstance(out, float) and out != 0.0 and math.isfinite(out):
                return math.nextafter(out, _direction(mode, out, seed))
            return out

        setattr(math, name, wrapper)

    for name, original in _ORIGINAL_NP.items():

        def wrapper(*args, _fn=original, **kwargs):
            out = _fn(*args, **kwargs)
            if isinstance(out, np.ndarray):
                bits = out.view(np.uint64) if out.dtype == np.float64 else None
                if bits is None:
                    moved = np.nextafter(out, math.inf)
                else:
                    up = ((bits >> np.uint64(1)) ^ np.uint64(seed & 0xFF)) & np.uint64(1) == 0
                    if mode == "up":
                        up = np.ones(out.shape, dtype=bool)
                    elif mode == "down":
                        up = np.zeros(out.shape, dtype=bool)
                    target = np.where(up, np.inf, -np.inf)
                    moved = np.nextafter(out, target)
                return np.where(out == 0.0, out, moved)
            if isinstance(out, (float, np.floating)):
                value = float(out)
                if value == 0.0 or not math.isfinite(value):
                    return value
                return np.nextafter(value, _direction(mode, value, seed))
            return out

        setattr(np, name, wrapper)


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

"""SIL-864 · `mixed` 噪声的 seed 空间：8 个等价类，两两不同。

    pixi run gate:libm-noise:seeds

SIL-824 的 `_bit_sign()` 是 `((bits >> 1) ^ (seed & 0xFF)) & 1`：异或之后只取
最低位，真正参与方向的只有 `seed & 1`，于是 0/2 是同一份噪声、1/3/7 也是，
「seed 0–3」实际只覆盖两个等价类。现在 seed 的低 3 位各选一个字节对齐的抽取位，
seed 空间被 `seed & 7` 切成 8 类。

这个脚本把证据打出来：对一份固定的取值语料，逐档 seed 把取值按 `mixed` 的方向
偏 1 ULP，把偏完之后的 float64 字节拼起来算 sha256。判据三条：

1. seed 0–7 的摘要两两不同（8 份互不相同的噪声）；
2. seed 8–15 分别与 0–7 逐位相同（等价类 = `seed & 7`，没有第 9 份噪声）；
3. 每处位移都恰好是 1 ULP（噪声幅度没被放宽）。

退出码：0 = 三条都成立；1 = 有一条不成立（seed 空间被改坏了）。
"""

from __future__ import annotations

import hashlib
import math
import struct
import sys

import libm_noise

#: 固定的取值语料：覆盖量级、符号、以及在二进制上「整齐」的取值（1.0 / 0.5 …）。
#: 语料只由常数与算术拼出来，不调用 libm，所以它本身是逐位确定的。
CORPUS = tuple(
    [i / 7.0 for i in range(-2000, 2001)]
    + [float(i) for i in range(-64, 65)]
    + [2.0**i for i in range(-30, 31)]
    + [1.0 + 2.0**-k for k in range(1, 40)]
    + [i * math.pi / 13.0 for i in range(1, 600)]
)


def _bit_distance(a: float, b: float) -> int:
    """两个 float 在 64 位表示上隔了几个值（同号时 1 ULP = 1）。"""
    ia = struct.unpack("<Q", struct.pack("<d", a))[0]
    ib = struct.unpack("<Q", struct.pack("<d", b))[0]
    return abs(ia - ib)


def field(seed: int) -> tuple[str, int, int]:
    """一档 seed 的噪声场：摘要 + 朝上 / 朝下的取值个数。"""
    payload = bytearray()
    up = down = 0
    for value in CORPUS:
        moved = math.nextafter(value, libm_noise.bit_direction(value, seed))
        assert _bit_distance(value, moved) == 1, f"{value!r} 在 seed={seed} 下不是 1 ULP"
        payload += struct.pack("<d", moved)
        if moved > value:
            up += 1
        else:
            down += 1
    return hashlib.sha256(bytes(payload)).hexdigest(), up, down


def main() -> int:
    classes = libm_noise.SEED_CLASSES
    table = {seed: field(seed) for seed in range(2 * classes)}

    print(f"corpus = {len(CORPUS)} 个取值；seed 空间 = {classes} 个等价类（seed & {classes - 1}）")
    print()
    print("| seed | +1 ULP | -1 ULP | sha256（噪声字节） |")
    print("| ---: | ---: | ---: | --- |")
    for seed, (digest, up, down) in table.items():
        print(f"| {seed} | {up} | {down} | `{digest}` |")

    first = [table[seed][0] for seed in range(classes)]
    ok = True
    if len(set(first)) != classes:
        print(
            f"gate:libm-noise:seeds FAIL — seed 0..{classes - 1} 只有 "
            f"{len(set(first))} 份不同的噪声，期望 {classes} 份",
            file=sys.stderr,
        )
        ok = False
    for seed in range(classes, 2 * classes):
        if table[seed][0] != table[seed - classes][0]:
            print(
                f"gate:libm-noise:seeds FAIL — seed {seed} 应等于 seed {seed - classes}"
                f"（等价类 = seed & {classes - 1}），摘要却不同",
                file=sys.stderr,
            )
            ok = False

    if not ok:
        return 1
    print()
    print(
        f"gate:libm-noise:seeds: ok — seed 0..{classes - 1} 两两不同；"
        f"seed {classes}..{2 * classes - 1} 分别复现 0..{classes - 1}；每处只差 1 ULP"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""`ggcore.ir._cbor` 与 `cbor2.dumps(..., canonical=True)` 的差分对拍（SIL-646）。

`gate:pyodide` 只在**一份** scene 上比字节，证明不了 `_cbor` 是 canonical CBOR：
NaN 的位型、长度头、负数分支这些边角没有输入就永远不会被走到。本门禁把取值矩阵
拉平成「一个值一对字节」，两侧编码逐字节比，解码方向也比。

口径（与审核在 SIL-645 用的那份对拍同源）：

- 相等 → 通过；
- 不一致 → 失败，打印第一个差异的偏移与两侧上下文；
- **有两类取值 `_cbor` 按设计不写**，它们不算「不一致」，但必须**确实被拒**：

  1. 超 64 位整数。canonical CBOR 要写 bignum tag（2/3），IR 线格式不写 tag；
     IR 层因此把 `int` 参数收进 `[INT_MIN, INT_MAX]`（`ggcore.ir.nodes`），
     浏览器里不会出现这种 scene。
  2. `memoryview`。`cbor2` 6.1.5 把它当**整数数组**编（`83186118621863`），
     当成 byte string 编就是另一个值；IR 编码路径从不传它，所以 `_cbor` 选择
     报错，而不是写出两边不一致的字节。

这两类在这里断言「抛 CBORError」：哪天有人给 `_cbor` 补上 bignum 或 memoryview
支持，这条会红，逼着把上面的口径一起改。
"""

from __future__ import annotations

import math
import random
import struct
import sys
from typing import Any

import cbor2

from ggcore.ir import _cbor

FAILS: list[tuple[str, str, str]] = []
UNSUPPORTED: list[str] = []
COUNT = 0
COMPARED = 0


def _same(left: Any, right: Any) -> bool:
    if isinstance(left, float) and isinstance(right, float):
        if math.isnan(left) and math.isnan(right):
            return True
    if isinstance(left, (bytes, bytearray)) and isinstance(right, (bytes, bytearray)):
        return bytes(left) == bytes(right)
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_same(left[key], right[key]) for key in left)
    if isinstance(left, (list, tuple)):
        return len(left) == len(right) and all(
            _same(a, b) for a, b in zip(left, right, strict=False)
        )
    return left == right


def check(value: Any, label: str = "") -> None:
    """编码与解码两个方向都对拍。"""
    global COUNT, COMPARED
    COUNT += 1
    name = (label or repr(value))[:120]
    try:
        expected = cbor2.dumps(value, canonical=True)
    except Exception as exc:  # cbor2 的异常族很杂
        FAILS.append((name, "cbor2 编不出来", repr(exc)[:120]))
        return
    try:
        got = _cbor.dumps(value)
    except Exception as exc:
        FAILS.append((name, f"_cbor 抛错 {exc!r}"[:120], f"cbor2 写出了 {len(expected)}B"))
        return
    if got != expected:
        offset = next(
            (i for i, (a, b) in enumerate(zip(got, expected, strict=False)) if a != b),
            min(len(got), len(expected)),
        )
        FAILS.append(
            (
                name,
                f"got {len(got)}B @{offset} {got[max(0, offset - 6) : offset + 6].hex()}",
                f"exp {len(expected)}B @{offset} {expected[max(0, offset - 6) : offset + 6].hex()}",
            )
        )
        return
    COMPARED += 1
    try:
        decoded_ours = _cbor.loads(expected)
        decoded_cbor2 = cbor2.loads(expected)
    except Exception as exc:
        FAILS.append((name, f"_cbor.loads 抛错 {exc!r}"[:120], ""))
        return
    if not _same(decoded_ours, decoded_cbor2):
        FAILS.append((name, repr(decoded_ours)[:100], repr(decoded_cbor2)[:100]))


def check_unsupported(value: Any, label: str) -> None:
    """按设计不写的取值：cbor2 写得出，`_cbor` 必须明确拒绝。"""
    global COUNT
    COUNT += 1
    try:
        cbor2.dumps(value, canonical=True)
    except Exception as exc:  # 前提变了，说明这条口径该重写
        FAILS.append((label, "cbor2 居然也编不出来", repr(exc)[:120]))
        return
    try:
        got = _cbor.dumps(value)
    except _cbor.CBORError:
        UNSUPPORTED.append(label)
        return
    FAILS.append(
        (label, f"_cbor 没拒绝，写出 {len(got)}B {got[:12].hex()}", "按设计应抛 CBORError")
    )


def ints() -> list[int]:
    bases = [
        0,
        1,
        22,
        23,
        24,
        25,
        254,
        255,
        256,
        257,
        65534,
        65535,
        65536,
        65537,
        2**32 - 2,
        2**32 - 1,
        2**32,
        2**32 + 1,
        2**63,
        2**64 - 2,
        2**64 - 1,
    ]
    values = {0, 1, -1}
    for base in bases:
        values.add(base)
        values.add(-1 - base)
    return sorted(values)


NAN_PATTERNS = [
    0x7FF8000000000000,
    0xFFF8000000000000,
    0x7FF0000000000001,
    0x7FFFFFFFFFFFFFFF,
    0x7FF4000000000000,
]


def floats() -> list[float]:
    values = [
        0.0,
        -0.0,
        1.0,
        -1.0,
        0.5,
        1.5,
        2.0,
        0.1,
        1 / 3,
        math.pi,
        65504.0,
        65503.0,
        65519.0,
        65520.0,
        65535.0,
        65536.0,
        131008.0,
        100000.0,
        2048.0,
        2049.0,
        2048.5,
        1e-8,
        5.960464477539063e-08,
        6.103515625e-05,
        1e-45,
        1.401298464324817e-45,
        1.1754943508222875e-38,
        3.4028234663852886e38,
        3.4028235677973366e38,
        1e-300,
        1e300,
        1.7976931348623157e308,
        5e-324,
        2.2250738585072014e-308,
        float("inf"),
        float("-inf"),
        float("nan"),
    ]
    for pattern in NAN_PATTERNS:
        values.append(struct.unpack(">d", struct.pack(">Q", pattern))[0])
    for exp in range(-24, 17):
        for mant in (0, 1, 2, 3, 5, 1023, 2047):
            values.append(float(mant) * (2.0**exp))
    rng = random.Random(20261101)
    while len(values) < 4100:
        value = struct.unpack(">d", struct.pack(">Q", rng.getrandbits(64)))[0]
        if math.isnan(value) or math.isinf(value):
            continue
        values.append(value)
    return values


LENGTHS = (0, 1, 2, 22, 23, 24, 25, 254, 255, 256, 257, 65534, 65535, 65536)


def strings() -> list[str]:
    values = [
        "",
        "\x00",
        "\x00\x01",
        "a\x00b",
        "line\nbreak",
        "quote\"'\\",
        "\u007f",
        "\u0080",
        "\u07ff",
        "\u0800",
        "\uffff",
        "é",
        "e\u0301",
        "नमस्ते",
        "𝄞",
    ]
    for length in LENGTHS:
        values += ["a" * length, "é" * length, "占" * length, "😀" * length]
    return values


CONTAINERS = [
    [],
    (),
    {},
    [[]],
    [{}],
    {"a": {}, "b": []},
    {"a": {"b": {"c": [1, 2, {"d": b"x"}]}}},
    # `True` 与 `1` 在 Python 里是同一个键，不能同时出现在一个映射里。
    {1: "a", "1": "b", b"1": "c", None: "e", 1.5: "f", -1: "g"},
    {True: 1, False: 0, None: None},
    {"b": 1, "a": 2, "": 3, "ab": 4, "abc": 5, "aa": 6, "z": 7},
    {b"": 1, b"a": 2, b"ab": 3, b"aa": 4},
    {"é": 1, "a": 2, "😀": 3, "占": 4, "": 5},
    {index: index for index in [23, 24, 255, 256, 65535, 65536, 0, -1, -24, -25]},
    {"x": list(range(24)), "y": list(range(25))},
    [{"a": index} for index in range(30)],
    {"k": [{"a": [1, 2, 3]}, {"b": {"c": 1}}]},
]


def rand_str(rng: random.Random) -> str:
    length = rng.choice([0, 1, 2, 3, 5, 10, 23, 24, 25, 40])
    alphabet = "abcXYZ019_é占😀 \x00"
    return "".join(rng.choice(alphabet) for _ in range(length))


def rand_val(rng: random.Random, bases: list[int], depth: int = 0) -> Any:
    kinds = ["int", "float", "str", "bytes", "bool", "none"]
    if depth < 3:
        kinds += ["list", "dict", "tuple"]
    kind = rng.choice(kinds)
    if kind == "int":
        return rng.choice([rng.randint(-(2**63), 2**63), rng.randint(-300, 300), rng.choice(bases)])
    if kind == "float":
        return rng.choice(
            [
                rng.uniform(-1e6, 1e6),
                rng.uniform(-1, 1),
                struct.unpack(">d", struct.pack(">Q", rng.getrandbits(64)))[0],
            ]
        )
    if kind == "str":
        return rand_str(rng)
    if kind == "bytes":
        return bytes(rng.getrandbits(8) for _ in range(rng.choice([0, 1, 3, 24, 300])))
    if kind == "bool":
        return rng.choice([True, False])
    if kind == "none":
        return None
    if kind == "list":
        return [rand_val(rng, bases, depth + 1) for _ in range(rng.randint(0, 5))]
    if kind == "tuple":
        return tuple(rand_val(rng, bases, depth + 1) for _ in range(rng.randint(0, 4)))
    return {rand_str(rng): rand_val(rng, bases, depth + 1) for _ in range(rng.randint(0, 5))}


def main() -> int:
    int_values = ints()
    for value in int_values:
        check(value, f"int {value}")
    for value in floats():
        check(value, f"float {value!r}")
    for text in strings():
        check(text, f"str utf8-len {len(text.encode('utf-8'))}")
    for length in LENGTHS:
        payload = bytes((index * 37 + 11) & 0xFF for index in range(length))
        check(payload, f"bytes len {length}")
        check(bytearray(payload), f"bytearray len {length}")
        check_unsupported(memoryview(payload), f"memoryview len {length}")
        check([0] * length, f"list len {length}")
        check(tuple([0] * length), f"tuple len {length}")
        check({index: index for index in range(length)}, f"map int-key len {length}")
        check({f"k{index}": index for index in range(length)}, f"map str-key len {length}")
    for value in (2**64, 2**64 + 1, -(2**64) - 1):
        check_unsupported(value, f"bignum {value}")
    for value in CONTAINERS:
        check(value, f"container {value!r}"[:120])
    rng = random.Random(20261101)
    for index in range(5000):
        check(rand_val(rng, int_values), f"fuzz {index}")

    print(f"checked {COUNT} values, byte-equal {COMPARED}, by-design rejects {len(UNSUPPORTED)}")
    if UNSUPPORTED:
        print("  by-design rejects（断言抛 CBORError）: " + ", ".join(UNSUPPORTED[:4]) + " …")
    for failure in FAILS[:40]:
        print("MISMATCH:", failure, file=sys.stdout)
    if FAILS:
        print(f"gate:cbor: FAILED — {len(FAILS)} 处不一致", file=sys.stdout)
        return 1
    print("gate:cbor: ok — _cbor 与 cbor2 canonical 逐字节一致（含 NaN / 长度头 / 负数）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

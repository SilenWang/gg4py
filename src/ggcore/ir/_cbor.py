"""IR 线格式的最小 canonical CBOR 编解码器（纯 Python）。

为什么要有它：Pyodide 的包索引里没有 `cbor2`，PyPI 上也只有编译好的平台轮子
（6.x 是 Rust 实现，源码包在 wasm 上编不出来），所以浏览器里的 `ggcore` 拿不到
`cbor2`。
`codec.py` 在 `import cbor2` 失败时退回到本模块，接口与用到的子集一致
（`dumps(obj, canonical=True)` / `loads(bytes)`），线格式一个字节都不变。

口径只覆盖 IR 实际用到的类型：dict / list / tuple / str / bytes / int /
float / bool / None。浮点写「能逐位还原的最短宽度」（half → single → double），
NaN 一律写首选编码 `f97e00`（符号位与 payload 都丢掉），这也是
`cbor2.dumps(..., canonical=True)` 6.1.5 的行为；`pixi run gate:pyodide` 与
`pixi run gate:cbor` 用真实 `cbor2` 的输出逐字节守住这两条。

canonical 规则（RFC 8949 §4.2.1）：整数与长度用最短编码；映射的键按
「编码后字节长度，再按字节序」排序。不定长与 tag 一律不支持：IR 不写它们，
读不懂的东西不该猜。超 64 位整数要写 bignum tag（2/3），所以 `_cbor` 拒绝它们，
由 IR 层在构造节点时就把 `int` 参数收进 64 位（`nodes.INT_MIN` / `INT_MAX`）——
这样「CPython 能 encode 的 scene，Pyodide 也能 encode 且能 decode 回来」不是靠
两边碰巧一致，而是格式上不存在这种输入。

`memoryview` 也**不支持**（直接报错）：`cbor2` 6.1.5 把 `memoryview` 编成整数数组
而不是 byte string，保留一条会写出两边不一致的字节；IR 编码路径从不传它，所以
这里选择「不认」，而不是「认错」。
"""

from __future__ import annotations

import math
import struct
from typing import Any

__all__ = ["dumps", "loads"]


class CBORError(ValueError):
    """本模块解不出来的字节。"""


def _head(buf: bytearray, major: int, value: int) -> None:
    if value < 0:
        raise CBORError(f"长度不能为负：{value}")
    if value < 24:
        buf.append((major << 5) | value)
    elif value < 1 << 8:
        buf.append((major << 5) | 24)
        buf.append(value)
    elif value < 1 << 16:
        buf.append((major << 5) | 25)
        buf += struct.pack(">H", value)
    elif value < 1 << 32:
        buf.append((major << 5) | 26)
        buf += struct.pack(">I", value)
    elif value < 1 << 64:
        buf.append((major << 5) | 27)
        buf += struct.pack(">Q", value)
    else:
        raise CBORError(f"整数超出 64 位（本模块不写 bignum tag）：{value}")


def _encode(obj: Any, buf: bytearray) -> None:
    # bool 是 int 的子类，必须先判；StrEnum 是 str 的子类，按文本写。
    if obj is None:
        buf.append(0xF6)
    elif obj is True:
        buf.append(0xF5)
    elif obj is False:
        buf.append(0xF4)
    elif isinstance(obj, str):
        data = obj.encode("utf-8")
        _head(buf, 3, len(data))
        buf += data
    elif isinstance(obj, (bytes, bytearray)):
        data = bytes(obj)
        _head(buf, 2, len(data))
        buf += data
    elif isinstance(obj, int):
        if obj >= 0:
            _head(buf, 0, obj)
        else:
            _head(buf, 1, -1 - obj)
    elif isinstance(obj, float):
        buf += _float(obj)
    elif isinstance(obj, (list, tuple)):
        _head(buf, 4, len(obj))
        for item in obj:
            _encode(item, buf)
    elif isinstance(obj, dict):
        items = [(_dumps(key), value) for key, value in obj.items()]
        items.sort(key=lambda kv: (len(kv[0]), kv[0]))
        _head(buf, 5, len(items))
        for encoded_key, value in items:
            buf += encoded_key
            _encode(value, buf)
    else:
        raise CBORError(f"不支持的类型：{type(obj).__name__}")


def _dumps(obj: Any) -> bytes:
    buf = bytearray()
    _encode(obj, buf)
    return bytes(buf)


def _float(value: float) -> bytes:
    """最短且能逐位还原的浮点编码（canonical 的浮点规则）。"""
    # NaN 没有「逐位还原」可言，canonical 只留一个首选编码（RFC 8949 §3.3）：
    # 正负号的 NaN、带 payload 的 NaN 全部归一成 f97e00，与 cbor2 一致。
    if math.isnan(value):
        return b"\xf9\x7e\x00"
    double = struct.pack(">d", value)
    for marker, code in ((0xF9, ">e"), (0xFA, ">f")):
        try:
            packed = struct.pack(code, value)
        except (OverflowError, struct.error):
            continue
        if struct.pack(">d", struct.unpack(code, packed)[0]) == double:
            return bytes((marker,)) + packed
    return b"\xfb" + double


def dumps(obj: Any, *, canonical: bool = True) -> bytes:
    """编码为 canonical CBOR。`canonical` 只为对齐 `cbor2.dumps` 的签名。"""
    if not canonical:
        raise ValueError("_cbor 只实现 canonical 编码")
    return _dumps(obj)


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def take(self, count: int) -> bytes:
        end = self.pos + count
        if end > len(self.data):
            raise CBORError("字节流提前结束")
        chunk = self.data[self.pos : end]
        self.pos = end
        return chunk

    def byte(self) -> int:
        return self.take(1)[0]

    def length(self, extra: int) -> int:
        if extra < 24:
            return extra
        if extra == 24:
            return self.byte()
        if extra == 25:
            return struct.unpack(">H", self.take(2))[0]
        if extra == 26:
            return struct.unpack(">I", self.take(4))[0]
        if extra == 27:
            return struct.unpack(">Q", self.take(8))[0]
        if extra == 31:
            raise CBORError("不定长编码不在 IR 线格式里")
        raise CBORError(f"保留的长度编码：{extra}")

    def item(self) -> Any:
        first = self.byte()
        major, extra = first >> 5, first & 0x1F
        if major == 0:
            return self.length(extra)
        if major == 1:
            return -1 - self.length(extra)
        if major == 2:
            return self.take(self.length(extra))
        if major == 3:
            try:
                return self.take(self.length(extra)).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise CBORError(f"文本不是合法 UTF-8：{exc}") from exc
        if major == 4:
            return [self.item() for _ in range(self.length(extra))]
        if major == 5:
            return {self.item(): self.item() for _ in range(self.length(extra))}
        if major == 6:
            raise CBORError("tag 不在 IR 线格式里")
        return self._simple(extra)

    def _simple(self, extra: int) -> Any:
        if extra == 20:
            return False
        if extra == 21:
            return True
        if extra == 22:
            return None
        if extra == 25:
            return struct.unpack(">e", self.take(2))[0]
        if extra == 26:
            return struct.unpack(">f", self.take(4))[0]
        if extra == 27:
            return struct.unpack(">d", self.take(8))[0]
        raise CBORError(f"不支持的简单值：{extra}")


def loads(data: bytes | bytearray | memoryview) -> Any:
    """解码 canonical CBOR，要求整个输入恰好是一个对象。"""
    raw = bytes(data)
    reader = _Reader(raw)
    value = reader.item()
    if reader.pos != len(raw):
        raise CBORError(f"末尾还有 {len(raw) - reader.pos} 个多余字节")
    return value

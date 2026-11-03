"""最小 PNG 编码（`geom_raster` 的位图路径，M2-S2）。

IR 的 `raster` 节点只认一个字节串 + mime（`docs/notes/ir.md` §4），而 ggcore
的门禁只允许标准库 / numpy，所以这里用 `zlib`（标准库）手写一个 8 位 RGBA PNG：

- 每行一个 filter byte `0`（None），像素按 RGBA 原样；
- `zlib.compress(level=9)` 写 IDAT，块顺序 IHDR / IDAT / IEND；
- 输出对同一份像素**逐字节确定**（IR 的 blob id 是 sha256，确定性门禁靠它）。

这不是通用图像库：只写不读、只支持 8 位 RGBA、无调色板 / 无隔行。
"""

from __future__ import annotations

import struct
import zlib

import numpy as np

__all__ = ["encode_rgba", "png_bytes"]

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def encode_rgba(width: int, height: int, pixels: np.ndarray) -> bytes:
    """`(height, width, 4)` 的 uint8 像素 → PNG 字节。"""
    if width < 1 or height < 1:
        raise ValueError(f"PNG 尺寸必须 ≥ 1，收到 {width}×{height}")
    data = np.asarray(pixels)
    if data.shape != (height, width, 4):
        raise ValueError(f"像素形状必须是 ({height}, {width}, 4)，收到 {data.shape}")
    raw = b"".join(b"\x00" + row.tobytes() for row in data.astype(np.uint8, copy=False))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        _PNG_SIGNATURE
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


#: 另一种叫法（节点参数里写的是「位图路径」，读起来顺一点）。
png_bytes = encode_rgba

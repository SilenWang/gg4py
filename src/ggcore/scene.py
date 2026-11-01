"""占位 scene IR。

真正的 IR 在后续阶段落地；这里先给确定性门禁（X1）一个真实的、字节稳定的
载荷：同一份 `Scene` 序列化两次必须是同一串字节。约定：

- bulk 数据一律 float32 小端缓冲，逐元素 JSON 在 `src/ggcore/` 内被门禁禁止；
- 线格式自带版本号与长度前缀，便于以后做前后兼容；
- 字符串按 UTF-8 长度前缀写入，不依赖字典顺序。
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass

WIRE_VERSION = 1
_MAGIC = b"GGSC"


@dataclass(frozen=True)
class Scene:
    """一张图的已解析几何（M0 占位版本：只有画布与点/文字）。"""

    width: float = 640.0
    height: float = 480.0
    # 交错存放的 x, y；上线时统一压成 float32。
    points: tuple[float, ...] = ()
    labels: tuple[str, ...] = ()

    def to_bytes(self) -> bytes:
        """序列化为确定性字节串（同输入同字节）。"""
        out = bytearray()
        out += _MAGIC
        out += struct.pack("<HH", WIRE_VERSION, 0)
        out += struct.pack("<ff", self.width, self.height)
        out += struct.pack("<I", len(self.points))
        if self.points:
            out += struct.pack(f"<{len(self.points)}f", *self.points)
        out += struct.pack("<I", len(self.labels))
        for label in self.labels:
            raw = label.encode("utf-8")
            out += struct.pack("<I", len(raw))
            out += raw
        return bytes(out)

    def digest(self) -> str:
        """`to_bytes()` 的 sha256，用于确定性门禁与基准用例。"""
        return hashlib.sha256(self.to_bytes()).hexdigest()


def placeholder_scene() -> Scene:
    """门禁与基准共用的占位 scene：内容固定，不含任何环境相关输入。"""
    return Scene(
        width=640.0,
        height=480.0,
        points=tuple(float(i) * 0.5 for i in range(64)),
        labels=("gg4py", "占位", "M0-1"),
    )

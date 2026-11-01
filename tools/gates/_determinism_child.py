"""X1 门禁的子进程：编码真实 IR scene 并把摘要打到 stdout。

由 `check_determinism.py` 以不同 `PYTHONHASHSEED` 起两次，两边的 stdout 必须
逐字节相同，否则说明 IR 序列化吃了哈希顺序或进程状态。载荷是
`ggcore.ir.demo_scene()`（嵌套视口 + path + text + raster blob + zeroGrob），
不再是 M0-1 的占位结构。
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ggcore import __version__
from ggcore.ir import IR_VERSION_STR, decode, demo_scene, encode


def main() -> int:
    scene = demo_scene()
    # 同一进程内重复调用也必须稳定。
    payloads = {encode(scene) for _ in range(3)}
    if len(payloads) != 1:
        print(f"error=in-process-mismatch {sorted(len(p) for p in payloads)}")
        return 1
    data = payloads.pop()
    # 解码再编码也要回到同一串字节，否则“编码 + 解码”合起来就不确定。
    if encode(decode(data)) != data:
        print("error=round-trip-mismatch")
        return 1
    print(f"version={__version__}")
    print(f"ir_version={IR_VERSION_STR}")
    print(f"digest={hashlib.sha256(data).hexdigest()}")
    print(f"bytes={len(data)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

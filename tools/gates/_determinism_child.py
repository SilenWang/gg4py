"""X1 门禁的子进程：序列化占位 scene 并把摘要打到 stdout。

由 `check_determinism.py` 以不同 `PYTHONHASHSEED` 起两次，两边的 stdout 必须
逐字节相同，否则说明 IR 序列化吃了哈希顺序或进程状态。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ggcore import Scene, __version__, placeholder_scene


def main() -> int:
    scene: Scene = placeholder_scene()
    # 同一进程内重复调用也必须稳定。
    digests = {scene.digest() for _ in range(3)}
    if len(digests) != 1:
        print(f"error=in-process-mismatch {sorted(digests)}")
        return 1
    digest = digests.pop()
    print(f"version={__version__}")
    print(f"digest={digest}")
    print(f"bytes={len(scene.to_bytes())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

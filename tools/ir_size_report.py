"""10k 点 path 的 IR 体积 vs 逐元素 JSON 体积（`docs/notes/ir.md` 的数字来源）。

    pixi run ir:size

JSON 侧给三种写法，差异只在“一条顶点占多少字节”：

- `pairs`：`[[x, y], …]`，数值按 float64 的完整十进制写出（信息无损）；
- `objects`：`[{"x": x, "y": y}, …]`，每点带字段名；
- `pairs-4dp`：`[[round(x, 4), round(y, 4)], …]`，**会丢精度**，只用来量化
  “JSON 想变小要付出什么代价”。
"""

from __future__ import annotations

import json

import numpy as np

from ggcore.ir import Gpar, Node, NodeKind, Scene, encode, f32

COUNT = 10_000


def build_scene() -> tuple[Scene, np.ndarray]:
    rng = np.random.default_rng(7)
    points = np.column_stack([rng.normal(size=COUNT), rng.normal(size=COUNT)]).astype(np.float32)
    root = Node(
        NodeKind.VIEWPORT,
        params={"name": "root", "clip": False},
        children=(
            Node(
                NodeKind.PATH,
                Gpar(col=(31, 119, 180, 255)),
                bufs={"points": f32(points)},
            ),
        ),
    )
    return Scene(root=root), points


def json_size(points: np.ndarray, style: str) -> int:
    if style == "pairs":
        payload = [[float(x), float(y)] for x, y in points]
    elif style == "objects":
        payload = [{"x": float(x), "y": float(y)} for x, y in points]
    elif style == "pairs-4dp":
        payload = [[round(float(x), 4), round(float(y), 4)] for x, y in points]
    else:  # pragma: no cover - 只是脚本内部枚举
        raise ValueError(style)
    return len(json.dumps(payload, separators=(",", ":")).encode())


def main() -> int:
    scene, points = build_scene()
    data = encode(scene)
    print(f"points                : {COUNT}")
    print(f"IR (CBOR + float32)   : {len(data):>9,} B  ({len(data) / COUNT:5.2f} B/point)")
    for style in ("pairs", "objects", "pairs-4dp"):
        size = json_size(points, style)
        print(
            f"JSON {style:<16}: {size:>9,} B  ({size / COUNT:5.2f} B/point)"
            f"  → IR 小 {size / len(data):.2f}×"
        )
    # base64 是 JSON 里塞同一份 float32 位串的最好情况：33% 膨胀，仍比 CBOR 大。
    base64_bytes = (len(points) * 8 + 2) // 3 * 4
    print(
        f"JSON base64(float32)  : {base64_bytes:>9,} B  ({base64_bytes / COUNT:5.2f} B/point)"
        f"  → IR 小 {base64_bytes / len(data):.2f}×"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

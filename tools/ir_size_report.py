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

import cbor2
import numpy as np

from ggcore.fills import pattern_rect
from ggcore.ir import (
    Gpar,
    LinearGradient,
    Node,
    NodeKind,
    RadialGradient,
    Scene,
    TilePattern,
    encode,
    f32,
)

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


def _fill_scene(fill: object) -> Scene:
    """一张最小场景：一个 rect 带这条 fill（§10.1 的量法）。"""
    node = Node(
        NodeKind.RECT,
        gpar=Gpar(fill=fill),
        bufs={"rect": f32([[0.0, 0.0, 10.0, 10.0]])},
    )
    root = Node(
        NodeKind.VIEWPORT,
        params={"name": "page", "clip": False},
        children=(node,),
    )
    return Scene(root=root)


def _fill_wire(fill: object) -> object:
    """从编码后的 payload 里取回这条 fill 的线格式对象（就是实际写出去的东西）。"""
    payload = cbor2.loads(encode(_fill_scene(fill)))
    return payload["scene"]["root"]["children"][0]["gpar"]["fill"]


def _stops(count: int) -> list[tuple[float, tuple[int, int, int, int]]]:
    palette = [(228, 87, 86, 255), (244, 165, 130, 255), (76, 120, 168, 255), (0, 0, 0, 255)]
    return [(index / (count - 1), palette[index % len(palette)]) for index in range(count)]


def fill_sizes() -> list[tuple[str, int, int, int]]:
    """§10.1 的体积表：(说明, fill 值字节, gpar 段字节, 逐档 JSON 字节)。

    - **fill 值**：`gpar.fill` 这个值本身的 canonical CBOR（含 `kind` / `extend` /
      `stops` 缓冲，不含承载它的 `fill` 键名）；
    - **gpar 段**：真实节点里新增的 `"gpar": {"fill": …}` 总字节（键名 + 映射头）；
    - **逐档 JSON**：同一条 fill 写成 JSON 文本的字节（`{"kind":…,"stops":[…]}`），
      色标是逐档 `{"offset":…,"colour":[r,g,b,a]}`。
    """
    rows: list[tuple[str, object]] = [
        ("纯色 [r, g, b, a]", (228, 87, 86, 255)),
        ("2 档线性渐变", LinearGradient(stops=_stops(2), start=(0.0, 0.0), end=(10.0, 0.0))),
        ("3 档线性渐变", LinearGradient(stops=_stops(3), start=(0.0, 0.0), end=(10.0, 0.0))),
        ("10 档线性渐变", LinearGradient(stops=_stops(10), start=(0.0, 0.0), end=(10.0, 0.0))),
        ("3 档径向渐变", RadialGradient(stops=_stops(3), center=(5.0, 5.0), radius=4.0)),
        (
            "图案（1 个内容矩形）",
            TilePattern(
                content=(pattern_rect((0.0, 0.0, 4.0, 4.0), "#E45756"),),
                size=(8.0, 8.0),
                origin=(0.0, 0.0),
            ),
        ),
    ]
    table: list[tuple[str, int, int, int]] = []
    for label, fill in rows:
        wire = _fill_wire(fill)
        bare = len(cbor2.dumps(wire, canonical=True))
        gpar = len(cbor2.dumps({"gpar": {"fill": wire}}, canonical=True))
        if isinstance(fill, tuple) or isinstance(fill, TilePattern):
            json_size = 0  # 纯色没有色标；图案的体积由内容节点决定
        else:
            json_size = len(
                json.dumps(wire_deep(wire), separators=(",", ":"), ensure_ascii=False).encode()
            )
        table.append((label, bare, gpar, json_size))
    return table


def wire_deep(value: object) -> object:
    """把色标缓冲换成逐档 JSON，好回答「同一份内容写成 JSON 多大」。"""
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        if value.get("dtype") == "f4" and "data" in value:
            rows = np.frombuffer(value["data"], dtype="<f4")
            rows = rows.reshape(tuple(value["shape"]))
            return [
                {"offset": round(float(row[0]), 6), "colour": [int(round(v)) for v in row[1:]]}
                for row in rows
            ]
        return {key: wire_deep(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [wire_deep(item) for item in value]
    return value


def print_fill_sizes() -> None:
    print()
    print("fill 段体积（docs/notes/ir.md §10.1）")
    print(f"{'fill':<22}{'fill 值':>10}{'gpar 段':>10}{'逐档 JSON':>12}")
    for label, bare, gpar, json_bytes in fill_sizes():
        json_cell = f"{json_bytes:,}" if json_bytes else "—"
        print(f"{label:<22}{bare:>10}{gpar:>10}{json_cell:>12}")


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
    print_fill_sizes()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

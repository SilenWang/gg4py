"""组合层的性能与 IR 体积记录（SIL-1001 / M3-1）。

    pixi run compose:report

4 / 9 个同构子图（200 点散点）的 `gtable()`（构建 + resolve + 渲染树）、
`to_scene()` 与 CBOR IR 体积；外加 SIL-1004 的 5 图
`2×2 + insert_bottom + panel_spacing(6mm)` 组合。数字写进
`docs/notes/composition.md` §7；这个脚本只负责复现，不参与门禁（机器差异不该
决定红绿）。
"""

from __future__ import annotations

import argparse
import time

import gg4py
from ggcore.ir import encode
from ggio.frame import from_dict
from ggskia.text import ShaperMetrics


def _plots(count: int):
    data = from_dict(
        {
            "x": list(range(200)),
            "y": [index * 0.5 for index in range(200)],
            "g": ["a", "b"] * 100,
        }
    )
    return [gg4py.ggplot(data, gg4py.aes(x="x", y="y")) + gg4py.geom_point() for _ in range(count)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=float, default=7.0, help="页面边长（in）")
    args = parser.parse_args()
    metrics = ShaperMetrics()
    for count, ncol in ((4, 2), (9, 3)):
        combined = gg4py.wrap_plots(*_plots(count), ncol=ncol)
        start = time.perf_counter()
        combined.gtable(metrics=metrics, width_in=args.size, height_in=args.size)
        gtable_ms = (time.perf_counter() - start) * 1000.0
        start = time.perf_counter()
        scene = combined.to_scene(metrics=metrics, width_in=args.size, height_in=args.size)
        scene_ms = (time.perf_counter() - start) * 1000.0
        start = time.perf_counter()
        payload = encode(scene)
        encode_ms = (time.perf_counter() - start) * 1000.0
        print(
            f"n={count:<2d} ncol={ncol}  gtable={gtable_ms:6.0f}ms  "
            f"scene={scene_ms:6.0f}ms  ir={len(payload):7d}B  encode={encode_ms:5.1f}ms"
        )

    # SIL-1004：insert_* + panel_spacing 不新增渲染阶段，量一次组合开销。
    base = gg4py.wrap_plots(*_plots(4), ncol=2)
    combined = gg4py.insert_bottom(base, _plots(1)[0], height=1)
    combined = gg4py.set_panel_spacing(combined, 6)
    start = time.perf_counter()
    combined.gtable(metrics=metrics, width_in=args.size, height_in=args.size)
    gtable_ms = (time.perf_counter() - start) * 1000.0
    start = time.perf_counter()
    scene = combined.to_scene(metrics=metrics, width_in=args.size, height_in=args.size)
    scene_ms = (time.perf_counter() - start) * 1000.0
    payload = encode(scene)
    print(
        f"n=5  insert+spacing  gtable={gtable_ms:6.0f}ms  "
        f"scene={scene_ms:6.0f}ms  ir={len(payload):7d}B"
    )


if __name__ == "__main__":
    main()

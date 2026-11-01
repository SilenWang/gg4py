"""IR v0 · 门禁与基准共用的演示 scene。

内容是固定算术，不含随机数、时间戳或任何环境输入，所以“同输入同字节”在
`PYTHONHASHSEED` 不同的进程之间也成立。它刻意把节点类型表的几个面都铺开：
嵌套视口（带旋转变换 + 裁剪）、gTree、多条子路径的 path、带最终宽度的 text、
带 blob 的 raster、zeroGrob。

真正的绘图在 M1 之后才有；这里的 text 宽度是构造出来的占位值，不代表度量口径
（口径见 `docs/notes/metrics-ledger.md` L1：真实宽度来自渲染端）。
"""

from __future__ import annotations

import numpy as np

from ggcore.ir.nodes import (
    Anchor,
    Baseline,
    BlobTable,
    FillRule,
    Gpar,
    Node,
    NodeKind,
    Scene,
    f32,
    i32,
)

#: 演示用位图：不追求能解码，只要字节稳定、够大，能覆盖 blob 表的编码路径。
_DEMO_RASTER = bytes(range(256)) * 4


def demo_scene() -> Scene:
    """返回固定的演示 scene（约 200 个顶点 + 1 个 blob）。"""
    count = 200
    step = np.arange(count, dtype=np.float32)
    x = step * np.float32(3.0) + np.float32(0.5)
    y = (step * np.float32(1.25)) % np.float32(97.0)
    curve = np.column_stack([x, y]).astype(np.float32)
    # 前 100 个点和后 100 个点分成两条子路径。
    ids = i32(np.repeat(np.array([0, 1], dtype=np.int32), count // 2))

    blobs, raster_id = BlobTable.empty().add(_DEMO_RASTER, "image/png")

    panel = Node(
        NodeKind.VIEWPORT,
        params={
            "name": "panel",
            "clip": True,
            "transform": (0.8, 0.0, 0.0, 0.8, 40.0, 20.0),
        },
        bufs={"clip_rect": f32([[0.0, 0.0, 600.0, 480.0]])},
        children=(
            Node(
                NodeKind.GTREE,
                params={"name": "panel-grobs"},
                children=(
                    Node(
                        NodeKind.RECT,
                        Gpar(fill=(255, 255, 255, 255), col=(40, 40, 40, 255), lwd=0.5),
                        bufs={"rect": f32([[0.0, 0.0, 600.0, 480.0]])},
                    ),
                    Node(
                        NodeKind.PATH,
                        Gpar(col=(31, 119, 180, 255), lwd=1.5, lty=(4.0, 2.0)),
                        params={"rule": FillRule.EVENODD},
                        bufs={"points": f32(curve), "id": ids},
                    ),
                    Node(
                        NodeKind.TEXT,
                        Gpar(col=(10, 10, 10, 255)),
                        params={
                            "font": "DejaVu Sans",
                            "size": 11.0,
                            "anchor": Anchor.LEFT,
                            "baseline": Baseline.ALPHABETIC,
                        },
                        bufs={
                            "pos": f32([[24.0, 36.0], [24.0, 52.0]]),
                            "width": f32([37.5, 61.25]),
                        },
                        texts=("gg4py IR v0", "占位"),
                    ),
                    Node(NodeKind.ZERO, params={}),
                ),
            ),
        ),
    )

    raster = Node(
        NodeKind.RASTER,
        params={"blob": raster_id, "width": 32, "height": 32},
        bufs={"rect": f32([[520.0, 400.0, 600.0, 480.0]])},
    )

    root = Node(
        NodeKind.VIEWPORT,
        params={"name": "root", "clip": False},
        children=(panel, raster),
    )
    return Scene(root=root, size=(640.0, 480.0), blobs=blobs)

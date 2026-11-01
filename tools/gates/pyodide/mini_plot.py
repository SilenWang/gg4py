"""M0-10 · 一份最小 plot 定义 → IR scene（两端共用的同一份代码）。

输入是 `plot.json`（一份手写的极小 plot 定义：数据点、标签、画布尺寸），输出是
`ggcore.ir.Scene`。CPython 与 Pyodide 跑的是同一个模块、同一份 JSON，所以两边
`encode()` 的字节必须逐位相同——`pixi run gate:pyodide` 守的就是这条。

这里只做到「图谱」为止：数据 → 面板坐标 → 一条 path，加背景、网格、标题、刻度
标签、图例色块。真正的 plot 语法（scale / coord / theme / facet）是 M1 的事。

依赖面被刻意压到 ggcore + numpy：Pyodide 里没有别的可用。代价是文字宽度只能按
字符数构造（`0.55 × 字号 × 字符数`），和 `ggcore.ir.demo` 一样是占位值；真实宽度
来自渲染端（`docs/notes/metrics-ledger.md` L1）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from ggcore.ir import (
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

PLOT = Path(__file__).with_name("plot.json")

PAD = {"left": 48.0, "right": 16.0, "top": 28.0, "bottom": 40.0}
FONT = "DejaVu Sans"
LABEL_SIZE = 9.0

#: 图例色块：固定灰度斜坡，不追求能解码，只覆盖 blob / raster 的编码路径。
_SWATCH = bytes(range(144))


def load(path: Path = PLOT) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def text_width(text: str, size: float) -> float:
    """占位宽度：字符数 × 0.55em（真实宽度由渲染端给出，见模块说明）。"""
    return 0.55 * size * len(text)


def _text(labels: list[str], positions: list[list[float]], *, size: float, anchor: Anchor) -> Node:
    return Node(
        NodeKind.TEXT,
        Gpar(col=(40, 40, 40, 255)),
        params={
            "font": FONT,
            "size": size,
            "anchor": anchor,
            "baseline": Baseline.MIDDLE,
        },
        bufs={
            "pos": f32(positions),
            "width": f32([text_width(label, size) for label in labels]),
        },
        texts=tuple(labels),
    )


def build(spec: dict[str, Any]) -> Scene:
    width, height = (float(value) for value in spec["size"])
    panel_w = width - PAD["left"] - PAD["right"]
    panel_h = height - PAD["top"] - PAD["bottom"]

    xs = np.asarray(spec["x"], dtype=np.float64)
    ys = np.asarray(spec["y"], dtype=np.float64)
    x_min, x_max = float(xs.min()), float(xs.max())
    y_min, y_max = float(ys.min()), float(ys.max())

    # 面板内坐标：y 轴向下（IR 约定），数据 y 大的在上方。
    px = (xs - x_min) / (x_max - x_min) * panel_w
    py = (y_max - ys) / (y_max - y_min) * panel_h
    points = f32(np.column_stack([px, py]))

    # 三条水平网格线，一次 path 三条子路径（id 分组）。
    grid_y = [panel_h * fraction for fraction in (0.0, 0.5, 1.0)]
    grid = f32([[0.0, y] for y in grid_y] + [[panel_w, y] for y in grid_y])
    grid_id = i32(np.repeat(np.arange(3, dtype=np.int32), 2))

    tick_y = [panel_h * fraction for fraction in (1.0, 0.5, 0.0)]

    panel = Node(
        NodeKind.VIEWPORT,
        params={
            "name": "panel",
            "clip": True,
            "transform": (1.0, 0.0, 0.0, 1.0, PAD["left"], PAD["top"]),
        },
        bufs={
            "clip_rect": f32(
                [[PAD["left"], PAD["top"], PAD["left"] + panel_w, PAD["top"] + panel_h]]
            )
        },
        children=(
            Node(
                NodeKind.GTREE,
                params={"name": "panel-grobs"},
                children=(
                    Node(
                        NodeKind.RECT,
                        Gpar(fill=(255, 255, 255, 255), col=(120, 120, 120, 255), lwd=0.5),
                        bufs={"rect": f32([[0.0, 0.0, panel_w, panel_h]])},
                    ),
                    Node(
                        NodeKind.PATH,
                        Gpar(col=(200, 200, 200, 255), lwd=0.5),
                        params={"rule": FillRule.WINDING},
                        bufs={"points": grid, "id": grid_id},
                    ),
                    Node(
                        NodeKind.PATH,
                        Gpar(col=(31, 119, 180, 255), lwd=1.5, lty=(4.0, 2.0)),
                        params={"rule": FillRule.WINDING},
                        bufs={"points": points, "id": i32(np.zeros(len(px), dtype=np.int32))},
                    ),
                ),
            ),
        ),
    )

    # 刻度标签与标题：页面坐标，槽位固定，文字宽度只影响自身。
    y_labels = _text(
        spec["y_labels"],
        [[PAD["left"] - 6.0, PAD["top"] + y] for y in tick_y],
        size=LABEL_SIZE,
        anchor=Anchor.RIGHT,
    )
    x_step = panel_w / (len(spec["x_labels"]) - 1)
    x_labels = _text(
        spec["x_labels"],
        [[PAD["left"] + x_step * index, PAD["top"] + panel_h + 8.0] for index in range(3)],
        size=LABEL_SIZE,
        anchor=Anchor.CENTER,
    )
    title = _text(
        [spec["title"]],
        [[PAD["left"], PAD["top"] / 2]],
        size=11.0,
        anchor=Anchor.LEFT,
    )

    blobs, swatch_id = BlobTable.empty().add(_SWATCH, "image/png")
    right = width - PAD["right"]
    middle = PAD["top"] / 2
    swatch = Node(
        NodeKind.RASTER,
        params={"blob": swatch_id, "width": 12, "height": 12},
        bufs={"rect": f32([[right - 12.0, middle - 6.0, right, middle + 6.0]])},
    )

    root = Node(
        NodeKind.VIEWPORT,
        params={"name": "root", "clip": False},
        children=(panel, y_labels, x_labels, title, swatch),
    )
    return Scene(root=root, size=(width, height), blobs=blobs)

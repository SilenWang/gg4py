"""X1 门禁的子进程：编码真实 IR scene 并把摘要打到 stdout。

由 `check_determinism.py` 以不同 `PYTHONHASHSEED` 起两次，两边的 stdout 必须
逐字节相同，否则说明 IR 序列化吃了哈希顺序或进程状态。两份载荷：

1. `ggcore.ir.demo_scene()`（嵌套视口 + path + text + raster blob + zeroGrob）；
2. M1-11 的整页场景：2×2 分面 + colour 图例 + 标题 + 主轴（图例 key 走
   `Geom.draw()`，轴 / 图例的尺寸来自主题与内置度量）。guide / axis 的任何
   顺序依赖都会让第二份摘要在不同种子下分叉。
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import numpy as np

from ggcore import __version__, registry
from ggcore.data import Column, ColumnTable
from ggcore.geom.scene import scene_from_plot
from ggcore.ir import IR_VERSION_STR, decode, demo_scene, encode
from ggcore.plot import aes, ggplot


def plot_scene():
    """M1-11 的整页场景（分面 + 图例 + 标题 + 主轴）。"""
    table = ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]))),
            ("y", Column("float", np.array([2.0, 4.0, 3.0, 5.0, 6.0, 7.0]))),
            (
                "g",
                Column(
                    "categorical",
                    np.array([0, 1, 2, 0, 1, 2], dtype=np.int32),
                    levels=("a", "b", "c"),
                ),
            ),
            (
                "f",
                Column(
                    "categorical",
                    np.array([0, 0, 1, 1, 1, 0], dtype=np.int32),
                    levels=("p", "q"),
                ),
            ),
        ]
    )
    plot = (
        ggplot(table, aes(x="x", y="y", colour="g"))
        + registry.geom_point()
        + registry.facet_wrap(("f",), ncol=2)
        + registry.labs(title="T", x="X", y="Y")
    )
    return scene_from_plot(plot, width_in=6.0, height_in=4.0)


def stable_encode(scene, label: str) -> bytes | None:
    payloads = {encode(scene) for _ in range(3)}
    if len(payloads) != 1:
        print(f"error={label}-in-process-mismatch {sorted(len(p) for p in payloads)}")
        return None
    data = payloads.pop()
    if encode(decode(data)) != data:
        print(f"error={label}-round-trip-mismatch")
        return None
    return data


def main() -> int:
    demo = stable_encode(demo_scene(), "demo")
    if demo is None:
        return 1
    # 构建也要稳定：两次 build + 装配出的场景字节必须一致。
    first_scene = plot_scene()
    second_scene = plot_scene()
    if encode(first_scene) != encode(second_scene):
        print("error=plot-build-mismatch")
        return 1
    plot = stable_encode(first_scene, "plot")
    if plot is None:
        return 1
    print(f"version={__version__}")
    print(f"ir_version={IR_VERSION_STR}")
    print(f"digest={hashlib.sha256(demo).hexdigest()}")
    print(f"bytes={len(demo)}")
    print(f"plot_digest={hashlib.sha256(plot).hexdigest()}")
    print(f"plot_bytes={len(plot)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

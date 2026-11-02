"""M1-13 查看器夹具：2×2 分面 + colour 图例的一张整页场景。

同一份素材给三处用：

- `tools/viewer/export_scene.py` 导出 `.ggir.cbor` 供浏览器手测 / 截图；
- `tests/test_viewer.py` 把它喂给 Playwright；
- 文档 `docs/notes/viewer.md` 里的映射表按这张图的节点结构写。

口径与 `tools/gates/_determinism_child.py` 的 `plot_scene()` 一致（分面 + 图例 +
标题 + 主轴），只是把分面做成真正的 2×2（4 个 level、`ncol = 2`），这样
`panel-1-1` / `panel-2-1` / `panel-1-2` / `panel-2-2` 四种视口名都会出现。
"""

from __future__ import annotations

import numpy as np

from ggcore import ir, registry
from ggcore.data import Column, ColumnTable
from ggcore.geom.scene import scene_from_plot
from ggcore.plot import aes, ggplot

__all__ = ["FACET_LEVELS", "GROUP_LEVELS", "facet_legend_plot", "facet_legend_scene"]

GROUP_LEVELS = ("a", "b", "c")
FACET_LEVELS = ("p", "q", "r", "s")
WIDTH_IN = 7.0
HEIGHT_IN = 5.0


def facet_legend_table() -> ColumnTable:
    """16 行：4 个分面 × 4 个点，颜色分 3 组（图例 3 个 key）。"""
    x = [1.0, 2.0, 3.0, 4.0, 1.5, 2.5, 3.5, 4.5, 1.2, 2.2, 3.2, 4.2, 1.8, 2.8, 3.8, 4.8]
    y = [2.0, 4.0, 3.0, 5.0, 3.0, 5.5, 4.5, 6.5, 1.5, 3.5, 2.5, 4.5, 2.5, 4.5, 3.5, 5.5]
    group = [0, 1, 2, 0, 1, 2, 0, 1, 2, 0, 1, 2, 0, 1, 2, 0]
    facet = [0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3]
    return ColumnTable(
        [
            ("x", Column("float", np.array(x))),
            ("y", Column("float", np.array(y))),
            (
                "g",
                Column(
                    "categorical",
                    np.array(group, dtype=np.int32),
                    levels=GROUP_LEVELS,
                ),
            ),
            (
                "f",
                Column(
                    "categorical",
                    np.array(facet, dtype=np.int32),
                    levels=FACET_LEVELS,
                ),
            ),
        ]
    )


def facet_legend_plot() -> ggplot:
    return (
        ggplot(facet_legend_table(), aes(x="x", y="y", colour="g"))
        + registry.geom_point()
        + registry.facet_wrap(("f",), ncol=2)
        + registry.labs(title="facet + legend", x="x", y="y")
    )


def facet_legend_scene(
    *, width_in: float = WIDTH_IN, height_in: float = HEIGHT_IN, metrics: object = None
) -> ir.Scene:
    """`metrics` 不给时用 `ggcore.geom.scene` 的缺省估算（与 `render` 一致按需换真度量）。"""
    return scene_from_plot(
        facet_legend_plot(), width_in=width_in, height_in=height_in, metrics=metrics
    )

"""jitter：点绘制（抖动在 position 阶段）。

参考图由 `refs:geom` 的 `jitter_basic` 段生成：坐标已抖动好，位置用
`position = "identity"`，比的是 `GeomPoint` 的绘制路径；抖动本身归
position 任务（`geom_jitter(width=)` → `position_jitter(width=)`）。
"""

from ggcore.plot import (
    aes,
    geom_jitter,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.2, 0.25, 0.3, 0.6, 0.65, 0.9],
    "y": [0.3, 0.35, 0.28, 0.7, 0.75, 0.6],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_jitter(stat="identity", position="identity", size=3, colour="#4C78A8")
        + scale_x_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + scale_y_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": [4, 3]}

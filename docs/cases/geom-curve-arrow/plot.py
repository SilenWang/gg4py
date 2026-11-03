"""geom_curve：curvature = -0.4 + 单端开口箭头。

曲线的箭头切向由设备按采样后的端点求（曲线公式只在设备侧）。
"""

from ggcore.plot import (
    aes,
    arrow,
    geom_curve,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.1, 0.5],
    "y": [0.2, 0.55],
    "xend": [0.8, 0.9],
    "yend": [0.7, 0.25],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", xend="xend", yend="yend"))
        + geom_curve(
            curvature=-0.4,
            angle=90,
            ncp=5,
            linewidth=1.1 / 2.845276,
            colour="#4C78A8",
            arrow=arrow(length=0.12 * 72.0, ends="last", type="open"),
        )
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

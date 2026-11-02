"""scale：x 轴 log10（limits 给的是数据空间，变换后才落到面板）。"""

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    scale_x_log10,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [1, 3, 10, 30, 100, 300, 1000, 2, 20, 200],
    "y": [0.10, 0.25, 0.35, 0.50, 0.60, 0.75, 0.90, 0.18, 0.42, 0.68],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point(shape=19, size=3.2, colour="#4C78A8")
        + scale_x_log10(limits=(1, 1000), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

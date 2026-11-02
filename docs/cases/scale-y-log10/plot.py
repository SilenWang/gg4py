"""scale：y 轴 log10。"""

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    scale_x_continuous,
    scale_y_log10,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.10, 0.20, 0.35, 0.50, 0.65, 0.80, 0.90, 0.25, 0.75],
    "y": [1, 3, 10, 30, 100, 300, 1000, 2, 200],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point(shape=19, size=3.2, colour="#F58518")
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_log10(limits=(1, 1000), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

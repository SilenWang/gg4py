"""scale：连续 colour 的缺省渐变（`scale_colour_gradient`，Lab 插值）。

图例显式关掉：色条本身的可比性见 `guide-colourbar`（那条因为渐变条的渲染口径
标了 ci = false）。
"""

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.10, 0.20, 0.35, 0.50, 0.65, 0.80, 0.90, 0.25, 0.75],
    "y": [0.20, 0.50, 0.35, 0.70, 0.45, 0.80, 0.60, 0.85, 0.15],
    "v": [0.00, 0.12, 0.25, 0.38, 0.50, 0.62, 0.75, 0.88, 1.00],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="v"))
        + geom_point(shape=19, size=3.8)
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

"""scale：离散 colour 的缺省色板（hue_pal，不写 manual）。"""

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
    "x": [0.15, 0.35, 0.55, 0.75, 0.25, 0.45, 0.65, 0.85, 0.10, 0.60],
    "y": [0.20, 0.45, 0.30, 0.60, 0.75, 0.55, 0.80, 0.40, 0.50, 0.15],
    "g": ["a", "a", "b", "b", "c", "c", "a", "b", "c", "a"],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="g"))
        + geom_point(shape=19, size=3.6)
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

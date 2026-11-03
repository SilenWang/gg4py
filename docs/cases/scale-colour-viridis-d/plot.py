"""scale：离散 colour 用 viridis option D（带完整图例）。"""

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    scale_colour_viridis_d,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggio.frame import to_column_table

DATA = {
    "x": [0.12, 0.30, 0.52, 0.74, 0.22, 0.44, 0.66, 0.88, 0.18, 0.40, 0.60, 0.82],
    "y": [0.22, 0.48, 0.32, 0.66, 0.78, 0.56, 0.84, 0.42, 0.60, 0.28, 0.74, 0.50],
    "g": ["a", "a", "a", "b", "b", "b", "c", "c", "c", "d", "d", "d"],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="g"))
        + geom_point(shape=19, size=3.0)
        + scale_colour_viridis_d(option="D")
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

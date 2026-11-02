"""facet：`facet_grid(rows, cols)` 2×2 网格。"""

from ggcore.plot import (
    aes,
    facet_grid,
    geom_point,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.2, 0.6, 0.3, 0.7, 0.25, 0.65, 0.35, 0.75],
    "y": [0.3, 0.5, 0.6, 0.4, 0.55, 0.25, 0.45, 0.8],
    "r": ["t", "t", "t", "t", "u", "u", "u", "u"],
    "c": ["l", "l", "r", "r", "l", "l", "r", "r"],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point(shape=19, size=2.8, colour="#F58518")
        + facet_grid(rows="r", cols="c")
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

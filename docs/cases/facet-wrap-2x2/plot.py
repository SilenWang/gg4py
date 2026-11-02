"""facet：`facet_wrap(ncol = 2)` 四个面板（2×2），固定标度。"""

from ggcore.plot import (
    aes,
    facet_wrap,
    geom_point,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.2, 0.5, 0.8, 0.3, 0.6, 0.9, 0.15, 0.45, 0.75, 0.25, 0.55, 0.85],
    "y": [0.3, 0.6, 0.4, 0.7, 0.2, 0.8, 0.5, 0.65, 0.35, 0.45, 0.75, 0.55],
    "g": ["a", "a", "a", "b", "b", "b", "c", "c", "c", "d", "d", "d"],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point(shape=19, size=2.8, colour="#4C78A8")
        + facet_wrap("g", ncol=2)
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

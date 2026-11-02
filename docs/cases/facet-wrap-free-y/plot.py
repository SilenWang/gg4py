"""facet：`scales = "free_y"`（每个面板各自的 y 标度）。"""

from ggcore.plot import (
    aes,
    facet_wrap,
    geom_point,
    ggplot,
    scale_x_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.2, 0.5, 0.8, 0.3, 0.6, 0.9, 0.15, 0.45],
    "y": [1.0, 1.5, 1.2, 1.8, 10.0, 15.0, 12.0, 18.0],
    "g": ["a", "a", "a", "a", "b", "b", "b", "b"],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point(shape=19, size=2.8, colour="#4C78A8")
        + facet_wrap("g", ncol=2, scales="free_y")
        + scale_x_continuous(limits=(0.1, 0.9), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

"""facet：`scales = "free_x"`（每个面板各自的 x 标度）。"""

from ggcore.plot import (
    aes,
    facet_wrap,
    geom_point,
    ggplot,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.10, 0.20, 0.30, 0.15, 1.0, 1.4, 1.8, 2.2],
    "y": [0.2, 0.5, 0.35, 0.7, 0.3, 0.6, 0.45, 0.8],
    "g": ["a", "a", "a", "a", "b", "b", "b", "b"],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point(shape=19, size=2.8, colour="#54A24B")
        + facet_wrap("g", ncol=2, scales="free_x")
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

"""area：两组 x 对齐的堆叠面积（默认 stat_align + position_stack）。"""

from ggcore.plot import (
    aes,
    geom_area,
    ggplot,
    position_stack,
    scale_fill_discrete,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [1, 2, 3, 4, 1, 2, 3, 4],
    "y": [1.0, 1.5, 1.2, 1.8, 0.8, 0.6, 1.1, 0.9],
    "g": ["a", "a", "a", "a", "b", "b", "b", "b"],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", fill="g"))
        + geom_area(position=position_stack())
        + scale_fill_discrete(values={"a": "#4C78A8", "b": "#F58518"})
        + scale_x_continuous(limits=(0.5, 4.5), expand=(0, 0))
        + scale_y_continuous(limits=(0, 4), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

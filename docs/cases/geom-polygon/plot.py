"""geom_polygon：两个分组三角。

`fill` 吃 alpha；每组一只多边形（IR 的 polygon 一个节点一份 gp）。
"""

from ggcore.plot import (
    aes,
    geom_polygon,
    ggplot,
    scale_fill_discrete,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.1, 0.4, 0.35, 0.7, 0.85, 0.5],
    "y": [0.1, 0.15, 0.5, 0.55, 0.9, 0.6],
    "g": ["a", "a", "a", "b", "b", "b"],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", group="g", fill="g"))
        + geom_polygon(colour="#333333", linewidth=0.8 / 2.845276, alpha=0.8)
        + scale_fill_discrete(values={"a": "#4C78A8", "b": "#F58518"})
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

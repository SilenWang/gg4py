"""matrix：2×2 facet_wrap × coord_polar × 右侧单图例。"""

from ggcore.plot import (
    aes,
    coord_polar,
    facet_wrap,
    geom_point,
    ggplot,
    labs,
    scale_colour_discrete,
    theme_grey,
)
from ggcore.theme import theme as make_theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.15, 0.45, 0.75, 0.2, 0.5, 0.8, 0.25, 0.55, 0.85, 0.3, 0.6, 0.9],
    "y": [0.35, 0.7, 0.5, 0.6, 0.25, 0.75, 0.4, 0.8, 0.55, 0.65, 0.3, 0.7],
    "f": ["a", "a", "a", "b", "b", "b", "c", "c", "c", "d", "d", "d"],
    "r": ["t", "t", "t", "t", "t", "t", "u", "u", "u", "u", "u", "u"],
    "c": ["l", "l", "r", "r", "l", "l", "l", "l", "r", "r", "l", "r"],
    "g": ["p", "q", "p", "q", "p", "q", "p", "q", "p", "q", "p", "q"],
    "s": ["u", "u", "v", "v", "u", "v", "u", "v", "u", "v", "u", "v"],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="g"))
        + geom_point(shape=19, size=2.4)
        + scale_colour_discrete(values={"p": "#F8766D", "q": "#00BA38"})
        + facet_wrap("f", ncol=2)
        + coord_polar()
        + labs(title="matrix", x="x label", y="y label")
        + theme_grey()
        + make_theme(**{"legend.position": "right"})
    )
    return {"plot": p, "size": SIZE}

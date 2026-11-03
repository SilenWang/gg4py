"""matrix：2×2 facet_wrap × coord_polar × 上侧横排双图例。"""

from ggcore.plot import (
    aes,
    coord_polar,
    facet_wrap,
    geom_point,
    ggplot,
    guide_legend,
    guides,
    scale_colour_discrete,
    scale_shape_discrete,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
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
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="g", shape="s"))
        + geom_point(size=2.4)
        + scale_colour_discrete(values={"p": "#F8766D", "q": "#00BA38"})
        + scale_shape_discrete(values={"u": 16, "v": 17})
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + facet_wrap("f", ncol=2)
        + guides(
            colour=guide_legend(direction="horizontal"), shape=guide_legend(direction="horizontal")
        )
        + coord_polar()
        + theme_void()
        + make_theme(**{"legend.position": "top"})
    )
    return {"plot": p, "size": SIZE}

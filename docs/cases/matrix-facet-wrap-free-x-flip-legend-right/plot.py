"""matrix：facet_wrap(free_x) × coord_flip × 右侧单图例。"""

from ggcore.plot import (
    aes,
    coord_flip,
    facet_wrap,
    geom_point,
    ggplot,
    scale_colour_discrete,
    theme_void,
)
from ggcore.theme import theme as make_theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.1, 0.3, 0.6, 0.4, 0.7, 0.9, 10.0, 20.0, 30.0, 12.0, 25.0, 35.0],
    "y": [1.0, 3.0, 2.0, 2.0, 5.0, 4.0, 100.0, 300.0, 200.0, 150.0, 250.0, 180.0],
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
        + facet_wrap("f", ncol=2, scales="free_x")
        + coord_flip()
        + theme_void()
        + make_theme(**{"legend.position": "right"})
    )
    return {"plot": p, "size": SIZE}

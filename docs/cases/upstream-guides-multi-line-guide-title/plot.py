from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_colourbar,
    guide_legend,
    guides,
    labs,
    scale_colour_discrete,
    scale_fill_continuous,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 2, 3], "z": ["1", "2", "3"]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="z", fill="y"))
        + geom_point(shape=21)
        + guides(colour=guide_legend(order=2), fill=guide_colourbar(order=1))
        + theme_test()
        + labs(title="multi-line guide title works")
    )
    p = (
        p
        + scale_colour_discrete(name="the\ndiscrete\ncolorscale")
        + scale_fill_continuous(name="the\ncontinuous\ncolorscale")
    )
    return {"plot": p, "size": [10, 8]}

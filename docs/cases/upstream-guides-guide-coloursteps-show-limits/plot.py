from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_coloursteps,
    guides,
    labs,
    scale_colour_binned,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 4], "y": [6, 5, 7]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="x"))
        + geom_point()
        + scale_colour_binned(breaks=(1.5, 2, 3))
        + guides(colour=guide_coloursteps(show_limits=True))
        + theme_test()
        + labs(title="guide_coloursteps can show limits")
    )
    return {"plot": p, "size": [10, 8]}

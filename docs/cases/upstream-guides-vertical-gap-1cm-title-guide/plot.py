from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_colourbar,
    guide_legend,
    guides,
    labs,
)
from ggcore.theme import element_text, margin, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 2, 3], "z": ["1", "2", "3"]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="z", fill="y"))
        + geom_point(shape=21)
        + guides(colour=guide_legend(order=2), fill=guide_colourbar(order=1))
        + theme_test()
        + labs(title="vertical gap of 1cm between guide title and guide")
    )
    p = p + theme(**{"legend.title": element_text(margin=margin(b=1, unit="cm"))})
    return {"plot": p, "size": [10, 8]}

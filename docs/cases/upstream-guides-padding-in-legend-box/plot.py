from ggcore.plot import (
    aes,
    geom_bar,
    ggplot,
    guide_colourbar,
    guides,
    labs,
)
from ggcore.theme import element_rect, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": ["A", "B", "C"], "y": [1, 1, 1], "c": [1, 2, 3]}


def build():
    base = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", fill="x", colour="c"))
        + geom_bar(stat="identity")
        + guides(colour=guide_colourbar(order=1))
        + theme_test()
        + labs(title="padding in legend box")
        + theme(**{"legend.background": element_rect(colour="black")})
    )
    return {"plot": base, "size": [10, 8]}

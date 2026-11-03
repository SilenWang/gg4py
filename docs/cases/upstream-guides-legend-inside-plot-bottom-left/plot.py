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
        + labs(title="legend inside plot, bottom left")
        + theme(**{"legend.background": element_rect(colour="black")})
    )
    p = base + theme(
        **{
            "legend.position": "inside",
            "legend.justification": (0, 0),
            "legend.position.inside": (0, 0),
        }
    )
    return {"plot": p, "size": [10, 8]}

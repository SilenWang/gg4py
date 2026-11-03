from ggcore.plot import (
    aes,
    geom_bar,
    ggplot,
    guide_colourbar,
    guide_legend,
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
        + labs(title="legend inside plot, multiple positions")
        + theme(**{"legend.background": element_rect(colour="black")})
    )
    p = (
        base
        + theme(**{"legend.position": "inside"})
        + guides(
            colour=guide_colourbar(
                position="inside",
                theme=theme(
                    **{
                        "legend.position.inside": (0, 1),
                        "legend.justification.inside": (0, 1),
                    }
                ),
            ),
            fill=guide_legend(
                position="inside",
                theme=theme(
                    **{
                        "legend.position.inside": (1, 0),
                        "legend.justification.inside": (1, 0),
                    }
                ),
            ),
        )
    )
    return {"plot": p, "size": [10, 8]}

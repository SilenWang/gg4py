from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_legend,
    labs,
    scale_colour_discrete,
)
from ggcore.theme import theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3, 4, 5, 6], "f": ["A", "B", "C", "D", "E", "F"]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="x", colour="f"))
        + geom_point()
        + scale_colour_discrete(
            guide=guide_legend(ncol=3, theme=theme(**{"legend.byrow": True})),
        )
        + theme_test()
        + labs(title="legend.byrow = TRUE")
    )
    return {"plot": p, "size": [10, 8]}

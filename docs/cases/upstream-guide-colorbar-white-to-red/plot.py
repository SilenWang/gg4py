from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    labs,
    scale_colour_gradient,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [0, 1, 2]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="x", colour="x"))
        + geom_point()
        + scale_colour_gradient(low="white", high="red")
        + theme_test()
        + labs(title="white-to-red colorbar, white ticks, no frame")
    )
    return {"plot": p, "size": [10, 8]}

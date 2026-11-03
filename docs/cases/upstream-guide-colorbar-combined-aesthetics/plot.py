from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    labs,
    scale_colour_viridis_c,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [6, 5, 7]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="x", fill="y"))
        + geom_point(shape=21, size=3, stroke=2)
        + scale_colour_viridis_c(name="value", option="B", aesthetics=("colour", "fill"))
        + theme_test()
        + labs(title="combined colour and fill aesthetics")
    )
    return {"plot": p, "size": [10, 8]}

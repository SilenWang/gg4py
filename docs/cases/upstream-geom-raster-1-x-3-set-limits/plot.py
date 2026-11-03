from ggcore.plot import (
    aes,
    geom_point,
    geom_raster,
    ggplot,
    labs,
    scale_x_continuous,
    scale_y_continuous,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {
    "x": [-1.0, 0.0, 1.0],
    "y": [0.0, 0.0, 0.0],
    "z": [1.0, 2.0, 3.0],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", fill="z"))
        + geom_raster()
        + geom_point(colour="red")
        + scale_x_continuous(limits=(-2, 2))
        + scale_y_continuous(limits=(-2, 2))
        + theme_test()
        + labs(title="1 x 3, set limits")
    )
    return {"plot": p, "size": [10, 8]}

from ggcore.plot import (
    aes,
    geom_point,
    geom_raster,
    ggplot,
    labs,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {
    "x": [0.0, 0.0, 0.0],
    "y": [-1.0, 0.0, 1.0],
    "z": [1.0, 2.0, 3.0],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", fill="z"))
        + geom_raster(hjust=0, vjust=0)
        + geom_point(colour="red")
        + theme_test()
        + labs(title="3 x 1, just = (0, 0)")
    )
    return {"plot": p, "size": [10, 8]}

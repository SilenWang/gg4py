from ggcore.plot import (
    aes,
    coord_polar,
    geom_raster,
    ggplot,
    labs,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

# 非线性的 coord_polar() 下 geom_raster 降级成矩形（R 侧 suppressMessages）。
DATA = {"x": [1.0, 2.0, 1.0, 2.0], "y": [1.0, 1.0, 2.0, 2.0], "z": ["A", "B", "C", "D"]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", fill="z"))
        + geom_raster()
        + coord_polar()
        + theme_test()
        + labs(title="rectangle fallback")
    )
    return {"plot": p, "size": [10, 8]}

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_bins,
    guides,
    labs,
    scale_size_binned,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [6, 5, 7]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", size="x"))
        + geom_point()
        + scale_size_binned()
        + guides(size=guide_bins(direction="horizontal"))
        + theme_test()
        + labs(title="guide_bins work horizontally")
    )
    return {"plot": p, "size": [10, 8]}

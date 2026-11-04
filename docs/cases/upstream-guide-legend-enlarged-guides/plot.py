"""Scratch: guide-legend/enlarged-guides."""

from ggcore.plot import (
    aes,
    geom_line,
    geom_point,
    ggplot,
    labs,
    scale_linewidth_continuous,
    scale_size_continuous,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [0.0, 1.0, 2.0]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="x"))
        + geom_point(aes(size="x"))
        + geom_line(aes(linewidth="2 - x"))
        + scale_size_continuous(range=(1.0, 12.0))
        + scale_linewidth_continuous(range=(1.0, 20.0))
        + theme_test()
        + labs(title="enlarged guides")
    )
    return {"plot": p, "size": [10, 8]}

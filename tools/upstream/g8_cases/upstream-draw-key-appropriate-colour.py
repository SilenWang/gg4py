"""Scratch: draw-key/appropriate-colour-key-with-alpha-key-as-lines."""

from ggcore.plot import (
    aes,
    geom_line,
    geom_point,
    ggplot,
    guide_legend,
    guides,
    labs,
    scale_alpha_discrete,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {
    "x": [1, 2],
    "point": ["point", "point"],
    "line": ["line", "line"],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="x"))
        + geom_point(
            aes(colour="point", alpha="point"),
            **{"show.legend": {"colour": None, "alpha": False}},
        )
        + geom_line(
            aes(colour="line", alpha="line"),
            **{"show.legend": {"colour": None, "alpha": True}},
        )
        + scale_alpha_discrete()
        + guides(alpha=guide_legend(order=1), colour=guide_legend(order=2))
        + theme_test()
        + labs(title="appropriate colour key with alpha key as lines")
    )
    return {"plot": p, "size": [10, 8]}

"""Scratch: guide-legend/legend-key-justification."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "docs" / "cases"))

from _fixtures import mtcars

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    labs,
    scale_colour_discrete,
    scale_size_continuous,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

SNAPSHOT = "guide-legend/legend-key-justification.svg"

DATA = {
    "mpg": mtcars["mpg"],
    "disp": mtcars["disp"],
    "cyl": [str(value) for value in mtcars["cyl"]],
    "drat": mtcars["drat"],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="mpg", y="disp", colour="cyl", size="drat"))
        + geom_point()
        + scale_size_continuous(range=(0.0, 20.0), breaks=[3.0, 4.0, 5.0], limits=(2.5, 5.0))
        + scale_colour_discrete(
            labels=["one line", "up\nto\nfour\nlines", "up\nto\nfive\nwhole\nlines"]
        )
        + theme(**{"legend.key.justification": (1.0, 0.0)})
        + labs(title="legend key justification")
    )
    return {"plot": p, "size": [10, 8]}

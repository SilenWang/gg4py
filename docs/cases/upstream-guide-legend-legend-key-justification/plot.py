"""Scratch: guide-legend/legend-key-justification (SIL-820 / G11-B)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _fixtures import mtcars

from ggcore import registry
from ggcore.plot import aes, geom_point, ggplot, guide_legend, guides
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "mpg": mtcars["mpg"],
    "disp": mtcars["disp"],
    "cyl": [str(int(value)) for value in mtcars["cyl"]],
    "drat": mtcars["drat"],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="mpg", y="disp", colour="cyl", size="drat"))
        + geom_point()
        + registry.scale_size_continuous(range=(0, 20), breaks=(3, 4, 5), limits=(2.5, 5))
        + registry.scale_colour_discrete(
            labels=("one line", "up\nto\nfour\nlines", "up\nto\nfive\nwhole\nlines")
        )
        + theme(**{"legend.key.justification": (1, 0)})
        + guides(
            size=guide_legend(order=1),
            colour=guide_legend(order=2),
        )
    )
    return {"plot": p, "size": [10, 8]}

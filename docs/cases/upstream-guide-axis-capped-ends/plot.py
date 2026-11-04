"""Scratch: guide-axis/axis-guides-with-capped-ends."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _fixtures import mtcars

from ggcore.plot import aes, geom_point, ggplot, guide_axis, guides, labs
from ggcore.theme import element_line, theme
from ggio.frame import to_column_table

DATA = {"hp": mtcars["hp"], "disp": mtcars["disp"]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="hp", y="disp"))
        + geom_point()
        + theme(**{"axis.line": element_line()})
        + guides(
            x=guide_axis(cap="both"),
            y=guide_axis(cap="upper"),
            **{"y.sec": guide_axis(cap="lower"), "x.sec": guide_axis(cap="none")},
        )
        + labs(title="axis guides with capped ends")
    )
    return {"plot": p, "size": [10, 8]}

"""Scratch: guide-axis/stacked-axes."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _fixtures import mtcars

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_axis,
    guide_axis_stack,
    guides,
    labs,
)
from ggcore.theme import element_line, theme
from ggio.frame import to_column_table

DATA = {"hp": mtcars["hp"], "disp": mtcars["disp"]}


def build():
    left = guide_axis_stack("axis", guide_axis(cap="both"), title="left")
    right = guide_axis_stack("axis", guide_axis(cap="both"), title="right")
    bottom = guide_axis_stack("axis", guide_axis(cap="both"), title="bottom")
    top = guide_axis_stack("axis", guide_axis(cap="both"), title="top")
    p = (
        ggplot(to_column_table(DATA), aes(x="hp", y="disp"))
        + geom_point()
        + theme(**{"axis.line": element_line()})
        + guides(x=bottom, **{"x.sec": top, "y": left, "y.sec": right})
        + labs(title="stacked axes")
    )
    return {"plot": p, "size": [10, 8]}

"""Scratch: guide-axis/guides-with-minor-ticks (SIL-817 / G10a)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _fixtures import mtcars

from ggcore.plot import aes, geom_point, ggplot, guide_axis, guides
from ggcore.theme import element_line, theme
from ggcore.units import unit
from ggio.frame import to_column_table

DATA = {"wt": mtcars["wt"], "disp": mtcars["disp"]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="wt", y="disp"))
        + geom_point()
        + theme(
            **{
                "axis.ticks.length": unit(1, "cm"),
                "axis.ticks.x.bottom": element_line(linetype=2),
                "axis.ticks.length.x.top": unit(-0.5, "cm"),
                "axis.minor.ticks.x.bottom": element_line(colour="red"),
                "axis.minor.ticks.length.y.left": unit(-0.5, "cm"),
                "axis.minor.ticks.length.x.top": unit(-0.5, "cm"),
                "axis.minor.ticks.length.x.bottom": unit(0.75, "cm"),
                "axis.minor.ticks.length.y.right": unit(5, "cm"),
            }
        )
        + guides(
            x=guide_axis(minor_ticks=True),
            y=guide_axis(minor_ticks=True),
            **{
                "x.sec": guide_axis(minor_ticks=True),
                "y.sec": guide_axis(minor_ticks=False),
            },
        )
    )
    return {"plot": p, "size": [10, 8]}

"""Scratch: guide-axis/guide-axis-theta-in-cartesian-coordinates."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _fixtures import mtcars

from ggcore.plot import aes, geom_point, ggplot, guides, labs
from ggcore.theme import element_line, theme
from ggio.frame import to_column_table

DATA = {"disp": mtcars["disp"], "mpg": mtcars["mpg"]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="disp", y="mpg"))
        + geom_point()
        + guides(x="axis_theta", y="axis_theta", **{"x.sec": "axis_theta", "y.sec": "axis_theta"})
        + theme(
            **{
                "axis.line.x.bottom": element_line(colour="tomato"),
                "axis.line.x.top": element_line(colour="limegreen"),
                "axis.line.y.left": element_line(colour="dodgerblue"),
                "axis.line.y.right": element_line(colour="orchid"),
            }
        )
        + labs(title="guide_axis_theta in cartesian coordinates")
    )
    return {"plot": p, "size": [10, 8]}

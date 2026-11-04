"""Scratch: guide-axis/guide-axis-theta-with-angle-adapting-to-theta."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "docs" / "cases"))

from _fixtures import mtcars

from ggcore.plot import (
    aes,
    coord_radial,
    geom_point,
    ggplot,
    guide_axis_theta,
    guides,
    labs,
    scale_x_continuous,
)
from ggcore.theme import element_line, theme
from ggio.frame import to_column_table

SNAPSHOT = "guide-axis/guide-axis-theta-with-angle-adapting-to-theta.svg"

DATA = {"disp": mtcars["disp"], "mpg": mtcars["mpg"]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="disp", y="mpg"))
        + geom_point()
        + scale_x_continuous(
            breaks=[
                100.0,
                125.0,
                150.0,
                175.0,
                200.0,
                225.0,
                250.0,
                275.0,
                300.0,
                325.0,
                350.0,
                375.0,
                400.0,
                425.0,
                450.0,
            ]
        )
        + coord_radial(inner_radius=0.5)
        + guides(
            theta=guide_axis_theta(angle=0, cap="none"),
            **{"theta.sec": guide_axis_theta(angle=90, cap="both")},
        )
        + theme(**{"axis.line": element_line(colour="black")})
        + labs(title="guide_axis_theta with angle adapting to theta")
    )
    return {"plot": p, "size": [10, 8]}

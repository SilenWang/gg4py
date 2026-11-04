"""Scratch: guide-axis/guides-with-minor-ticks."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "docs" / "cases"))

from _fixtures import mtcars

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_axis,
    guides,
    labs,
    scale_x_continuous,
)
from ggcore.theme import element_line, theme
from ggcore.units import unit
from ggio.frame import to_column_table

SNAPSHOT = "guide-axis/guides-with-minor-ticks.svg"

DATA = {"wt": mtcars["wt"], "disp": mtcars["disp"]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="wt", y="disp"))
        + geom_point()
        + scale_x_continuous(labels=["10^2", "10^3", "10^4", "10^5"])
        + theme(
            **{
                "axis.ticks.length": unit(1.0, "cm"),
                "axis.ticks.x.bottom": element_line(linetype=2),
                "axis.ticks.length.x.top": unit(-0.5, "cm"),
                "axis.minor.ticks.x.bottom": element_line(colour="red"),
                "axis.minor.ticks.length.y.left": unit(-0.5, "cm"),
                "axis.minor.ticks.length.x.top": unit(-0.5, "cm"),
                "axis.minor.ticks.length.x.bottom": unit(0.75, "cm"),
                "axis.minor.ticks.length.y.right": unit(5.0, "cm"),
            }
        )
        + guides(
            x=guide_axis(minor_ticks=True),
            y=guide_axis(minor_ticks=True),
            **{"x.sec": guide_axis(minor_ticks=True), "y.sec": guide_axis(minor_ticks=False)},
        )
        + labs(title="guides with minor ticks")
    )
    return {"plot": p, "size": [10, 8]}

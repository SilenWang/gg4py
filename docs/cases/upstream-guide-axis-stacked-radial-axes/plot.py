"""上游快照复刻：stacked radial axes。

源：guide-axis/stacked-radial-axes.svg

R：

    left   <- guide_axis_stack("axis", guide_axis(cap = "both"), title = "left")
    right  <- guide_axis_stack("axis", guide_axis(cap = "both"), title = "right")
    bottom <- guide_axis_stack("axis_theta", guide_axis_theta(cap = "both"))
    top    <- guide_axis_stack("axis_theta", guide_axis_theta(cap = "both"))

    ggplot(mtcars, aes(hp, disp)) +
      geom_point() +
      theme(axis.line = element_line()) +
      coord_radial(start = 0.25 * pi, end = 1.75 * pi, inner.radius = 0.5) +
      guides(theta = top, theta.sec = bottom, r = left, r.sec = right)
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _fixtures import mtcars

from ggcore.plot import (
    aes,
    coord_radial,
    geom_point,
    ggplot,
    guide_axis,
    guide_axis_stack,
    guide_axis_theta,
    guides,
    labs,
)
from ggcore.theme import element_line, theme
from ggio.frame import to_column_table

DATA = {"hp": mtcars["hp"], "disp": mtcars["disp"]}


def build():
    left = guide_axis_stack("axis", guide_axis(cap="both"), title="left")
    right = guide_axis_stack("axis", guide_axis(cap="both"), title="right")
    bottom = guide_axis_stack("axis_theta", guide_axis_theta(cap="both"))
    top = guide_axis_stack("axis_theta", guide_axis_theta(cap="both"))
    p = (
        ggplot(to_column_table(DATA), aes(x="hp", y="disp"))
        + geom_point()
        + theme(**{"axis.line": element_line()})
        + coord_radial(start=0.25 * math.pi, end=1.75 * math.pi, inner_radius=0.5)
        + guides(**{"theta": top, "theta.sec": bottom, "r": left, "r.sec": right})
        + labs(title="stacked radial axes")
    )
    return {"plot": p, "size": [10, 8]}

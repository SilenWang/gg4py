"""上游快照复刻：inner.radius with all axes。

源：coord-polar/inner-radius-with-all-axes.svg

R：

    theme <- theme(
      axis.line.theta = element_line(colour = "tomato"),
      axis.line.r   = element_line(colour = "dodgerblue")
    )
    sec_guides <- guides(
      r.sec = guide_axis(theme = theme(axis.line.r = element_line(colour = "orchid"))),
      theta.sec = guide_axis_theta(
        theme = theme(axis.line.theta = element_line(colour = "limegreen"))
      )
    )
    ggplot(mtcars, aes(disp, mpg)) + geom_point() + theme +
      coord_radial(inner.radius = 0.3, r.axis.inside = FALSE) + sec_guides
"""

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
    guide_axis_theta,
    guides,
    labs,
)
from ggcore.theme import element_line, theme
from ggio.frame import to_column_table

DATA = {"disp": mtcars["disp"], "mpg": mtcars["mpg"]}

AXIS_THEME = theme(
    **{
        "axis.line.theta": element_line(colour="tomato"),
        "axis.line.r": element_line(colour="dodgerblue"),
    }
)

SEC_GUIDES = guides(
    **{
        "r.sec": guide_axis(theme=theme(**{"axis.line.r": element_line(colour="orchid")})),
        "theta.sec": guide_axis_theta(
            theme=theme(**{"axis.line.theta": element_line(colour="limegreen")})
        ),
    }
)


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="disp", y="mpg"))
        + geom_point()
        + AXIS_THEME
        + coord_radial(inner_radius=0.3, r_axis_inside=False)
        + SEC_GUIDES
        + labs(title="inner.radius with all axes")
    )
    return {"plot": p, "size": [10, 8]}

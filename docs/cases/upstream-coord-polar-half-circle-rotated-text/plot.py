"""上游快照复刻：bottom half circle with rotated text。

源：coord-polar/bottom-half-circle-with-rotated-text.svg

R：

    theme <- theme(
      axis.line.theta = element_line(colour = "tomato"),
      axis.line.r   = element_line(colour = "dodgerblue")
    )
    df <- data_frame0(
      x = 1:5, lab = c("cat", "strawberry\ncake", "coffee", "window", "fluid")
    )
    ggplot(df, aes(x, label = lab)) +
      geom_text(aes(y = "0 degrees"),  angle = 0) +
      geom_text(aes(y = "90 degrees"), angle = 90) +
      coord_radial(start = 0.5 * pi, end = 1.5 * pi,
                   rotate.angle = TRUE, r.axis.inside = FALSE) +
      theme
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ggcore.plot import aes, coord_radial, geom_text, ggplot, labs
from ggcore.theme import element_line, theme
from ggio.frame import to_column_table

DATA = {
    "x": [1.0, 2.0, 3.0, 4.0, 5.0],
    "lab": ["cat", "strawberry\ncake", "coffee", "window", "fluid"],
    "y0": ["0 degrees"] * 5,
    "y1": ["90 degrees"] * 5,
}

AXIS_THEME = theme(
    **{
        "axis.line.theta": element_line(colour="tomato"),
        "axis.line.r": element_line(colour="dodgerblue"),
    }
)


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", label="lab"))
        + geom_text(aes(y="y0"), angle=0.0)
        + geom_text(aes(y="y1"), angle=90.0)
        + AXIS_THEME
        + coord_radial(
            start=0.5 * math.pi,
            end=1.5 * math.pi,
            rotate_angle=True,
            r_axis_inside=False,
        )
        + labs(title="bottom half circle with rotated text")
    )
    return {"plot": p, "size": [10, 8]}

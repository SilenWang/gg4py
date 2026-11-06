"""上游快照复刻：full circle with axes placed at 90 and 225 degrees。

源：coord-polar/full-circle-with-axes-placed-at-90-and-225-degrees.svg

R：

    df <- data.frame(x = c(0, 360), y = c(1, 14))
    ggplot(df, aes(x, y)) + geom_point() +
      coord_radial(expand = FALSE, r.axis.inside = c(90, 225)) +
      guides(r.sec = "axis") +
      theme(axis.line = element_line())
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ggcore.plot import aes, coord_radial, geom_point, ggplot, guides, labs
from ggcore.theme import element_line, theme
from ggio.frame import to_column_table

DATA = {"x": [0.0, 360.0], "y": [1.0, 14.0]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + coord_radial(expand=False, r_axis_inside=(90.0, 225.0))
        + guides(**{"r.sec": "axis"})
        + theme(**{"axis.line": element_line()})
        + labs(title="full circle with axes placed at 90 and 225 degrees")
    )
    return {"plot": p, "size": [10, 8]}

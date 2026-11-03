"""上游快照复刻：reversed cartesian coords。

源：coord-cartesian/reversed-cartesian-coords.svg（vdiffr 名 "reversed cartesian coords"）。

R：

    p <- ggplot(data_frame0(x = c(0, 2), y = c(0, 2))) +
      aes(x = x, y = y) + geom_point() +
      coord_cartesian(xlim = c(-1, 3), ylim = c(-1, 3), expand = FALSE, reverse = "xy") +
      theme_test() + theme(axis.line = element_line())
"""

from ggcore.plot import aes, coord_cartesian, geom_point, ggplot, labs
from ggcore.theme import element_line, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": [0.0, 2.0], "y": [0.0, 2.0]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + coord_cartesian(xlim=(-1.0, 3.0), ylim=(-1.0, 3.0), expand=False, reverse="xy")
        + theme_test()
        + theme(**{"axis.line": element_line()})
        + labs(title="reversed cartesian coords")
    )
    return {"plot": p, "size": [10, 8]}

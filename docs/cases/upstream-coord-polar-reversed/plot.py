"""上游快照复刻：reversed polar coords。

源：coord-polar/reversed-polar-coords.svg（vdiffr 名 "reversed polar coords"）。

R：

    p <- ggplot(data_frame0(x = c(0, 2), y = c(0, 2))) +
      aes(x = x, y = y) + geom_point() +
      scale_x_continuous(limits = c(-1, 3), expand = c(0, 0)) +
      scale_y_continuous(limits = c(-1, 3), expand = c(0, 0)) +
      theme_test() + theme(axis.line = element_line())

    rev <- coord_radial(start = 0.5 * pi, end = 1.5 * pi, reverse = "thetar")
    p + rev

`reverse = "thetar"` 同时反转 theta 与 r：半圆的开口方向与半径刻度都反过来。
"""

from ggcore.plot import (
    aes,
    coord_radial,
    geom_point,
    ggplot,
    labs,
    scale_x_continuous,
    scale_y_continuous,
)
from ggcore.theme import element_line, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": [0.0, 2.0], "y": [0.0, 2.0]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + scale_x_continuous(limits=(-1.0, 3.0), expand=(0.0, 0.0))
        + scale_y_continuous(limits=(-1.0, 3.0), expand=(0.0, 0.0))
        + coord_radial(start=0.5 * 3.141592653589793, end=1.5 * 3.141592653589793, reverse="thetar")
        + theme_test()
        + theme(**{"axis.line": element_line()})
        + labs(title="reversed polar coords")
    )
    return {"plot": p, "size": [10, 8]}

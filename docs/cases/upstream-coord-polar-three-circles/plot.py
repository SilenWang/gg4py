"""上游快照复刻：three-concentric-circles。

源：coord-polar/three-concentric-circles.svg（vdiffr 名 "three-concentric-circles"）。

R：

    theme <- theme_test() +
      theme(
        axis.text.y = element_blank(),
        axis.title = element_blank(),
        panel.grid.major = element_line(colour = "grey90")
      )
    dat <- data_frame(x = rep(0:1, 4), y = rep(c(1, 10, 40, 80), each = 2))

    ggplot(dat, aes(x, y, group = factor(y))) +
      geom_path() +
      coord_polar() +
      theme

x（0..1）是 theta、y 是半径：三个同心圆由 y 的三个水平各画一条 path 得到，
`panel.grid.major` 的 r 圆与 theta 辐条用 grey90。
"""

from ggcore.plot import aes, coord_polar, geom_path, ggplot, labs
from ggcore.theme import element_blank, element_line, theme, theme_test
from ggio.frame import to_column_table

DATA = {
    "x": [0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0],
    "y": [1.0, 1.0, 10.0, 10.0, 40.0, 40.0, 80.0, 80.0],
    "g": ["1", "1", "10", "10", "40", "40", "80", "80"],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", group="g"))
        + geom_path()
        + coord_polar()
        + theme_test()
        + theme(
            **{
                "axis.text.y": element_blank(),
                "axis.title": element_blank(),
                "panel.grid.major": element_line(colour="grey90"),
            }
        )
        + labs(title="three-concentric-circles")
    )
    return {"plot": p, "size": [10, 8]}

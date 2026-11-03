"""上游快照复刻：Rays, circular arcs, and spiral arcs。

源：coord-polar/rays-circular-arcs-and-spiral-arcs.svg
（vdiffr 名 "Rays, circular arcs, and spiral arcs"）。

R：

    theme <- theme_test() +
      theme(axis.text.y = element_blank(), axis.title = element_blank(),
            panel.grid.major = element_line(colour = "grey90"))
    dat <- data_frame(
      theta = c(0, 2*pi,   2,   6, 6, 1,    1,  0),
      r     = c(0,    0, 0.5, 0.5, 1, 1, 0.75, 0.5),
      g     = 1:8
    )
    ggplot(dat, aes(theta, r, colour = g)) +
      geom_path(show.legend = FALSE) +
      geom_point(colour = "black") +
      coord_polar() +
      theme

一条 path 里同时有半径不变（圆弧）与半径变化（螺旋）的段；`colour = g` 是连续色，
`show.legend = FALSE` 去掉图例。
"""

from ggcore.plot import aes, coord_polar, geom_path, geom_point, ggplot, labs
from ggcore.theme import element_blank, element_line, theme, theme_test
from ggio.frame import to_column_table

DATA = {
    "theta": [0.0, 2.0 * 3.141592653589793, 2.0, 6.0, 6.0, 1.0, 1.0, 0.0],
    "r": [0.0, 0.0, 0.5, 0.5, 1.0, 1.0, 0.75, 0.5],
    "g": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="theta", y="r", colour="g"))
        + geom_path(show_legend=False)
        + geom_point(colour="black")
        + coord_polar()
        + theme_test()
        + theme(
            **{
                "axis.text.y": element_blank(),
                "axis.title": element_blank(),
                "panel.grid.major": element_line(colour="grey90"),
            }
        )
        + labs(title="Rays, circular arcs, and spiral arcs")
    )
    return {"plot": p, "size": [10, 8]}

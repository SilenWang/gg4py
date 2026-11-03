"""上游快照复刻：racetrack plot: closed and has center hole。

源：coord-polar/racetrack-plot-closed-and-has-center-hole.svg
（vdiffr 名 "racetrack plot: closed and has center hole"）。

R：

    dat <- data_frame(x = LETTERS[1:3], y = 1:3)
    ggplot(dat, aes(x, y)) +
      geom_bar(stat = "identity") +
      coord_polar(theta = "y") +
      scale_x_discrete(expand = c(0, 0.6)) +
      theme

`scale_x_discrete(expand = c(0, 0.6))` 把离散 r 轴的两端各留 0.6 格，圆心因此
留出一个洞；其余与 `racetrack plot: closed and no center hole` 相同。
"""

from ggcore.plot import aes, coord_polar, geom_bar, ggplot, labs, scale_x_discrete
from ggcore.theme import element_blank, element_line, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": ["A", "B", "C"], "y": [1.0, 2.0, 3.0]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_bar(stat="identity")
        + coord_polar(theta="y")
        + scale_x_discrete(expand=(0.0, 0.6))
        + theme_test()
        + theme(
            **{
                "axis.text.y": element_blank(),
                "axis.title": element_blank(),
                "panel.grid.major": element_line(colour="grey90"),
            }
        )
        + labs(title="racetrack plot: closed and has center hole")
    )
    return {"plot": p, "size": [10, 8]}

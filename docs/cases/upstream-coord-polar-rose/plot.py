"""上游快照复刻：rose plot with has equal spacing。

源：coord-polar/rose-plot-with-has-equal-spacing.svg
（vdiffr 名 "rose plot with has equal spacing"）。

R：

    theme <- theme_test() +
      theme(axis.text.y = element_blank(), axis.title = element_blank(),
            panel.grid.major = element_line(colour = "grey90"))
    dat <- data_frame(x = LETTERS[1:3], y = 1:3)
    ggplot(dat, aes(x, y)) + geom_bar(stat = "identity") + coord_polar() + theme

离散 theta（3 个水平）等分整圆；柱子的外缘是圆弧（`coord_munch()`）。
"""

from ggcore.plot import aes, coord_polar, geom_bar, ggplot, labs
from ggcore.theme import element_blank, element_line, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": ["A", "B", "C"], "y": [1.0, 2.0, 3.0]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_bar(stat="identity")
        + coord_polar()
        + theme_test()
        + theme(
            **{
                "axis.text.y": element_blank(),
                "axis.title": element_blank(),
                "panel.grid.major": element_line(colour="grey90"),
            }
        )
        + labs(title="rose plot with has equal spacing")
    )
    return {"plot": p, "size": [10, 8]}

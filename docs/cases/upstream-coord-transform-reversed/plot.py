"""上游快照复刻：reversed transformed coords。

源：coord-transform/reversed-transformed-coords.svg
（vdiffr 名 "reversed transformed coords"）。

R：

    p <- ggplot(data_frame0(x = c(1, 100), y = c(1, 100))) +
      aes(x = x, y = y) + geom_point() +
      coord_transform(
        x = "log10", y = "log10",
        xlim = c(0.1, 1000), ylim = c(0.1, 1000), expand = FALSE,
        reverse = "xy"
      ) +
      theme_test() + theme(axis.line = element_line())
"""

from ggcore.plot import aes, coord_trans, geom_point, ggplot, labs
from ggcore.theme import element_line, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": [1.0, 100.0], "y": [1.0, 100.0]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + coord_trans(
            x="log10",
            y="log10",
            xlim=(0.1, 1000.0),
            ylim=(0.1, 1000.0),
            expand=False,
            reverse="xy",
        )
        + theme_test()
        + theme(**{"axis.line": element_line()})
        + labs(title="reversed transformed coords")
    )
    return {"plot": p, "size": [10, 8]}

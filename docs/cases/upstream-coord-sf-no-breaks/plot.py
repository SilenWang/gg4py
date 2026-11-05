"""上游快照复刻：no breaks（coord_sf/no-breaks.svg）。

R：

    df <- data_frame(x = c(1, 2, 3), y = c(1, 2, 3))
    ggplot(df, aes(x, y)) + geom_point() + coord_sf() + theme_gray() +
      scale_x_continuous(breaks = NULL) + scale_y_continuous(breaks = NULL)
"""

from ggcore.plot import (
    aes,
    coord_sf,
    geom_point,
    ggplot,
    labs,
    scale_x_continuous,
    scale_y_continuous,
)
from ggcore.theme import theme_gray
from ggio.frame import to_column_table

DATA = {"x": [1.0, 2.0, 3.0], "y": [1.0, 2.0, 3.0]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + coord_sf()
        + theme_gray()
        + scale_x_continuous(breaks=None)
        + scale_y_continuous(breaks=None)
        + labs(title="no breaks")
    )
    return {"plot": p, "size": [10, 8]}

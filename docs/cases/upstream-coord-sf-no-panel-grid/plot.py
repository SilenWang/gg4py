"""上游快照复刻：no panel grid（coord_sf/no-panel-grid.svg）。

R：

    df <- data_frame(x = c(1, 2, 3), y = c(1, 2, 3))
    ggplot(df, aes(x, y)) + geom_point() + coord_sf() +
      theme_gray() + theme(panel.grid = element_blank())
"""

from ggcore.plot import aes, coord_sf, geom_point, ggplot, labs
from ggcore.theme import element_blank, theme, theme_gray
from ggio.frame import to_column_table

DATA = {"x": [1.0, 2.0, 3.0], "y": [1.0, 2.0, 3.0]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + coord_sf()
        + theme_gray()
        + theme(**{"panel.grid": element_blank()})
        + labs(title="no panel grid")
    )
    return {"plot": p, "size": [10, 8]}

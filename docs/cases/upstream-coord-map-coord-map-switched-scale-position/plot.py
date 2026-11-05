"""上游快照复刻：coord_map switched scale position。

R：

    p_us + geom_polygon(fill = NA, colour = "grey50") + coord_map("mercator") +
      scale_y_continuous(position = "right") + scale_x_continuous(position = "top")
"""

from ggcore.map_data import map_frame
from ggcore.plot import (
    aes,
    coord_map,
    geom_polygon,
    ggplot,
    labs,
    scale_x_continuous,
    scale_y_continuous,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = to_column_table(map_frame("usa", "."))


def build():
    p = (
        ggplot(DATA, aes(x="x", y="y", group="group"))
        + geom_polygon(fill=None, colour="grey50")
        + coord_map("mercator")
        + scale_y_continuous(position="right")
        + scale_x_continuous(position="top")
        + theme_test()
        + labs(title="coord_map switched scale position")
    )
    return {"plot": p, "size": [10, 8]}

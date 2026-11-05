"""上游快照复刻：USA mercator（coord-map/usa-mercator.svg）。

R：

    us_map <- map_data("usa")
    p_us <- ggplot(us_map, aes(x = long, y = lat, group = group))
    p_us + geom_polygon(fill = NA, colour = "grey50") + coord_map("mercator")
"""

from ggcore.map_data import map_frame
from ggcore.plot import aes, coord_map, geom_polygon, ggplot, labs
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = to_column_table(map_frame("usa", "."))


def build():
    p = (
        ggplot(DATA, aes(x="x", y="y", group="group"))
        + geom_polygon(fill=None, colour="grey50")
        + coord_map("mercator")
        + theme_test()
        + labs(title="USA mercator")
    )
    return {"plot": p, "size": [10, 8]}

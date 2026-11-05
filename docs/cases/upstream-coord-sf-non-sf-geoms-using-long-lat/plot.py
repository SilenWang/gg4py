"""上游快照复刻：non-sf geoms using long-lat。

R：

    ggplot(polygon) + geom_sf(fill = NA) +
      geom_point(data = points, aes(x, y)) + coord_sf(default_crs = 4326)
"""

from ggcore.plot import aes, coord_sf, geom_point, geom_sf, ggplot, labs
from ggcore.sf import sf, st_polygon
from ggcore.theme import theme_test
from ggio.frame import to_column_table

RING = [(-80, 35), (-76, 35), (-76, 40), (-80, 40), (-80, 35)]
POLYGON = sf({}, geometry=[st_polygon(RING, crs=4326).transform(3347)])
POINTS = to_column_table({"x": [-80.0, -80.0, -76.0, -76.0], "y": [35.0, 40.0, 35.0, 40.0]})


def build():
    p = (
        ggplot(POLYGON)
        + geom_sf(fill=None)
        + geom_point(data=POINTS, mapping=aes(x="x", y="y"))
        + coord_sf(default_crs=4326)
        + theme_test()
        + labs(title="non-sf geoms using long-lat")
    )
    return {"plot": p, "size": [10, 8]}

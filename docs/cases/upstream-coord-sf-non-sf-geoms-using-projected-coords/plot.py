"""上游快照复刻：non-sf geoms using projected coords。

R：

    polygon <- sf::st_sfc(sf::st_polygon(list(matrix(
      c(-80, -76, -76, -80, -80, 35, 35, 40, 40, 35), ncol = 2))), crs = 4326)
    polygon <- sf::st_transform(polygon, crs = 3347)
    points  <- data_frame(x = c(-80, -80, -76, -76), y = c(35, 40, 35, 40))
    points_trans <- sf_transform_xy(points, 3347, 4326)
    ggplot(polygon) + geom_sf(fill = NA) +
      geom_point(data = points_trans, aes(x, y))
"""

from ggcore.plot import aes, geom_point, geom_sf, ggplot, labs
from ggcore.sf import sf, st_polygon, st_transform_xy
from ggcore.theme import theme_test
from ggio.frame import to_column_table

RING = [(-80, 35), (-76, 35), (-76, 40), (-80, 40), (-80, 35)]
POLYGON = sf({}, geometry=[st_polygon(RING, crs=4326).transform(3347)])

LONLAT = {"x": [-80.0, -80.0, -76.0, -76.0], "y": [35.0, 40.0, 35.0, 40.0]}
PX, PY = st_transform_xy(LONLAT["x"], LONLAT["y"], 3347, 4326)
POINTS = to_column_table({"x": [float(v) for v in PX], "y": [float(v) for v in PY]})


def build():
    p = (
        ggplot(POLYGON)
        + geom_sf(fill=None)
        + geom_point(data=POINTS, mapping=aes(x="x", y="y"))
        + theme_test()
        + labs(title="non-sf geoms using projected coords")
    )
    return {"plot": p, "size": [10, 8]}

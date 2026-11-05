"""上游快照复刻：limits specified in projected coords。

R：

    lims <- sf_transform_xy(list(x = c(-80.5, -76, -78.25, -78.25),
                                 y = c(38.5, 38.5, 36, 41)), 3347, 4326)
    ggplot(polygon) + geom_sf(fill = NA) +
      geom_point(data = points_trans, aes(x, y)) +
      coord_sf(xlim = lims$x[1:2], ylim = lims$y[3:4])
"""

from ggcore.plot import aes, coord_sf, geom_point, geom_sf, ggplot, labs
from ggcore.sf import sf, st_polygon, st_transform_xy
from ggcore.theme import theme_test
from ggio.frame import to_column_table

RING = [(-80, 35), (-76, 35), (-76, 40), (-80, 40), (-80, 35)]
POLYGON = sf({}, geometry=[st_polygon(RING, crs=4326).transform(3347)])

LONLAT = {"x": [-80.0, -80.0, -76.0, -76.0], "y": [35.0, 40.0, 35.0, 40.0]}
PX, PY = st_transform_xy(LONLAT["x"], LONLAT["y"], 3347, 4326)
POINTS = to_column_table({"x": [float(v) for v in PX], "y": [float(v) for v in PY]})

LIMS_X, LIMS_Y = st_transform_xy(
    [-80.5, -76.0, -78.25, -78.25], [38.5, 38.5, 36.0, 41.0], 3347, 4326
)


def build():
    p = (
        ggplot(POLYGON)
        + geom_sf(fill=None)
        + geom_point(data=POINTS, mapping=aes(x="x", y="y"))
        + coord_sf(
            xlim=(float(LIMS_X[0]), float(LIMS_X[1])),
            ylim=(float(LIMS_Y[2]), float(LIMS_Y[3])),
        )
        + theme_test()
        + labs(title="limits specified in projected coords")
    )
    return {"plot": p, "size": [10, 8]}

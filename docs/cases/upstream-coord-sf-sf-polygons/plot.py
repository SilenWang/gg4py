"""上游快照复刻：sf-polygons（coord_sf/sf-polygons.svg）。

R：

    nc_tiny_coords <- matrix(c(-81.473, -81.741, -81.67, -81.345, -81.266,
                               -81.24, -81.473, 36.234, 36.392, 36.59,
                               36.573, 36.437, 36.365, 36.234), ncol = 2)
    nc <- sf::st_as_sf(data_frame(
      NAME = "ashe",
      geometry = sf::st_sfc(sf::st_polygon(list(nc_tiny_coords)), crs = 4326)))
    ggplot(nc) + geom_sf() + coord_sf()
"""

from ggcore.plot import geom_sf, ggplot, labs
from ggcore.sf import sf, st_polygon
from ggcore.theme import theme_test

COORDS = [
    (-81.473, 36.234),
    (-81.741, 36.392),
    (-81.67, 36.59),
    (-81.345, 36.573),
    (-81.266, 36.437),
    (-81.24, 36.365),
    (-81.473, 36.234),
]
DATA = sf({"NAME": ["ashe"]}, geometry=[st_polygon(COORDS, crs=4326)])


def build():
    p = ggplot(DATA) + geom_sf() + labs(title="sf-polygons") + theme_test()
    return {"plot": p, "size": [10, 8]}

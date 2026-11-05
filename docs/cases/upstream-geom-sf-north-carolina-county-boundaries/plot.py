"""上游快照复刻：North Carolina county boundaries（geom-sf）。

R：

    nc <- sf::st_as_sf(data_frame(
      NAME = "ashe",
      geometry = sf::st_sfc(sf::st_polygon(list(nc_tiny_coords)), crs = 4326)))
    ggplot() + geom_sf(data = nc, linetype = 2) + coord_sf(datum = 4326)
"""

from ggcore.plot import coord_sf, geom_sf, ggplot, labs
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
    p = (
        ggplot()
        + geom_sf(data=DATA, linetype=2)
        + coord_sf(datum=4326)
        + theme_test()
        + labs(title="North Carolina county boundaries")
    )
    return {"plot": p, "size": [10, 8]}

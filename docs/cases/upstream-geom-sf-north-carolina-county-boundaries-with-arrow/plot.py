"""上游快照复刻：North Carolina county boundaries with arrow。

R：

    nc <- sf::st_linestring(sf::st_coordinates(
      sf::st_as_sf(nc_tiny_coords, coords = c("x", "y"), crs = 4326)))
    ggplot() + geom_sf(data = nc, arrow = arrow()) + coord_sf(datum = 4326)
"""

from ggcore.arrow import arrow
from ggcore.plot import coord_sf, geom_sf, ggplot, labs
from ggcore.sf import sf, st_linestring
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
DATA = sf({}, geometry=[st_linestring(COORDS)])


def build():
    p = (
        ggplot()
        + geom_sf(data=DATA, arrow=arrow())
        + coord_sf(datum=4326)
        + theme_test()
        + labs(title="North Carolina county boundaries with arrow")
    )
    return {"plot": p, "size": [10, 8]}

"""上游快照复刻：spatial points（geom-sf/spatial-points.svg）。

R：

    pts <- sf::st_sf(a = 1:2, geometry = sf::st_sfc(sf::st_point(0:1), sf::st_point(1:2)))
    ggplot() + geom_sf(data = pts)
"""

from ggcore.plot import geom_sf, ggplot, labs
from ggcore.sf import sf, st_point
from ggcore.theme import theme_test

DATA = sf({"a": [1, 2]}, geometry=[st_point(0, 1), st_point(1, 2)])


def build():
    p = ggplot(DATA) + geom_sf() + labs(title="spatial points") + theme_test()
    return {"plot": p, "size": [10, 8]}

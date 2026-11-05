"""上游快照复刻：geom_sf polygon legend（geom-sf/geom-sf-polygon-legend.svg）。

R：

    data <- sf::st_as_sf(sf::st_sfc(
      sf::st_polygon(list(cbind(c(1, 2, 2, 1), c(3, 3, 4, 3)))),
      sf::st_polygon(list(cbind(c(3, 3, 4, 3), c(5, 6, 6, 5))))),
      col = c("foo", "bar"))
    ggplot() + geom_sf(aes(colour = col)) + data
"""

from ggcore.plot import aes, geom_sf, ggplot, labs
from ggcore.sf import sf, st_polygon
from ggcore.theme import theme_test

DATA = sf(
    {"col": ["foo", "bar"]},
    geometry=[
        st_polygon([(1, 3), (2, 3), (2, 4), (1, 3)]),
        st_polygon([(3, 5), (3, 6), (4, 6), (3, 5)]),
    ],
)


def build():
    p = (
        ggplot(DATA)
        + geom_sf(aes(colour="col"))
        + theme_test()
        + labs(title="geom_sf polygon legend")
    )
    return {"plot": p, "size": [10, 8]}

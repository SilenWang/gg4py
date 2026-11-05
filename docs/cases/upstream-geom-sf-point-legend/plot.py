"""上游快照复刻：geom_sf point legend（geom-sf/geom-sf-point-legend.svg）。

R：

    data <- sf::st_as_sf(data.frame(lon = c(1, 2), lat = c(3, 4),
                                    col = c("foo", "bar")),
                         coords = c("lon", "lat"))
    ggplot() + geom_sf(aes(colour = col)) + data
"""

from ggcore.plot import aes, geom_sf, ggplot, labs
from ggcore.sf import sf, st_point
from ggcore.theme import theme_test

DATA = sf(
    {"col": ["foo", "bar"]},
    geometry=[st_point(1, 3), st_point(2, 4)],
)


def build():
    p = (
        ggplot(DATA)
        + geom_sf(aes(colour="col"))
        + theme_test()
        + labs(title="geom_sf point legend")
    )
    return {"plot": p, "size": [10, 8]}

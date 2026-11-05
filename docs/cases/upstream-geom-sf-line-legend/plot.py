"""上游快照复刻：geom_sf line legend（geom-sf/geom-sf-line-legend.svg）。

R：

    data <- sf::st_as_sf(sf::st_sfc(
      sf::st_linestring(x = cbind(1:2, 3:4)),
      sf::st_linestring(x = cbind(3:4, 5:6))), col = c("foo", "bar"))
    ggplot() + geom_sf(aes(colour = col)) + data
"""

from ggcore.plot import aes, geom_sf, ggplot, labs
from ggcore.sf import sf, st_linestring
from ggcore.theme import theme_test

DATA = sf(
    {"col": ["foo", "bar"]},
    geometry=[st_linestring([(1, 3), (2, 4)]), st_linestring([(3, 5), (4, 6)])],
)


def build():
    p = ggplot(DATA) + geom_sf(aes(colour="col")) + theme_test() + labs(title="geom_sf line legend")
    return {"plot": p, "size": [10, 8]}

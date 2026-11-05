"""上游快照复刻：… with more than one arrow（geom-sf）。

R：

    nc2 <- sf::st_cast(sf::st_sfc(sf::st_multilinestring(lapply(
      1:(nrow(coords) - 1), function(i) rbind(coords[i, ], coords[i + 1, ])))),
      "LINESTRING")
    ggplot() + geom_sf(data = nc2, arrow = arrow()) + coord_sf(datum = 4326)
"""

from ggcore.arrow import arrow
from ggcore.plot import coord_sf, geom_sf, ggplot, labs
from ggcore.sf import sf, st_multilinestring
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
DATA = sf(
    {},
    geometry=[st_multilinestring([[COORDS[i], COORDS[i + 1]] for i in range(len(COORDS) - 1)])],
)


def build():
    p = (
        ggplot()
        + geom_sf(data=DATA, arrow=arrow())
        + coord_sf(datum=4326)
        + theme_test()
        + labs(title="North Carolina county boundaries with more than one arrow")
    )
    return {"plot": p, "size": [10, 8]}

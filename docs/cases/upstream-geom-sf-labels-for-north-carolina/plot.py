"""上游快照复刻：Labels for North Carolina（geom-sf/labels-for-north-carolina.svg）。

R：

    nc_3857 <- sf::st_transform(nc, 3857)
    ggplot() + geom_sf_label(data = nc_3857, aes(label = NAME))
"""

from ggcore.plot import aes, geom_sf_label, ggplot, labs
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
POLYGON = st_polygon(COORDS, crs=4326).transform(3857)
DATA = sf({"NAME": ["ashe"]}, geometry=[POLYGON], crs=3857)


def build():
    p = (
        ggplot()
        + geom_sf_label(data=DATA, mapping=aes(label="NAME"))
        + theme_test()
        + labs(title="Labels for North Carolina")
    )
    return {"plot": p, "size": [10, 8]}

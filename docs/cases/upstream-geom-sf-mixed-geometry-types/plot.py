"""上游快照复刻：mixed geometry types（geom-sf/mixed-geometry-types.svg）。

R：

    update_geom_defaults("point", list(colour = "blue"))
    update_geom_defaults("line", list(colour = "red"))
    ggplot(data) + geom_sf()

（`withr::defer()` 在图画完后恢复缺省；本 case 在同一进程里画完即恢复。）
"""

import math

from ggcore.plot import geom_sf, ggplot, labs, update_geom_defaults
from ggcore.sf import (
    sf,
    st_geometrycollection,
    st_linestring,
    st_multilinestring,
    st_multipoint,
    st_point,
    st_polygon,
)
from ggcore.theme import theme_test

T = [2.0 * math.pi * index / 9.0 for index in range(10)]


def _zap(value: float) -> float:
    return 0.0 if abs(value) < 1e-4 else value


def build():
    circle = [(math.cos(angle), _zap(math.sin(angle))) for angle in T]
    shifted = [(x + 5.0, y + 5.0) for x, y in circle]
    DATA = sf(
        {},
        geometry=[
            st_multipoint([(1, 3), (2, 4)]),
            st_multilinestring([[(1, 3.8), (1.8, 3)], [(1.2, 4), (2, 3.2)]]),
            st_polygon([circle, shifted]),
            st_geometrycollection(
                [
                    st_point(3, 2),
                    st_linestring([(2, 1), (4, 1), (4, 3)]),
                ]
            ),
            st_linestring([(2, -1), (6, 3)]),
            st_point(5, 0),
        ],
    )
    update_geom_defaults("point", {"colour": "blue"})
    update_geom_defaults("line", {"colour": "red"})
    try:
        p = ggplot(DATA) + geom_sf() + theme_test() + labs(title="mixed geometry types")
    finally:
        update_geom_defaults("point", None)
        update_geom_defaults("line", None)
    return {"plot": p, "size": [10, 8]}

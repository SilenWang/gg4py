"""上游快照复刻：coord_sf() with custom guides。

R：

    p <- ggplot(polygon) + geom_sf(fill = NA) +
      coord_sf(label_graticule = "NSWE") +
      scale_x_continuous(guide = guide_none("guide_none() with title")) +
      scale_y_continuous(guide = guide_axis(angle = 45), name = "title from scale") +
      guides(x.sec = guide_axis(angle = -45),
             y.sec = guide_axis(n.dodge = 2, title = "Secondary guide via `guides()`"))
"""

from ggcore.plot import (
    coord_sf,
    geom_sf,
    ggplot,
    guide_axis,
    guide_none,
    guides,
    labs,
    scale_x_continuous,
    scale_y_continuous,
)
from ggcore.sf import sf, st_polygon
from ggcore.theme import theme_test

RING = [(-80, 35), (-76, 35), (-76, 40), (-80, 40), (-80, 35)]
POLYGON = sf({}, geometry=[st_polygon(RING, crs=4326).transform(3347)])


def build():
    p = (
        ggplot(POLYGON)
        + geom_sf(fill=None)
        + coord_sf(label_graticule="NSWE")
        + scale_x_continuous(guide=guide_none("guide_none() with title"))
        + scale_y_continuous(guide=guide_axis(angle=45), name="title from scale")
        + guides(
            **{
                "x.sec": guide_axis(angle=-45),
                "y.sec": guide_axis(n_dodge=2, title="Secondary guide via `guides()`"),
            }
        )
        + theme_test()
        + labs(title="coord_sf() with custom guides")
    )
    return {"plot": p, "size": [10, 8]}

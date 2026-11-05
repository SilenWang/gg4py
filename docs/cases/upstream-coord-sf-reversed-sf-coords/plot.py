"""上游快照复刻：reversed sf coords（coord_sf/reversed-sf-coords.svg）。

R：

    p <- ggplot(sf::st_multipoint(cbind(c(0, 2), c(0, 2)))) +
      geom_sf() +
      coord_sf(xlim = c(-1, 3), ylim = c(-1, 3), expand = FALSE, reverse = "xy") +
      theme_test() + theme(axis.line = element_line())
"""

from ggcore.plot import coord_sf, geom_sf, ggplot, labs
from ggcore.sf import sf, st_multipoint
from ggcore.theme import element_line, theme, theme_test

DATA = sf({}, geometry=[st_multipoint([(0.0, 0.0), (2.0, 2.0)])])


def build():
    p = (
        ggplot(DATA)
        + geom_sf()
        + coord_sf(xlim=(-1.0, 3.0), ylim=(-1.0, 3.0), expand=False, reverse="xy")
        + theme_test()
        + theme(**{"axis.line": element_line()})
        + labs(title="reversed sf coords")
    )
    return {"plot": p, "size": [10, 8]}

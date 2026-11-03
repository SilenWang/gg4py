"""coord：`coord_quickmap()` —— 等距圆柱近似（纬度 1/cos(lat) 因子）。"""

from ggcore.plot import aes, coord_quickmap, geom_point, ggplot
from ggcore.theme import theme, theme_void
from ggio.frame import to_column_table

DATA = {
    "lon": [-10.0, -4.0, 0.0, 6.0, 12.0],
    "lat": [35.0, 41.0, 39.0, 44.0, 37.0],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="lon", y="lat"))
        + geom_point(size=3, colour="#4C78A8")
        + coord_quickmap()
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

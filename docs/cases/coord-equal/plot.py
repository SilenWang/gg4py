"""coord：`coord_equal()` —— 与 `coord_fixed(ratio = 1)` 同一口径。"""

from ggcore.plot import aes, coord_equal, geom_point, ggplot
from ggcore.theme import theme, theme_void
from ggio.frame import to_column_table

DATA = {
    "x": [1.0, 2.0, 3.0, 4.0],
    "y": [2.0, 5.0, 3.0, 6.0],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point(size=3, colour="#4C78A8")
        + coord_equal()
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

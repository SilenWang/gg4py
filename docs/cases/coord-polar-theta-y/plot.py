"""coord：`coord_polar(theta = "y")` —— y 是角度、x 是半径。"""

from ggcore.plot import aes, coord_polar, geom_point, ggplot
from ggcore.theme import theme, theme_void
from ggio.frame import to_column_table

DATA = {
    "cls": ["a", "b", "c", "d", "e"],
    "v": [1.0, 2.5, 1.8, 3.0, 2.2],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="cls", y="v"))
        + geom_point(size=3, colour="#4C78A8")
        + coord_polar(theta="y")
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

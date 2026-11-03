"""coord：`coord_polar()` × `facet_wrap()` —— 每块面板各自是正圆。"""

from ggcore.plot import aes, coord_polar, facet_wrap, geom_point, ggplot
from ggcore.theme import theme, theme_void
from ggio.frame import to_column_table

DATA = {
    "cls": ["a", "b", "c", "d", "e"],
    "v": [1.0, 2.5, 1.8, 3.0, 2.2],
    "g": ["p", "p", "p", "q", "q"],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="cls", y="v"))
        + geom_point(size=3, colour="#4C78A8")
        + coord_polar()
        + facet_wrap(("g",))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

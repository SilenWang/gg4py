"""coord：`coord_flip()` + 横向柱 —— flip × 柱（geom 不判断 coord 名）。"""

from ggcore.plot import aes, coord_flip, geom_col, ggplot
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
        + geom_col(fill="#4C78A8", width=0.6)
        + coord_flip()
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

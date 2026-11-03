"""coord：`coord_polar()` 的玫瑰图 —— 柱边按 `coord_munch()` 细分。"""

from ggcore.plot import aes, coord_polar, geom_col, ggplot
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
        + geom_col(fill="#4C78A8", width=0.8)
        + coord_polar()
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

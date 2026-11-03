"""coord：`coord_trans(y = "sqrt")` —— 逐轴变换，x 轴保持线性。"""

from ggcore.plot import aes, coord_trans, geom_point, ggplot
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
        + coord_trans(y="sqrt")
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

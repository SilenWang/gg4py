"""coord：`coord_trans(x = "log10")` —— 变换在标度空间之后。"""

from ggcore.plot import aes, coord_trans, geom_point, ggplot
from ggcore.theme import theme, theme_void
from ggio.frame import to_column_table

DATA = {
    "x": [1.0, 3.0, 10.0, 30.0, 100.0, 300.0],
    "y": [0.10, 0.25, 0.35, 0.50, 0.60, 0.75],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point(size=3, colour="#4C78A8")
        + coord_trans(x="log10")
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

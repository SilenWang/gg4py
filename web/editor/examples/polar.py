"""示例 6 / 9 · 极坐标：`coord_polar()` 把柱子的 x 轴卷成角度（玫瑰图）。"""

from ggcore.plot import aes, coord_polar, geom_col, ggplot, labs, theme_minimal
from ggcore.theme import theme
from ggio.frame import to_column_table

needs = ["numpy"]

DATA = {
    "class": ["a", "b", "c", "d", "e", "f"],
    "value": [1.0, 2.5, 1.8, 3.0, 2.2, 1.4],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="class", y="value"))
        + geom_col(fill="#4C78A8", width=0.9)
        + coord_polar()
        + theme_minimal()
        + theme(**{"legend.position": "none"})
        + labs(title="Polar bars", subtitle="the same geom, a different coord", x=None, y=None)
    )
    return {"plot": p, "size": [5.0, 3.5]}

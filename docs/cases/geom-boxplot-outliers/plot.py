"""boxplot：两组带离群点（须线按 1.5 IQR，离群点走 point 的口径）。"""

from ggcore.plot import (
    aes,
    geom_boxplot,
    ggplot,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "cls": ["a"] * 5 + ["b"] * 6 + ["c"] * 6,
    "v": [2.0, 3.0, 4.0, 5.0, 6.0, 2.0, 3.0, 3.5, 4.0, 4.5, 9.0, 1.0, 1.5, 2.0, 2.5, 3.0, 8.5],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="cls", y="v"))
        + geom_boxplot(fill="#4C78A8", colour="#333333", width=0.6)
        + scale_y_continuous(limits=(0, 10), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

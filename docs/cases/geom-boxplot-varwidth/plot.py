"""boxplot：`varwidth = TRUE`（箱宽 ∝ sqrt(n / max(n))）。"""

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
    "cls": ["a"] * 8 + ["b"] * 4 + ["c"] * 6,
    "v": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 2.0, 3.0, 4.0, 5.0, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="cls", y="v"))
        + geom_boxplot(fill="#4C78A8", colour="#333333", varwidth=True, width=0.8)
        + scale_y_continuous(limits=(0, 9), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

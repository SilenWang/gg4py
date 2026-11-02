"""col：横向柱（`orientation = "y"`，数据给定长度）。"""

from ggcore.plot import (
    aes,
    geom_col,
    ggplot,
    scale_fill_discrete,
    scale_x_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "cls": ["a", "b", "c"],
    "v": [1.4, 2.6, 0.8],
    "grp": ["p", "q", "p"],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(y="cls", x="v", fill="grp"))
        + geom_col(orientation="y", width=0.6)
        + scale_fill_discrete(values={"p": "#4C78A8", "q": "#F58518"})
        + scale_x_continuous(limits=(0, 3), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

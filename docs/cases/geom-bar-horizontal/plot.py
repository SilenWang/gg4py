"""bar：横向计数（`orientation = "y"`，count 落在 x 轴上）。"""

from ggcore.plot import (
    aes,
    geom_bar,
    ggplot,
    scale_fill_discrete,
    scale_x_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "cls": ["a", "a", "a", "b", "b", "c"],
    "grp": ["p", "q", "p", "p", "q", "p"],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(y="cls", fill="grp"))
        + geom_bar(orientation="y")
        + scale_fill_discrete(values={"p": "#4C78A8", "q": "#F58518"})
        + scale_x_continuous(limits=(0, 4), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

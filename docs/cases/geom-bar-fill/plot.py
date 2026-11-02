"""bar：stat_count + position_fill（按 x 归一化到 1）。"""

from ggcore.plot import (
    aes,
    geom_bar,
    ggplot,
    position_fill,
    scale_fill_discrete,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "cls": ["a", "a", "a", "b", "b", "c"],
    "grp": ["p", "p", "q", "p", "q", "p"],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="cls", fill="grp"))
        + geom_bar(position=position_fill())
        + scale_fill_discrete(values={"p": "#4C78A8", "q": "#F58518"})
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

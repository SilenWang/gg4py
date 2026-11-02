"""col：position_stack() 堆叠（数值 y，非计数）。"""

from ggcore.plot import (
    aes,
    geom_col,
    ggplot,
    position_stack,
    scale_fill_discrete,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "cls": ["a", "a", "b", "b", "c", "c"],
    "y": [1.5, 2.0, 2.4, 1.2, 0.8, 2.6],
    "grp": ["p", "q", "p", "q", "p", "q"],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="cls", y="y", fill="grp"))
        + geom_col(position=position_stack(), width=0.7)
        + scale_fill_discrete(values={"p": "#4C78A8", "q": "#F58518"})
        + scale_y_continuous(limits=(0, 5), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

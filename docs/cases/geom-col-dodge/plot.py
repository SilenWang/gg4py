"""col：position_dodge(width=0.8) + 显式柱宽 0.6。"""

from ggcore.plot import (
    aes,
    geom_col,
    ggplot,
    position_dodge,
    scale_fill_discrete,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "cls": ["a", "a", "b", "b", "c", "c"],
    "y": [2.0, 3.0, 2.5, 1.5, 1.0, 2.8],
    "grp": ["p", "q", "p", "q", "p", "q"],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="cls", y="y", fill="grp"))
        + geom_col(position=position_dodge(width=0.8), width=0.6)
        + scale_fill_discrete(values={"p": "#4C78A8", "q": "#F58518"})
        + scale_y_continuous(limits=(0, 4), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

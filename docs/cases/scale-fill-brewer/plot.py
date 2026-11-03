"""scale：离散 fill 用 brewer Set2（带完整图例）。"""

from ggcore.plot import (
    aes,
    geom_col,
    ggplot,
    position_dodge,
    scale_fill_brewer,
    scale_y_continuous,
    theme_void,
)
from ggio.frame import to_column_table

DATA = {
    "cls": ["a", "b", "c", "a", "b", "c"],
    "y": [1.2, 2.1, 1.6, 0.9, 1.5, 2.3],
    "grp": ["p", "p", "p", "q", "q", "q"],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="cls", y="y", fill="grp"))
        + geom_col(width=0.7, position=position_dodge())
        + scale_fill_brewer(palette="Set2")
        + scale_y_continuous(limits=(0, 3.2), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

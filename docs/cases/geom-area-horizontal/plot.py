"""geom_area：横向（orientation = "y"，SIL-715 #4）。

上游 `GeomArea` / `StatAlign` 都传 `ambiguous = TRUE`，横向必须写
`orientation = "y"`（或 coord_flip）；这条 case 锁住「两侧同值」的数据与画面。
"""

from ggcore.plot import (
    aes,
    geom_area,
    ggplot,
    scale_x_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "cls": ["a", "b", "c", "d", "e"],
    "v": [1.0, 2.5, 1.8, 3.2, 2.2],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(y="cls", x="v"))
        + geom_area(stat="identity", orientation="y", fill="#4C78A8")
        + scale_x_continuous(limits=(0, 4), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

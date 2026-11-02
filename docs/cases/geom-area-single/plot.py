"""area：单组（stat_align 的 `is_unique(group)` 原样通过）+ 不规则 x。"""

from ggcore.plot import (
    aes,
    geom_area,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [1.0, 1.8, 2.9, 3.4, 4.6, 5.0],
    "y": [0.8, 1.4, 1.1, 1.9, 1.5, 2.2],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_area(fill="#4C78A8")
        + scale_x_continuous(limits=(0.5, 5.5), expand=(0, 0))
        + scale_y_continuous(limits=(0, 3), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

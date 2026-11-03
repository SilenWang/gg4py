"""geom_blank + geom_rug：只训练标度 / 面板边上的短刻度。

`geom_blank()` 是 `nullGrob()`；`geom_rug(sides = "bl")` 在下边与左边各画一道短刻度。
"""

from ggcore.plot import (
    aes,
    geom_blank,
    geom_rug,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.2, 0.5, 0.8],
    "y": [0.3, 0.6, 0.9],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_blank()
        + geom_rug(sides="bl", length=0.04, linewidth=0.8 / 2.845276, colour="#4C78A8")
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

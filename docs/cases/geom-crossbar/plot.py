"""geom_crossbar：箱体 + 中位线（fatten = 2.5）。

箱体多边形 + 中位线；`middle.*` / `box.*` 参数可覆盖对应的图形参数。
"""

from ggcore.plot import (
    aes,
    geom_crossbar,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.3, 0.7],
    "y": [0.5, 0.45],
    "lo": [0.2, 0.3],
    "hi": [0.8, 0.7],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", ymin="lo", ymax="hi"))
        + geom_crossbar(width=0.3, fill="#F58518", colour="#333333", linewidth=0.8 / 2.845276)
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

"""geom_rect：两个带 alpha 的矩形。

`colour = NA`、`fill` 吃 alpha；`xmin/xmax/ymin/ymax` 直接进 `rectGrob`。
"""

from ggcore.plot import (
    aes,
    geom_rect,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "xmin": [0.1, 0.5],
    "xmax": [0.4, 0.8],
    "ymin": [0.1, 0.2],
    "ymax": [0.5, 0.6],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(
            to_column_table(DATA),
            aes(xmin="xmin", xmax="xmax", ymin="ymin", ymax="ymax"),
        )
        + geom_rect(fill="#4C78A8", colour="#333333", linewidth=0.8 / 2.845276, alpha=0.6)
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

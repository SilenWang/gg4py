"""geom_spoke：angle / radius 映射（数据空间弧度）。

`xend = x + cos(angle) * radius`、`yend = y + sin(angle) * radius` 在 `setup_data()` 里算完。
"""

import math

from ggcore.plot import (
    aes,
    geom_spoke,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.3, 0.6],
    "y": [0.3, 0.6],
    "ang": [0.0, math.pi / 4.0],
    "rad": [0.2, 0.25],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", angle="ang", radius="rad"))
        + geom_spoke(linewidth=1.2 / 2.845276, colour="#4C78A8")
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

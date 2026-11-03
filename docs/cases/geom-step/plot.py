"""geom_step：direction = "hv"。

`stairstep()` 逐 group 展开成阶梯折线，再交给 `GeomPath`。
"""

from ggcore.plot import (
    aes,
    geom_step,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.1, 0.3, 0.5, 0.7, 0.9],
    "y": [0.2, 0.5, 0.35, 0.7, 0.6],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_step(direction="hv", linewidth=1.2 / 2.845276, colour="#4C78A8")
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

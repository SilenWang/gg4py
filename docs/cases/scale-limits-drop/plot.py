"""scale：limits 之外的观测被丢弃（R 的 `Removed N rows` 口径）。"""

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.10, 0.20, 0.35, 0.50, 0.65, 0.80, 0.90, 0.25, 0.75],
    "y": [0.20, 0.95, 0.35, 0.70, 0.05, 0.80, 0.60, 0.85, 0.15],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point(shape=19, size=3.2, colour="#54A24B")
        + scale_x_continuous(limits=(0.2, 0.9), expand=(0, 0))
        + scale_y_continuous(limits=(0.2, 0.9), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

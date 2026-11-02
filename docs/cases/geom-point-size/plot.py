"""point：连续 size 映射（`scale_size_continuous` 的 1..6 mm 口径）。"""

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    scale_size_continuous,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.10, 0.25, 0.40, 0.55, 0.70, 0.85, 0.18, 0.62, 0.90],
    "y": [0.20, 0.55, 0.35, 0.70, 0.45, 0.80, 0.75, 0.15, 0.60],
    "v": [0.00, 0.25, 0.50, 0.75, 1.00, 0.35, 0.65, 0.15, 0.85],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", size="v"))
        + geom_point(shape=19, colour="#4C78A8")
        + scale_size_continuous(limits=(0, 1))
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

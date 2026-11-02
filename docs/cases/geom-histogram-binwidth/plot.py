"""histogram：显式 binwidth 0.2 + boundary 0（箱边界对齐到整数倍）。"""

from ggcore.plot import (
    aes,
    geom_histogram,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [
        0.05,
        0.12,
        0.18,
        0.22,
        0.28,
        0.31,
        0.35,
        0.38,
        0.42,
        0.46,
        0.52,
        0.58,
        0.61,
        0.66,
        0.71,
        0.75,
        0.82,
        0.88,
        0.92,
        0.97,
    ],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x"))
        + geom_histogram(binwidth=0.2, boundary=0, fill="#4C78A8")
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 8), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

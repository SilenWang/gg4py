"""histogram：`bins = 8`（两端按数据范围等分）。"""

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
        0.02,
        0.06,
        0.11,
        0.14,
        0.19,
        0.22,
        0.27,
        0.31,
        0.34,
        0.38,
        0.41,
        0.45,
        0.48,
        0.52,
        0.55,
        0.58,
        0.62,
        0.66,
        0.69,
        0.72,
        0.75,
        0.78,
        0.81,
        0.84,
        0.87,
        0.90,
        0.93,
        0.96,
        0.98,
        0.99,
    ],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x"))
        + geom_histogram(bins=8, fill="#4C78A8")
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 8), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

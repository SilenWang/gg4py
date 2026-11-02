"""histogram：横向（只映射 y，断点取 y 标度，计数落在 x）。"""

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
        0.08,
        0.12,
        0.15,
        0.18,
        0.22,
        0.25,
        0.28,
        0.35,
        0.38,
        0.42,
        0.45,
        0.48,
        0.55,
        0.58,
        0.62,
        0.65,
        0.72,
        0.75,
        0.82,
        0.85,
        0.88,
        0.92,
        0.95,
    ],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(y="x"))
        + geom_histogram(bins=6, fill="#4C78A8")
        + scale_x_continuous(limits=(0, 10), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

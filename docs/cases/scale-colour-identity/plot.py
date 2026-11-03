"""scale：colour identity（数据里已经是颜色值，原样映射）。"""

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    scale_colour_identity,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggio.frame import to_column_table

DATA = {
    "x": [0.12, 0.30, 0.52, 0.74, 0.22, 0.44, 0.66, 0.88, 0.18, 0.40],
    "y": [0.22, 0.48, 0.32, 0.66, 0.78, 0.56, 0.84, 0.42, 0.60, 0.28],
    "col": [
        "#4C78A8",
        "#4C78A8",
        "#F58518",
        "#F58518",
        "#54A24B",
        "#54A24B",
        "#E45756",
        "#E45756",
        "#72B7B2",
        "#72B7B2",
    ],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="col"))
        + geom_point(shape=19, size=3.2)
        + scale_colour_identity()
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

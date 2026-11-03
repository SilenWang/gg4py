"""scale：size_area（面积正比于值）+ 完整图例。"""

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    scale_size_area,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggio.frame import to_column_table

DATA = {
    "x": [0.12, 0.30, 0.52, 0.74, 0.22, 0.44, 0.66, 0.88],
    "y": [0.22, 0.48, 0.32, 0.66, 0.78, 0.56, 0.84, 0.42],
    "v": [0.0, 1.0, 2.0, 3.0, 4.0, 1.5, 2.5, 3.5],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", size="v"))
        + geom_point(shape=19, colour="#4C78A8")
        + scale_size_area(max_size=6)
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

"""guide：单张图例（colour 一个美学）+ theme_void。"""

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    scale_colour_discrete,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggio.frame import to_column_table

DATA = {
    "x": [1, 2, 3, 4, 5, 1.5, 2.5, 3.5, 4.5, 5.5],
    "y": [2.1, 2.8, 3.2, 3.9, 4.5, 3.4, 4.1, 2.6, 4.8, 3.0],
    "g": ["a"] * 5 + ["b"] * 5,
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="g"))
        + geom_point(shape=19, size=2.4)
        + scale_colour_discrete(values={"a": "#F8766D", "b": "#00BA38"})
        + scale_x_continuous(limits=(0, 6), expand=(0, 0))
        + scale_y_continuous(limits=(1.5, 5.5), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

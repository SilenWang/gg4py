"""guide：colour + shape 同标签合并成一张图例（`Guide$merge()` 口径）。"""

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    scale_colour_discrete,
    scale_shape_discrete,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggio.frame import to_column_table

DATA = {
    "x": [0.15, 0.35, 0.55, 0.75, 0.25, 0.45, 0.65, 0.85],
    "y": [0.20, 0.45, 0.30, 0.60, 0.75, 0.55, 0.80, 0.40],
    "g": ["a", "a", "b", "b", "a", "a", "b", "b"],
    "sh": ["s1", "s2", "s1", "s2", "s1", "s2", "s1", "s2"],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="g", shape="sh"))
        + geom_point(size=2.8)
        + scale_colour_discrete(values={"a": "#F8766D", "b": "#00BA38"})
        + scale_shape_discrete(values={"s1": 19, "s2": 15})
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

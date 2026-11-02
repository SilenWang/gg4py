"""path：两个 group 各自成路径，**保持行序**（不像 line 那样按 x 排序）。"""

from ggcore.plot import (
    aes,
    geom_path,
    ggplot,
    scale_colour_discrete,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.10, 0.50, 0.20, 0.60, 0.30, 0.70, 0.40, 0.80],
    "y": [0.20, 0.75, 0.45, 0.30, 0.70, 0.50, 0.25, 0.65],
    "g": ["a", "b", "a", "b", "a", "b", "a", "b"],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="g", group="g"))
        + geom_path(linewidth=0.50)
        + scale_colour_discrete(values={"a": "#4C78A8", "b": "#E45756"})
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

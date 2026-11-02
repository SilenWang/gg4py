"""smooth：两个 group 各自拟合（se = FALSE，只比拟合线）。"""

from ggcore.plot import (
    aes,
    geom_smooth,
    ggplot,
    scale_colour_discrete,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.0, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 0.0, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9],
    "y": [0.10, 0.22, 0.35, 0.40, 0.52, 0.60, 0.72, 0.80, 0.72, 0.60, 0.55, 0.42, 0.30, 0.20],
    "g": ["a"] * 7 + ["b"] * 7,
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="g", group="g"))
        + geom_smooth(method="loess", formula="y ~ x", se=False)
        + scale_colour_discrete(values={"a": "#3366FF", "b": "#E45756"})
        + scale_x_continuous(limits=(0, 0.9), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

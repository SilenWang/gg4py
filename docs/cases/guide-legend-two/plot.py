"""guide：两张图例并存 + 显式 order 决定堆叠顺序（M2-2）。"""

from ggcore.guide import guide_legend
from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guides,
    scale_colour_discrete,
    scale_fill_discrete,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggio.frame import to_column_table

DATA = {
    "x": [0.12, 0.28, 0.44, 0.60, 0.76, 0.88, 0.22, 0.38, 0.54, 0.70],
    "y": [0.18, 0.42, 0.30, 0.66, 0.50, 0.80, 0.74, 0.56, 0.86, 0.24],
    "g": ["a", "b", "c", "a", "b", "c", "a", "b", "c", "a"],
    "h": ["p", "q", "p", "q", "p", "q", "p", "q", "p", "q"],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="g", fill="h"))
        + geom_point(shape=21, size=2.8)
        + scale_colour_discrete(values={"a": "#F8766D", "b": "#00BA38", "c": "#619CFF"})
        + scale_fill_discrete(values={"p": "#F8766D", "q": "#00BA38"})
        + guides(
            fill=guide_legend(order=1),
            colour=guide_legend(order=2),
        )
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

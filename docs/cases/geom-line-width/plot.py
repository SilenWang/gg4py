"""line：linewidth（mm）+ 虚线 linetype（两侧同值）。"""

from ggcore.plot import (
    aes,
    geom_line,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
    "y": [0.15, 0.40, 0.30, 0.65, 0.50, 0.75, 0.45, 0.85, 0.70],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_line(colour="#2C7FB8", linewidth=0.9, linetype="dashed")
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

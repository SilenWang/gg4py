"""scale：离散 linetype（pal_linetype 的 solid / 22 / 42）+ 图例。"""

from ggcore.plot import (
    aes,
    geom_line,
    ggplot,
    scale_linetype_discrete,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65],
    "y": [0.2, 0.5, 0.3, 0.6, 0.4, 0.7, 0.35, 0.65, 0.45, 0.75, 0.5, 0.8],
    "g": ["a", "a", "a", "a", "b", "b", "b", "b", "c", "c", "c", "c"],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", linetype="g"))
        + geom_line(linewidth=1.1)
        + scale_linetype_discrete()
        + scale_x_continuous(limits=(0, 0.7), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

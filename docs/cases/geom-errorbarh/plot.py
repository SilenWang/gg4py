"""geom_errorbarh：横向误差棒（height 改名叫 width）。

4.0.3 起 `geom_errorbarh()` 是 `geom_errorbar(orientation = "y")` 的软弃用别名。
"""

from ggcore.plot import (
    aes,
    geom_errorbarh,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.5, 0.45],
    "y": [0.3, 0.7],
    "lo": [0.2, 0.3],
    "hi": [0.8, 0.7],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(y="y", x="x", xmin="lo", xmax="hi"))
        + geom_errorbarh(height=0.2, linewidth=0.9 / 2.845276, colour="#E45756")
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

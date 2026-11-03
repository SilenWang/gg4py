"""geom_errorbar：width = 0.2 的两根误差棒。

8 个顶点一条折线（上帽、竖线、下帽），NA 断开；
`width` 走 `compute_data_size(..., discrete = TRUE)`。
"""

from ggcore.plot import (
    aes,
    geom_errorbar,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.3, 0.7],
    "y": [0.5, 0.45],
    "lo": [0.2, 0.3],
    "hi": [0.8, 0.7],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", ymin="lo", ymax="hi"))
        + geom_errorbar(width=0.2, linewidth=0.9 / 2.845276, colour="#4C78A8")
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

"""geom_tile：2×2 小方块（默认 width / height = 1）。

缺省 width / height 是 `compute_data_size(..., discrete = TRUE)` 的结果（离散位置恒为 1）。
"""

from ggcore.plot import (
    aes,
    geom_tile,
    ggplot,
    scale_fill_discrete,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.25, 0.75, 0.25, 0.75],
    "y": [0.25, 0.25, 0.75, 0.75],
    "f": ["p", "q", "q", "p"],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", fill="f"))
        + geom_tile()
        + scale_fill_discrete(values={"p": "#4C78A8", "q": "#F58518"})
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

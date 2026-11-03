"""geom_linerange + geom_pointrange：区间线 + 中点。

`pointrange` 是 linerange + 点（点大小 `size * 4`）；图例 key 未映射，两层都画在面板里。
"""

from ggcore.plot import (
    aes,
    geom_linerange,
    geom_pointrange,
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
        + geom_linerange(linewidth=1.5 / 2.845276, colour="#54A24B")
        + geom_pointrange(size=1.4, linewidth=0.9 / 2.845276, colour="#333333")
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

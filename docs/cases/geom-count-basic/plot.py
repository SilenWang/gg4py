"""count：stat_sum 的 n → size（面积标度）。

参考图由 `refs:geom` 的 `count_basic` 段生成：`stat = "identity"` + 现成的
`n` 列（stat_sum 的输出形状），`scale_size_area(max_size = 7)`。
"""

from ggcore.plot import (
    aes,
    geom_count,
    ggplot,
    scale_size_area,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.2, 0.2, 0.5, 0.8, 0.8, 0.8],
    "y": [0.3, 0.3, 0.5, 0.7, 0.7, 0.7],
    "n": [2.0, 2.0, 1.0, 3.0, 3.0, 3.0],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", size="n"))
        + geom_count(stat="identity", colour="#4C78A8")
        + scale_size_area(max_size=7)
        + scale_x_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + scale_y_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": [4, 3]}

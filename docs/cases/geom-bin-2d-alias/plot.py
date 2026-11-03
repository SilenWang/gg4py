"""bin_2d：`geom_bin_2d` 别名（同一形状，固定填充）。

参考图由 `refs:geom` 的 `bin_2d_alias` 段生成：与 `geom-bin2d-basic` 同一份
bin 数据，`geom_bin_2d(stat = "identity", fill = "#4C78A8")`。
"""

from ggcore.plot import (
    aes,
    geom_bin_2d,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.166667, 0.5, 0.833333, 0.166667, 0.5, 0.833333],
    "y": [0.25, 0.25, 0.25, 0.75, 0.75, 0.75],
    "width": [0.333333, 0.333333, 0.333333, 0.333333, 0.333333, 0.333333],
    "height": [0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
    "count": [1.0, 4.0, 2.0, 3.0, 5.0, 2.0],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", width="width", height="height"))
        + geom_bin_2d(stat="identity", fill="#4C78A8")
        + scale_x_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + scale_y_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": [4, 3]}

"""quantile：三条分位线（stat_quantile 的输出形状）。

参考图由 `refs:geom` 的 `quantile_basic` 段生成：每个分位一个 group，
`geom_quantile(stat = "identity", colour = "#3366FF")`（GeomQuantile 继承
GeomPath）。
"""

from ggcore.plot import (
    aes,
    geom_quantile,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.1, 0.5, 0.9, 0.1, 0.5, 0.9, 0.1, 0.5, 0.9],
    "y": [0.15, 0.3, 0.4, 0.3, 0.5, 0.65, 0.45, 0.7, 0.9],
    "grp": ["q1"] * 3 + ["q2"] * 3 + ["q3"] * 3,
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", group="grp"))
        + geom_quantile(stat="identity", colour="#3366FF")
        + scale_x_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + scale_y_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": [4, 3]}

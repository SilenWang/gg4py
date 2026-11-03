"""contour：两条等值线（stat_contour 形状：level / x / y / group）。

参考图由 `refs:geom` 的 `contour_basic` 段生成：
`geom_contour(stat = "identity", colour = "#3366FF")`（GeomContour 继承
GeomPath）。
"""

from ggcore.plot import (
    aes,
    geom_contour,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.1, 0.3, 0.5, 0.7, 0.9, 0.1, 0.3, 0.5, 0.7, 0.9],
    "y": [0.2, 0.6, 0.75, 0.6, 0.2, 0.35, 0.7, 0.85, 0.7, 0.35],
    "level": [0.5] * 5 + [1.5] * 5,
    "grp": ["g1"] * 5 + ["g2"] * 5,
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", group="grp"))
        + geom_contour(stat="identity", colour="#3366FF")
        + scale_x_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + scale_y_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": [4, 3]}

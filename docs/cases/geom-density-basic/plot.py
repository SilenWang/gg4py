"""density：密度多边形 + 只描上沿（outline.type = "upper"）。

参考图由 `refs:geom` 的 `density_basic` 段生成：`stat = "identity"`，
y 已是密度值；`geom_density(fill = "grey35", colour = "black")`。
"""

from ggcore.plot import (
    aes,
    geom_density,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.05, 0.14, 0.23, 0.32, 0.41, 0.5, 0.59, 0.68, 0.77, 0.86, 0.95],
    "y": [0.05, 0.12, 0.3, 0.55, 0.78, 0.9, 0.85, 0.65, 0.38, 0.15, 0.04],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_density(stat="identity", fill="grey35", colour="black")
        + scale_x_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + scale_y_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": [4, 3]}

"""density_2d：`geom_density_2d` 别名（同一路径，换色）。

参考图由 `refs:geom` 的 `density_2d_alias` 段生成。
"""

from ggcore.plot import (
    aes,
    geom_density_2d,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [
        0.85,
        0.747487,
        0.5,
        0.252513,
        0.15,
        0.252513,
        0.5,
        0.747487,
        0.85,
        0.68,
        0.627279,
        0.5,
        0.372721,
        0.32,
        0.372721,
        0.5,
        0.627279,
        0.68,
    ],
    "y": [
        0.5,
        0.747487,
        0.85,
        0.747487,
        0.5,
        0.252513,
        0.15,
        0.252513,
        0.5,
        0.5,
        0.627279,
        0.68,
        0.627279,
        0.5,
        0.372721,
        0.32,
        0.372721,
        0.5,
    ],
    "level": [0.2] * 9 + [0.4] * 9,
    "grp": ["c1"] * 9 + ["c2"] * 9,
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", group="grp"))
        + geom_density_2d(stat="identity", colour="#E45756")
        + scale_x_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + scale_y_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": [4, 3]}

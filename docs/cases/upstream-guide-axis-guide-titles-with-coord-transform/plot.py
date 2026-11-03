"""上游快照复刻：轴标题不被 `coord_transform()` 冲掉。

源：guide-axis/guide-titles-with-coord-transform.svg（vdiffr 名
'guide titles with coord_transform()'）。
"""

from ggcore.plot import (
    aes,
    coord_transform,
    geom_point,
    ggplot,
    guide_axis,
    guides,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1.0], "y": [1.0]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + theme_test()
        + guides(
            x=guide_axis(title="x (primary)"),
            y=guide_axis(title="y (primary)"),
            **{
                "x.sec": guide_axis(title="x (secondary)"),
                "y.sec": guide_axis(title="y (secondary)"),
            },
        )
        + coord_transform()
    )
    return {"plot": p, "size": [10, 8]}

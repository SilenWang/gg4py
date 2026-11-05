"""上游快照复刻：`guide_none(title = )` 只留轴标题，不画刻度。

源：guide-axis/position-guide-titles.svg（vdiffr 名 'position guide titles'）。
"""

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_none,
    guides,
    labs,
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
            x=guide_none(title="x (primary)"),
            y=guide_none(title="y (primary)"),
            **{
                "x.sec": guide_none(title="x (secondary)"),
                "y.sec": guide_none(title="y (secondary)"),
            },
        )
        + labs(title="position guide titles")
    )
    return {"plot": p, "size": [10, 8]}

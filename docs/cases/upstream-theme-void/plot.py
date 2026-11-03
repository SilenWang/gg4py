"""上游快照复刻。

源：theme/theme-void.svg（vdiffr 名 'theme_void'）。
自动生成：`pixi run snapshots:import`。expected.svg 是上游那份，未改写。
"""

from ggcore.plot import (
    aes,
    facet_wrap,
    geom_point,
    ggplot,
    labs,
)
from ggcore.theme import (
    theme_void,
)
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 2, 3], "z": ["a", "b", "a"], "a": [1, 1, 1]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="z"))
        + geom_point()
        + facet_wrap("a")
        + theme_void()
        + labs(title="theme_void")
    )
    return {"plot": p, "size": [10, 8]}

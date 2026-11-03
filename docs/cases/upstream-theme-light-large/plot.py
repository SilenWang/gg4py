"""上游快照复刻。

源：theme/theme-light-large.svg（vdiffr 名 'theme_light_large'）。
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
    theme_light,
)
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 2, 3], "z": ["a", "b", "a"], "a": [1, 1, 1]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="z"))
        + geom_point()
        + facet_wrap("a")
        + theme_light(base_size=33)
        + labs(title="theme_light_large")
    )
    return {"plot": p, "size": [10, 8]}

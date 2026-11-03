"""上游快照复刻。

源：geom-dotplot/stackratio-1-5.svg（vdiffr 名 'stackratio = 1.5'）。
自动生成：`pixi run snapshots:import`。expected.svg 是上游那份，未改写。
"""

from ggcore.plot import (
    aes,
    geom_dotplot,
    geom_hline,
    ggplot,
    labs,
)
from ggcore.theme import (
    theme_test,
)
from ggio.frame import to_column_table

DATA = {"x": [1.0, 1.0, 1.0, 2.0, 2.0]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x"))
        + geom_hline(yintercept=0.0)
        + geom_dotplot(aes(x="x"), binwidth=0.5, stackdir="down", stackratio=1.5, fill=None)
        + geom_dotplot(aes(x="x + 3"), binwidth=0.5, stackdir="up", stackratio=1.5, fill=None)
        + geom_dotplot(aes(x="x + 6"), binwidth=0.5, stackdir="center", stackratio=1.5, fill=None)
        + geom_dotplot(
            aes(x="x + 9"), binwidth=0.5, stackdir="centerwhole", stackratio=1.5, fill=None
        )
        + theme_test()
        + labs(title="stackratio = 1.5")
    )
    return {"plot": p, "size": [10, 8]}

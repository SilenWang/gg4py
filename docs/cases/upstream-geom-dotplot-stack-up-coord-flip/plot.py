"""上游快照复刻。

源：geom-dotplot/stack-up-with-coord-flip.svg（vdiffr 名 'stack up with coord_flip'）。
自动生成：`pixi run snapshots:import`。expected.svg 是上游那份，未改写。
"""

from ggcore.plot import (
    aes,
    coord_flip,
    geom_dotplot,
    ggplot,
    labs,
)
from ggcore.theme import (
    theme_test,
)
from ggio.frame import to_column_table

DATA = {
    "x": [
        -0.3142316959504725,
        2.403375078778703,
        -0.718263962664052,
        -1.7606109629935416,
        -1.1252811743977724,
        -0.7195405657515067,
        1.310223977253826,
        0.45189845282321606,
        0.15217740702295823,
        0.6533707827767958,
        -0.9473355385324345,
        -1.071086252558543,
        -0.17605937002612163,
        1.8720502082968995,
        -0.5103383795997904,
        1.4388904417981778,
        1.1531709539424315,
        -0.15483976358124263,
        -0.2599055202700481,
        0.4713667708621337,
    ]
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x"))
        + geom_dotplot(binwidth=0.4, stackdir="up")
        + coord_flip()
        + theme_test()
        + labs(title="stack up with coord_flip")
    )
    return {"plot": p, "size": [10, 8]}

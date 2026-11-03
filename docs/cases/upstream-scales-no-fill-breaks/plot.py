"""上游快照复刻：no fill breaks (no legend)。

`scale_fill_continuous(breaks = NULL)` → 无图例。
源：scales-breaks-labels/no-fill-breaks-no-legend.svg。
vdiffr 名：no fill breaks (no legend)。

expected.svg 是上游那份，未改写。
"""

from ggcore.plot import aes, geom_point, ggplot, labs, scale_fill_continuous
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 2, 3]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x=1, y="y", fill="x"))
        + geom_point(shape=21)
        + scale_fill_continuous(breaks=None)
        + theme_test()
        + labs(title="no fill breaks (no legend)")
    )
    return {"plot": p, "size": [10, 8]}

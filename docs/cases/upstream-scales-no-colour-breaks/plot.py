"""上游快照复刻：no colour breaks (no legend)。

`scale_colour_continuous(breaks = NULL)` → 无图例。
源：scales-breaks-labels/no-colour-breaks-no-legend.svg。
vdiffr 名：no colour breaks (no legend)。

expected.svg 是上游那份，未改写。
"""

from ggcore.plot import aes, geom_point, ggplot, labs, scale_colour_continuous
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 2, 3]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x=1, y="y", colour="x"))
        + geom_point()
        + scale_colour_continuous(breaks=None)
        + theme_test()
        + labs(title="no colour breaks (no legend)")
    )
    return {"plot": p, "size": [10, 8]}

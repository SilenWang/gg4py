"""上游快照复刻：no y breaks。

`scale_y_continuous(breaks = NULL)`。
源：scales-breaks-labels/no-y-breaks.svg。
vdiffr 名：no y breaks。

expected.svg 是上游那份，未改写。
"""

from ggcore.plot import aes, geom_point, ggplot, labs, scale_y_continuous
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 2, 3]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + scale_y_continuous(breaks=None)
        + theme_test()
        + labs(title="no y breaks")
    )
    return {"plot": p, "size": [10, 8]}

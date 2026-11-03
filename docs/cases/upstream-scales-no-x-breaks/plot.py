"""上游快照复刻：no x breaks。

`scale_x_continuous(breaks = NULL)`。
源：scales-breaks-labels/no-x-breaks.svg。
vdiffr 名：no x breaks。

expected.svg 是上游那份，未改写。
"""

from ggcore.plot import aes, geom_point, ggplot, labs, scale_x_continuous
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 2, 3]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + scale_x_continuous(breaks=None)
        + theme_test()
        + labs(title="no x breaks")
    )
    return {"plot": p, "size": [10, 8]}

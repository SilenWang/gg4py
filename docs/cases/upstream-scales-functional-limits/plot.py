"""上游快照复刻：functional limits。

`scale_y_continuous(limits = <function>)`。
源：scales-breaks-labels/functional-limits.svg。
vdiffr 名：functional limits。

expected.svg 是上游那份，未改写。
"""

import math

from ggcore.plot import aes, geom_bar, ggplot, labs, scale_y_continuous
from ggcore.theme import theme_test
from ggio.frame import to_column_table

#: `mpg` 的 `class × drv` 计数（只保留本图用到的两列；数据 = 234 行）。
COUNTS = {
    "2seater": {"r": 5},
    "compact": {"4": 12, "f": 35},
    "midsize": {"4": 3, "f": 38},
    "minivan": {"f": 11},
    "pickup": {"4": 33},
    "subcompact": {"4": 4, "f": 22, "r": 9},
    "suv": {"4": 51, "r": 11},
}
DRIVES = ("4", "f", "r")
DATA = {
    "class": [cls for cls, row in COUNTS.items() for drv in DRIVES for _ in range(row.get(drv, 0))],
    "drv": [drv for cls, row in COUNTS.items() for drv in DRIVES for _ in range(row.get(drv, 0))],
}


def _limiter(by):
    def limits(values):
        low, high = values
        return (math.floor(low / by) * by, math.ceil(high / by) * by)

    return limits


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="class"))
        + geom_bar(aes(fill="drv"))
        + scale_y_continuous(limits=_limiter(50))
        + theme_test()
        + labs(title="functional limits")
    )
    return {"plot": p, "size": [10, 8]}

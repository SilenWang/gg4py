"""上游快照复刻：date。

月主断点 / 周次断点 + `label_date("%m/%d")`。
源：scales-breaks-labels/date.svg。
vdiffr 名：date。

expected.svg 是上游那份，未改写。
"""

import datetime as _dt

from ggcore.plot import aes, geom_blank, ggplot, labs, scale_x_date
from ggcore.scales_date import breaks_width_date, date_formatter
from ggcore.theme import element_line, theme, theme_test
from ggio.frame import to_column_table

DATA = {
    "x_num": [1, 3],
    "x_chr": ["a", "b"],
    "x_date": [_dt.date(2012, 2, 29), _dt.date(2012, 6, 8)],
    "x_log": [1, 1e4],
    "y": [1, 3],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x_date", y="y"))
        + geom_blank()
        + scale_x_date(
            labels=date_formatter("date", "%m/%d"),
            breaks=breaks_width_date("1 month"),
            minor_breaks=breaks_width_date("1 week"),
        )
        + theme_test()
        + theme(
            **{
                "panel.grid.major": element_line(colour="grey30", linewidth=0.5),
                "panel.grid.minor": element_line(colour="grey70"),
            }
        )
        + labs(x=None, y=None, title="date")
    )
    return {"plot": p, "size": [10, 8]}

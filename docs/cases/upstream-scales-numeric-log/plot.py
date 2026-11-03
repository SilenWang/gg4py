"""上游快照复刻：numeric log。

x 走 log2、y 走 log10。
源：scales-breaks-labels/numeric-log.svg。
vdiffr 名：numeric log。

expected.svg 是上游那份，未改写。
"""

from ggcore.plot import (
    aes,
    geom_blank,
    ggplot,
    labs,
    scale_x_continuous,
    scale_y_log10,
)
from ggcore.theme import element_line, theme, theme_test
from ggio.frame import to_column_table

DATA = {
    "x_num": [1, 3],
    "x_chr": ["a", "b"],
    "x_date": ["2012-02-29", "2012-06-08"],
    "x_log": [1, 1e4],
    "y": [1, 3],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x_log", y="x_log"))
        + geom_blank()
        + scale_x_continuous(trans="log2")
        + scale_y_log10()
        + theme_test()
        + theme(
            **{
                "panel.grid.major": element_line(colour="grey30", linewidth=0.5),
                "panel.grid.minor": element_line(colour="grey70"),
            }
        )
        + labs(x=None, y=None, title="numeric-log")
    )
    return {"plot": p, "size": [10, 8]}

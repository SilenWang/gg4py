"""上游快照复刻：numeric。

主 / 次网格线 + 显式断点。
源：scales-breaks-labels/numeric.svg。
vdiffr 名：numeric。

expected.svg 是上游那份，未改写。
"""

from ggcore.plot import (
    aes,
    geom_blank,
    ggplot,
    labs,
    scale_x_continuous,
    scale_y_continuous,
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
        ggplot(to_column_table(DATA), aes(x="x_num", y="y"))
        + geom_blank()
        + scale_x_continuous(breaks=(1, 2, 3), minor_breaks=(1.25, 2.75))
        + scale_y_continuous(breaks=(1, 2, 3), minor_breaks=(1.25, 2.75))
        + theme_test()
        + theme(
            **{
                "panel.grid.major": element_line(colour="grey30", linewidth=0.5),
                "panel.grid.minor": element_line(colour="grey70"),
            }
        )
        + labs(x=None, y=None, title="numeric")
    )
    return {"plot": p, "size": [10, 8]}

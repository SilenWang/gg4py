"""上游快照复刻：numeric-exp。

x / y 都走 `transform_exp(2)`。
源：scales-breaks-labels/numeric-exp.svg。
vdiffr 名：numeric-exp。

expected.svg 是上游那份，未改写。
"""

from ggcore.plot import aes, geom_blank, ggplot, labs, scale_x_continuous, scale_y_continuous
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
        ggplot(to_column_table(DATA), aes(x="x_num", y="x_num"))
        + geom_blank()
        + scale_x_continuous(trans=("exp", 2))
        + scale_y_continuous(trans=("exp", 2))
        + theme_test()
        + theme(
            **{
                "panel.grid.major": element_line(colour="grey30", linewidth=0.5),
                "panel.grid.minor": element_line(colour="grey70"),
            }
        )
        + labs(x=None, y=None, title="numeric-exp")
    )
    return {"plot": p, "size": [10, 8]}

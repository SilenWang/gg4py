"""示例 3 / 9 · 柱状图：`geom_col()` 用给定高度画柱，分组靠 `fill` 映射。"""

from ggcore.plot import aes, geom_col, ggplot, labs, position_dodge, theme_minimal
from ggio.frame import to_column_table

needs = ["numpy"]

DATA = {
    "month": ["Jan", "Feb", "Mar", "Apr"] * 2,
    "value": [12.0, 18.5, 9.5, 22.0, 8.0, 11.5, 16.0, 14.5],
    "kind": ["north"] * 4 + ["south"] * 4,
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="month", y="value", fill="kind"))
        + geom_col(position=position_dodge(width=0.8), width=0.6)
        + labs(title="Bars by region", subtitle="geom_col + position_dodge", x="month", y="value")
        + theme_minimal()
    )
    return {"plot": p, "size": [5.0, 3.5]}

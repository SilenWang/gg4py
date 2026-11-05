"""示例 2 / 9 · 折线 + 分组颜色：离散列映射到 colour，图例自动出现。"""

from ggcore.plot import aes, geom_line, geom_point, ggplot, labs, theme_minimal
from ggio.frame import to_column_table

needs = ["numpy"]

DATA = {
    "t": [1, 2, 3, 4, 5, 6, 7, 8] * 2,
    "value": [2.1, 2.9, 4.2, 4.8, 6.1, 6.0, 7.4, 8.1, 1.8, 2.4, 3.1, 4.0, 4.6, 5.5, 6.2, 7.0],
    "group": ["a"] * 8 + ["b"] * 8,
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="t", y="value", colour="group"))
        + geom_line()
        + geom_point(size=1.8)
        + labs(title="Two series", subtitle="colour maps a discrete column", x="t", y="value")
        + theme_minimal()
    )
    return {"plot": p, "size": [5.0, 3.5]}

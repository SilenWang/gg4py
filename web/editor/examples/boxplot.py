"""示例 4 / 9 · 箱线图：离散 x × 连续 y，五数 + 须线 + 离群点都由 `geom_boxplot` 算。"""

from ggcore.plot import aes, geom_boxplot, ggplot, labs, theme_minimal
from ggio.frame import to_column_table

needs = ["numpy"]

DATA = {
    "group": ["a"] * 12 + ["b"] * 12 + ["c"] * 12,
    "value": [
        3.2,
        4.1,
        4.4,
        5.0,
        5.1,
        5.3,
        5.5,
        5.8,
        6.0,
        6.2,
        7.1,
        9.4,
        2.1,
        3.0,
        3.6,
        4.0,
        4.2,
        4.4,
        4.5,
        4.8,
        5.0,
        5.2,
        6.0,
        7.8,
        4.0,
        5.2,
        5.6,
        6.0,
        6.1,
        6.4,
        6.6,
        6.8,
        7.0,
        7.4,
        8.2,
        10.1,
    ],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="group", y="value"))
        + geom_boxplot(fill="#cfe3f3", colour="#2b6cb0")
        + labs(title="Boxplots", subtitle="five numbers per group", x="group", y="value")
        + theme_minimal()
    )
    return {"plot": p, "size": [5.0, 3.5]}

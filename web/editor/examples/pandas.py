"""示例 8 / 9 · pandas 输入：DataFrame 直接喂给 `ggplot()`。

pandas 的 wasm 轮子（含 dateutil / pytz / six）只在这一页真正跑时才下载，
`needs` 里写了才进加载计划。
"""

import pandas as pd

from ggcore.plot import aes, geom_point, ggplot, labs, theme_minimal
from ggio.frame import to_column_table

needs = ["numpy", "pandas"]

FRAME = pd.DataFrame(
    {
        "size": [1.2, 1.8, 2.4, 3.0, 3.6, 4.2, 4.8, 5.4],
        "price": [3.1, 4.4, 5.0, 6.8, 7.2, 8.9, 9.1, 11.0],
        "kind": ["flat", "flat", "flat", "house", "house", "house", "villa", "villa"],
    }
)


def build():
    p = (
        ggplot(to_column_table(FRAME), aes(x="size", y="price", colour="kind"))
        + geom_point(size=3.0)
        + labs(
            title="pandas DataFrame input",
            subtitle="same pipeline, a DataFrame on the way in",
            x="size",
            y="price",
        )
        + theme_minimal()
    )
    return {"plot": p, "size": [5.0, 3.5]}

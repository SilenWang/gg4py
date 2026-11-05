"""示例 3 / 3：pandas DataFrame 输入（`needs` 里多一个 pandas —— 按需下载）。

`ggio.frame.to_column_table()` 的输入边界是 DataFrame-like：pandas / Arrow /
dict of arrays。这一页专门走 pandas，页面只在切到它时才 `loadPackage("pandas")`
（+4.18 MB 的 wheel 与它的三个纯 Python 依赖），boot 阶段一个字节都不下。
"""

from ggcore.plot import aes, geom_col, ggplot, labs, theme_minimal
from ggio.frame import to_column_table

needs = ["numpy", "pandas"]


def frame():
    """pandas 在这里才 import：不跑这一页就不会触发 `import pandas`。"""
    import pandas as pd

    return pd.DataFrame(
        {
            "category": ["A", "B", "C", "D", "E", "F"],
            "value": [12.0, 19.5, 8.2, 22.4, 15.1, 9.8],
            "batch": ["one", "one", "one", "two", "two", "two"],
        }
    )


def build():
    p = (
        ggplot(to_column_table(frame()), aes(x="category", y="value", fill="batch"))
        + geom_col()
        + labs(
            title="pandas DataFrame input", subtitle="pandas loaded on demand", x=None, y="value"
        )
        + theme_minimal()
    )
    return {"plot": p, "size": [5.0, 3.6]}

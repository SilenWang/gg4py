"""示例 1 / 9 · 最小散点图：八行数据 + 一行语法。

每个示例都是「一页代码」：`build()` 返回 `{"plot": ..., "size": [宽, 高]}`，页面把
它交给内核出图。`needs` 声明这段代码要用到的 Pyodide 包（编辑器按它懒加载）。
"""

from ggcore.plot import aes, geom_point, ggplot, labs, theme_minimal
from ggio.frame import to_column_table

needs = ["numpy"]

DATA = {"x": [1, 2, 3, 4, 5, 6, 7, 8], "y": [2.1, 3.4, 2.8, 4.9, 5.2, 6.4, 5.9, 7.2]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point(size=2.4, colour="#2b6cb0")
        + labs(title="Hello, gg4py", subtitle="eight rows, one line of syntax", x="x", y="y")
        + theme_minimal()
    )
    # 5.0 × 3.5 in = 360 × 252 pt：整数像素，导出 1× 与屏幕逐像素可对。
    return {"plot": p, "size": [5.0, 3.5]}

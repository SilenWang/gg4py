"""示例 9 / 9 · CSV 数据：读数据面板写进虚拟文件系统的 `data.csv`。

不用 pandas：`ggio.csv.read_csv()` 只用标准库（`csv` + numpy），贴一段 CSV 就能
出图，价格是零轮子下载。左侧「数据输入」面板里显示的 CSV 就是这张图的数据。
"""

from ggcore.plot import aes, geom_col, geom_point, ggplot, labs, theme_minimal
from ggio.csv import read_csv

needs = ["numpy"]


def build():
    table = read_csv("data.csv")
    p = (
        ggplot(table, aes(x="class", y="value"))
        + geom_col(fill="#4C78A8", width=0.7)
        + geom_point(size=2.0, colour="#1a202c")
        + labs(title="CSV input", subtitle="read_csv('data.csv') — no pandas", x="class", y="value")
        + theme_minimal()
    )
    return {"plot": p, "size": [5.0, 3.5]}

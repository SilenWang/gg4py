"""boxplot：原始数据 + stat_boxplot

参考图由 `pixi run -e refs refs:stat` 生成（ggplot2 4.0.3 + svglite，
`tools/refs/stat_ref.R` 的 `stat-boxplot-stat` 段）：两边同一份数据、宽度、颜色；
`expand = c(0, 0)` 让面板就是整页。

数据里只有 `cls` 与 `v`：五数、须线、离群点全部由 `stat_boxplot()` 从原始观测
算出来（`outliers` 在 ggcore 里是 `"c(20)"` 文本列，见 `docs/notes/stat.md`）。
"""

from ggcore.plot import (
    aes,
    geom_boxplot,
    ggplot,
    scale_y_continuous,
    theme_void,
)
from ggio.frame import to_column_table

DATA = {
    "cls": ["a"] * 9 + ["b"] * 9,
    "v": [1, 2, 3, 4, 5, 6, 7, 8, 20, 2, 3, 4, 5, 6, 7, 8, 9, 25],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="cls", y="v"))
        + geom_boxplot(fill="#4C78A8", width=0.6)
        + scale_y_continuous(limits=(0, 26), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

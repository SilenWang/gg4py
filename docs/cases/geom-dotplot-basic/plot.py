"""dotplot：按 count 展开 + 向上堆叠。

参考图由 `refs:geom` 的 `dotplot_stat` 段生成（R 侧走真实 `stat_bindot`，
因为 `geom_dotplot` 的构造器不接受 `stat =`）。这里把 stat 输出的 bin
（x / binwidth / count）当绘制输入：`setup_data()` 按 count 展开成点，
在非堆叠轴上堆叠。
"""

from ggcore.plot import (
    aes,
    geom_dotplot,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.15, 0.35, 0.6, 0.8],
    "y": [0.0, 0.0, 0.0, 0.0],
    "binwidth": [0.1, 0.1, 0.1, 0.1],
    "count": [1.0, 1.0, 3.0, 2.0],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", binwidth="binwidth", count="count"))
        + geom_dotplot(stat="identity", fill="#4C78A8", colour="black", dotsize=1)
        + scale_x_continuous(limits=(0.0625, 0.8875), expand=(0.0, 0.0))
        + scale_y_continuous(limits=(-0.05, 1.05), expand=(0.0, 0.0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": [4, 3]}

"""横向 histogram：只映射 y 的连续轴 + 默认 stat_bin

参考图由 `pixi run -e refs refs:stat` 生成（ggplot2 4.0.3 + svglite，
`tools/refs/stat_ref.R` 的 `stat-histogram-horizontal` 段）：同一份数据、
断点、颜色；`expand = c(0, 0)` 让面板就是整页。

这张 case 守的是「横向 histogram」的轴选择：数据里只有 `y`，`stat_bin()` 的
断点必须取自 **y 标度**（上游 `StatBin$compute_group()` 的
`flipped_names(flipped_aes)$x`），计数落在 x 轴上；输出再翻回横向
（`x = count`、`y = 箱中心`）。竖向路径见 `stat-histogram-bin`。
"""

from ggcore.plot import (
    aes,
    geom_histogram,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggio.frame import to_column_table

DATA = {"x": [1, 1, 2, 2, 2, 3, 4, 4, 4, 4]}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(y="x"))
        + geom_histogram(binwidth=1, boundary=0, fill="#4C78A8")
        + scale_x_continuous(limits=(0, 5), expand=(0, 0))
        + scale_y_continuous(expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

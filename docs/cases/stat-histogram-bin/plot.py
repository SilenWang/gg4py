"""histogram：原始数据 + 默认 stat_bin

参考图由 `pixi run -e refs refs:stat` 生成（ggplot2 4.0.3 + svglite，
`tools/refs/stat_ref.R` 的 `stat-histogram-bin` 段）：两边同一份数据、断点、颜色；
`expand = c(0, 0)` 让面板就是整页（theme_void 没有轴 / 图例 / 边距）。

这张 case 覆盖 stat 的端到端路径：数据里只有 `x`，`y` 由 `stat_bin()` 的
`after_stat(count)` 补出来（`geom_histogram()` 的默认 stat 就是 `bin`）。
`binwidth = 1` + `boundary = 0` 让断点落在整数上，两边的箱完全一致。
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
        ggplot(to_column_table(DATA), aes(x="x"))
        + geom_histogram(binwidth=1, boundary=0, fill="#4C78A8")
        + scale_x_continuous(limits=(0, 5), expand=(0, 0))
        + scale_y_continuous(limits=(0, 4.5), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

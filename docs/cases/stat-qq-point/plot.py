"""qq：理论分位数 vs 样本分位数（正态分布）。

参考图由 `pixi run -e refs refs:stat-longtail` 生成（ggplot2 4.0.3 + svglite，
`tools/refs/stat_longtail_ref.R` 的 `stat-qq-point` 段）：两边同一份数据、同一套
`theme_void` + `expand = c(0, 0)`，所以面板就是整页。

`stat_qq()` 的默认 geom 是 `point`；`smaple` 是唯一输入美学，`x` / `y` 由 stat 的
`default_aes`（`x = after_stat(theoretical)`、`y = after_stat(sample)`）补出来。
"""

from ggcore.plot import aes, ggplot, scale_x_continuous, scale_y_continuous, stat_qq, theme_void
from ggio.frame import to_column_table

DATA = {"v": [1.2, 2.4, 2.9, 3.1, 3.8, 4.5, 5.1, 5.2, 6.0, 7.7]}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(sample="v"))
        + stat_qq()
        + scale_x_continuous(limits=(-1.8, 1.8), expand=(0, 0))
        + scale_y_continuous(limits=(0.5, 8.5), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

"""sum：同一位置上的观测计数（`n` → `size`）。

参考图由 `pixi run -e refs refs:stat-longtail` 生成（`stat-sum-count` 段）。
注意这里**不传**独立的 `size`：`StatSum$default_aes` 已经把 `size` 映射到
`after_stat(n)`，位置越挤的点越大——这就是 `geom_count()` 的口径。
"""

from ggcore.plot import (
    aes,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    stat_sum,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {"x": [1, 1, 2, 2, 2], "y": [1, 1, 2, 3, 3]}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + stat_sum()
        + scale_x_continuous(limits=(0.5, 2.5), expand=(0, 0))
        + scale_y_continuous(limits=(0.5, 3.5), expand=(0, 0))
        + theme_void()
        # 参考图的 R 侧是 `theme_case()` = theme_void() + legend.position = "none"
        # （`tools/refs/stat_longtail_ref.R`），`size` 映射到 `n` 也不出图例。
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

"""smooth：原始数据 + stat_smooth(loess)

参考图由 `pixi run -e refs refs:stat` 生成（ggplot2 4.0.3 + svglite，
`tools/refs/stat_ref.R` 的 `stat-smooth-loess` 段）。R 侧显式用
`loess.control(surface = "direct", statistics = "exact")`：这是 gg4py 实现的算法
口径；R 默认的 `surface = "interpolate"` 是 kd 树插值，见 `docs/notes/stat.md`
「已知差异」。

数据里只有 `x` / `y`：拟合线、`se` 带、置信区间全部由 `stat_smooth()` 算出来。
"""

from ggcore.plot import (
    aes,
    geom_smooth,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggio.frame import to_column_table

DATA = {
    "x": [
        0.0,
        0.07142857142857142,
        0.14285714285714285,
        0.21428571428571427,
        0.2857142857142857,
        0.35714285714285715,
        0.42857142857142855,
        0.5,
        0.5714285714285714,
        0.6428571428571429,
        0.7142857142857143,
        0.7857142857142857,
        0.8571428571428571,
        0.9285714285714286,
        1.0,
    ],
    "y": [0.1, 0.35, 0.32, 0.45, 0.5, 0.48, 0.62, 0.6, 0.7, 0.68, 0.78, 0.82, 0.8, 0.9, 0.95],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_smooth(method="loess", formula="y ~ x", se=True, fill="grey60")
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1.1), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

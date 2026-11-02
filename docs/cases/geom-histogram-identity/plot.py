"""histogram：identity stat + width 列

参考图由 `pixi run -e refs refs:geom` 生成（ggplot2 4.0.3 + svglite，
`tools/refs/geom_ref.R` 的 `histogram_identity` 段）：两边同一份数据、limits、颜色与大小；
`expand = c(0, 0)` 让面板就是整页（theme_void 没有轴 / 图例 / 边距）。

绘制入口是 M1-7 的真管线：`plot.py` 返回 `{"plot": ggplot(...) + geom_*()}`，
`ggcore.plotspec.build_scene()` 走 `build_plot()` + `ggcore.geom.scene`。
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

DATA = {
    "x": [0.5, 1.5, 2.5, 3.5],
    "y": [0.2, 0.5, 0.75, 0.4],
    "w": [1, 1, 1, 1],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", width="w"))
        + geom_histogram(stat="identity", fill="#4C78A8")
        + scale_x_continuous(limits=(0, 4), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

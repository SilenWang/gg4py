"""smooth：identity stat + se 带

参考图由 `pixi run -e refs refs:geom` 生成（ggplot2 4.0.3 + svglite，
`tools/refs/geom_ref.R` 的 `smooth_identity` 段）：两边同一份数据、limits、颜色与大小；
`expand = c(0, 0)` 让面板就是整页（theme_void 没有轴 / 图例 / 边距）。

绘制入口是 M1-7 的真管线：`plot.py` 返回 `{"plot": ggplot(...) + geom_*()}`，
`ggcore.plotspec.build_scene()` 走 `build_plot()` + `ggcore.geom.scene`。
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
    "x": [1, 2, 3, 4, 5, 6],
    "y": [1.0, 1.6, 2.1, 2.7, 3.1, 3.8],
    "ymin": [0.6, 1.2, 1.7, 2.3, 2.7, 3.4],
    "ymax": [1.4, 2.0, 2.5, 3.1, 3.5, 4.2],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", ymin="ymin", ymax="ymax"))
        + geom_smooth(stat="identity", colour="#3366FF", fill="grey60", alpha=0.4)
        + scale_x_continuous(limits=(0, 7), expand=(0, 0))
        + scale_y_continuous(limits=(0, 5), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

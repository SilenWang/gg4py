"""boxplot：五数预计算

参考图由 `pixi run -e refs refs:geom` 生成（ggplot2 4.0.3 + svglite，
`tools/refs/geom_ref.R` 的 `boxplot_identity` 段）：两边同一份数据、limits、颜色与大小；
`expand = c(0, 0)` 让面板就是整页（theme_void 没有轴 / 图例 / 边距）。

绘制入口是 M1-7 的真管线：`plot.py` 返回 `{"plot": ggplot(...) + geom_*()}`，
`ggcore.plotspec.build_scene()` 走 `build_plot()` + `ggcore.geom.scene`。
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
    "cls": ["a", "b"],
    "y0": [0.1, 0.2],
    "lo": [0.3, 0.35],
    "mid": [0.5, 0.5],
    "hi": [0.7, 0.65],
    "y1": [0.9, 0.8],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(
            to_column_table(DATA),
            aes(x="cls", ymin="y0", lower="lo", middle="mid", upper="hi", ymax="y1"),
        )
        + geom_boxplot(stat="identity", width=0.6, fill="#4C78A8")
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

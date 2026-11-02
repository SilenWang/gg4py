"""point：shape + colour 双离散映射

参考图由 `pixi run -e refs refs:geom` 生成（ggplot2 4.0.3 + svglite，
`tools/refs/geom_ref.R` 的 `point_shapes` 段）：两边同一份数据、limits、颜色与大小；
`expand = c(0, 0)` 让面板就是整页（theme_void 没有轴 / 图例 / 边距）。

绘制入口是 M1-7 的真管线：`plot.py` 返回 `{"plot": ggplot(...) + geom_*()}`，
`ggcore.plotspec.build_scene()` 走 `build_plot()` + `ggcore.geom.scene`。
"""

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    scale_colour_discrete,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggio.frame import to_column_table

DATA = {
    "x": [0.1, 0.35, 0.65, 0.9] * 4,
    "y": [0.15] * 4 + [0.4] * 4 + [0.6] * 4 + [0.85] * 4,
    "g": ["a", "b", "a", "b"] * 4,
    # 19 = 实心圆、15 = 实心方；R 的 shape 只有离散标度，所以两种符号各用一层。
    "sh": [19, 15, 19, 15] * 4,
}


def _rows(shape: int):
    keep = [value == shape for value in DATA["sh"]]
    subset = {
        name: [item for item, flag in zip(values, keep, strict=True) if flag]
        for name, values in DATA.items()
    }
    return to_column_table(subset)


SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="g", shape="sh"))
        + geom_point(data=_rows(19), shape=19, size=9 / 2.845276, stroke=0)
        + geom_point(data=_rows(15), shape=15, size=9 / 2.845276, stroke=0)
        + scale_colour_discrete(values={"a": "#F8766D", "b": "#00BA38"})
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

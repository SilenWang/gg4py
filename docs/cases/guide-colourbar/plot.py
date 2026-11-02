"""guide：连续 colourbar（渐变条 + 刻度 + 标签）。

**ci = false**：渐变条在 IR 里是 256 条 0.34pt 的细矩形，resvg 光栅化后整体
偏白约 30%（R/svglite 用 1×300 的位图）。差值集中在色条自身，属于渲染口径
问题而不是 guide 的数据口径——参考图照常生成，待渲染侧修好后翻 ci = true。
"""

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggio.frame import to_column_table

DATA = {
    "x": [0.10, 0.20, 0.35, 0.50, 0.65, 0.80, 0.90, 0.25, 0.75],
    "y": [0.20, 0.50, 0.35, 0.70, 0.45, 0.80, 0.60, 0.85, 0.15],
    "v": [0.00, 0.12, 0.25, 0.38, 0.50, 0.62, 0.75, 0.88, 1.00],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="v"))
        + geom_point(shape=19, size=3.2)
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

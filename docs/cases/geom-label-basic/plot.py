"""label：圆角矩形背景 + 内边距。

参考图由 `refs:geom` 的 `label_basic` 段生成：`geom_label(size = 5,
colour = "white", fill = "#4C78A8")`。背景框尺寸按 `labelGrob()` 的几何
（文字宽高 + 内边距 + descent 平衡）算，`label.r` 的圆角在 72dpi 下不足
1.5px，IR 没有圆角矩形节点，用方角矩形表达（见 `docs/notes/geom.md`）。
"""

from ggcore.plot import (
    aes,
    geom_label,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.3, 0.7],
    "y": [0.5, 0.5],
    "label": ["A", "BB"],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", label="label"))
        + geom_label(size=5, colour="white", fill="#4C78A8")
        + scale_x_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + scale_y_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": [4, 3]}

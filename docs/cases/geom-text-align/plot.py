"""text / align：hjust 三态（左 / 中 / 右）。

参考图由 `pixi run -e refs refs:geom`（ggplot2 4.0.3 + svglite）的
`text_align` 段生成：`geom_text(size = 5)`，hjust 映射到 0 / 0.5 / 1。
"""

from ggcore.plot import (
    aes,
    geom_text,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.5, 0.5, 0.5],
    "y": [0.2, 0.5, 0.8],
    "label": ["left", "centre", "right"],
    "hj": [0.0, 0.5, 1.0],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", label="label", hjust="hj"))
        + geom_text(size=5)
        + scale_x_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + scale_y_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": [4, 3]}

"""function：x / y 网格折线（stat_function 的输出形状）。

参考图由 `refs:geom` 的 `function_basic` 段生成：`geom_function(stat =
"identity")` 画一条连续曲线；多个 group 时上游会发警告（见
`docs/notes/geom.md`）。
"""

from ggcore.plot import (
    aes,
    geom_function,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
    "y": [0.1, 0.22, 0.35, 0.48, 0.6, 0.68, 0.72, 0.68, 0.58, 0.45, 0.3],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_function(stat="identity", colour="black")
        + scale_x_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + scale_y_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": [4, 3]}

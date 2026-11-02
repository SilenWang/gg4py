"""area：默认 stat_align + position stack

参考图由 `pixi run -e refs refs:stat` 生成（ggplot2 4.0.3 + svglite，
`tools/refs/stat_ref.R` 的 `stat-area-align` 段）：两边同一份数据、调色板与 limits；
`expand = c(0, 0)` 让面板就是整页。

两个 group 的 x 不齐（a: 1..4、b: 2..5）：`geom_area()` 的默认 stat 是
`stat_align`，它把组间 x 取并集、缺失处线性插值、两端补 0，再交给 position stack。
"""

from ggcore.plot import (
    aes,
    geom_area,
    ggplot,
    scale_fill_discrete,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [1, 2, 3, 4, 2, 3, 4, 5],
    "y": [1, 2, 1, 2, 2, 1, 2, 1],
    "g": ["a"] * 4 + ["b"] * 4,
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", fill="g"))
        + geom_area(position="stack")
        + scale_fill_discrete(values={"a": "#4C78A8", "b": "#F58518"})
        + scale_x_continuous(limits=(0.5, 5.5), expand=(0, 0))
        + scale_y_continuous(limits=(0, 4), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

"""point：离散 x 上的散点 + 分组着色（theme_void 整页）。

离散位置标度的 0.6 扩张由两边各自的 `scale_x_discrete()` 提供；颜色由
`scale_colour_discrete(values=)` 写死，R 侧用同值的 `scale_colour_manual()`。
参考图：`pixi run -e refs refs:cases`。
"""

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    scale_colour_discrete,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "cls": ["a", "b", "c", "a", "b", "c", "a", "b", "c"],
    "y": [1.2, 2.4, 1.8, 1.6, 2.8, 2.2, 1.0, 2.0, 2.6],
    "g": ["p", "p", "p", "q", "q", "q", "p", "q", "p"],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="cls", y="y", colour="g"))
        + geom_point(size=3.2, shape=19)
        + scale_colour_discrete(values={"p": "#F8766D", "q": "#00BA38"})
        + scale_y_continuous(limits=(0, 3), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

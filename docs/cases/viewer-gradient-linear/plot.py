"""SVG 渲染器：**线性渐变**填充（SIL-751）。

三根柱子共用一个横向 linearGradient（`x1=0, y1=0, x2=1, y2=0`，npc 口径）：
R 的 `geom_col()` 把三行数据画成**一个**多行 `rectGrob`，渐变按整层包围盒
解析，所以三根柱子上看到的是同一条被裁切的渐变——不是每根柱子各来一遍。
"""

from ggcore.plot import (
    aes,
    geom_col,
    ggplot,
    linear_gradient,
    scale_x_discrete,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {"cls": ["a", "b", "c"], "v": [0.35, 0.65, 0.90]}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="cls", y="v"))
        + geom_col(
            fill=linear_gradient(
                ["#132B43", "#56B1F7"], stops=[0.0, 1.0], x1=0.0, y1=0.0, x2=1.0, y2=0.0
            ),
            colour=None,
        )
        + scale_x_discrete()
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

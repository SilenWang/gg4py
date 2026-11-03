"""SVG 渲染器：**径向渐变**填充（SIL-751）。

同样三根柱子共用一个 radialGradient：圆心在被填充对象包围盒正中、半径是
短边的一半（grid 的缺省 npc 口径）。R 侧与这里都按整层 bbox 解析，所以
三根柱子共享同一个圆心与半径。
"""

from ggcore.plot import (
    aes,
    geom_col,
    ggplot,
    radial_gradient,
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
            fill=radial_gradient(["#FDE7E9", "#B31D28"], stops=[0.0, 1.0], cx=0.5, cy=0.5, r=0.5),
            colour=None,
        )
        + scale_x_discrete()
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

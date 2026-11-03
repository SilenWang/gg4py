"""SVG 渲染器：**4 档 + 中间档带 alpha** 的线性渐变（SIL-773）。

现有三条渐变 case 都是「2 档、无 alpha」，所以「中间档插入位置」与「单档 alpha
落在 stop-opacity 而不是整条渐变的 fill-opacity」这两点一直没有对拍守。这条把
两者一起钉住：三段柱子共用一条 4 档渐变，中段是半透明的。
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
                ["#132B43", "#56B1F780", "#F4A582", "#B31D28"],
                stops=[0.0, 0.3, 0.7, 1.0],
                x1=0.0,
                y1=0.0,
                x2=1.0,
                y2=0.0,
            ),
            colour=None,
        )
        + scale_x_discrete()
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

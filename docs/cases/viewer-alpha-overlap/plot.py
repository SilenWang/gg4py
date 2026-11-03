"""SVG 渲染器：两层半透明柱**重叠**时的合成顺序（M2-12）。

两个图层各自 55% 不透明、颜色不同，横向错开 0.15 形成重叠带：重叠处的颜色
是「先画的层在下、后画的层在上」按源覆盖合成的结果。渲染器把每层的
`fill-opacity` 写对它自己的元素（不是整页 `opacity`），合成才与 R 一致。
"""

from ggcore.plot import (
    aes,
    geom_col,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.25, 0.75],
    "x2": [0.40, 0.72],
    "y": [0.70, 0.50],
}

SIZE = [4, 3]


def build():
    table = to_column_table(DATA)
    p = (
        ggplot(table, aes(x="x", y="y"))
        + geom_col(width=0.40, fill="#E45756", alpha=0.55, colour=None)
        + geom_col(aes(x="x2", y="y"), width=0.40, fill="#4C78A8", alpha=0.55, colour=None)
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

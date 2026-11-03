"""violin：按 violinwidth 收窄的闭合多边形。

参考图由 `refs:geom` 的 `violin_basic` 段生成（R 侧走真实 `stat_ydensity`）：
这里把 stat 输出的 `violinwidth` 列当绘制输入，`setup_data()` 用
`x ± width/2` 给边界。
"""

from ggcore.plot import (
    aes,
    geom_violin,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

VIOLIN_Y = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]

DATA = {
    "x": [1.0] * 7 + [2.0] * 7,
    "y": VIOLIN_Y + [value + 0.05 for value in VIOLIN_Y],
    "violinwidth": [0.0, 0.35, 0.7, 1.0, 0.7, 0.35, 0.0, 0.0, 0.3, 0.65, 0.9, 0.65, 0.3, 0.0],
    "grp": ["a"] * 7 + ["b"] * 7,
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", violinwidth="violinwidth", group="grp"))
        + geom_violin(stat="identity", width=0.6, fill="#4C78A8", colour="black")
        + scale_x_continuous(limits=(0.3, 2.7), expand=(0.0, 0.0))
        + scale_y_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": [4, 3]}

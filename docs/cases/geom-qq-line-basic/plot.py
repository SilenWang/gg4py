"""qq_line：两端点折线（stat_qq_line 的输出形状）。

参考图由 `refs:geom` 的 `qq_line_stat` 段生成（R 侧走真实 `stat_qq_line`）：
两端点是样本分位数与理论分位数的连线。
"""

from ggcore.plot import (
    aes,
    geom_qq_line,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [-1.2815515655446008, 1.2815515655446008],
    "y": [0.18712004791983672, 0.79037995208016321],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_qq_line(stat="identity", colour="#3366FF")
        + scale_x_continuous(limits=(-1.409707, 1.409707), expand=(0.0, 0.0))
        + scale_y_continuous(limits=(0.1569571, 0.8205429), expand=(0.0, 0.0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": [4, 3]}

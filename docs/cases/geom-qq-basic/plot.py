"""qq：theoretical / sample 散点（stat_qq 的输出形状）。

参考图由 `refs:geom` 的 `qq_stat` 段生成（R 侧走真实 `stat_qq`）：
theoretical = qnorm(ppoints(n))，sample = 排序后的样本。
"""

from ggcore.plot import (
    aes,
    geom_qq,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "theoretical": [
        -1.2815515655446008,
        -0.64334540539291685,
        -0.20189347914185091,
        0.20189347914185077,
        0.64334540539291685,
        1.2815515655446008,
    ],
    "sample": [0.12, 0.3, 0.42, 0.55, 0.68, 0.88],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="theoretical", y="sample"))
        + geom_qq(stat="identity", size=3, colour="#4C78A8")
        + scale_x_continuous(limits=(-1.409707, 1.409707), expand=(0.0, 0.0))
        + scale_y_continuous(limits=(0.082, 0.918), expand=(0.0, 0.0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": [4, 3]}

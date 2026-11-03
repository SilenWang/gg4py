"""quantile：线性分位数回归的三条分位线（0.25 / 0.5 / 0.75）。

参考图由 `pixi run -e refs refs:stat-longtail` 生成（`stat-quantile-line` 段）。
`stat_quantile()` 的默认 geom 是 `quantile`（M2-7），这里显式用
`geom = "line"`；预测网格是 100 点的 `xseq`。
"""

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    stat_quantile,
    theme_void,
)
from ggio.frame import to_column_table

DATA = {
    "x": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    "y": [1, 2, 1.5, 3, 2.5, 4, 3.5, 5, 4.5, 6, 5.5, 7],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point(size=2, colour="#4C78A8")
        + stat_quantile(quantiles=(0.25, 0.5, 0.75), geom="line")
        + scale_x_continuous(limits=(0.5, 12.5), expand=(0, 0))
        + scale_y_continuous(limits=(0, 8), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

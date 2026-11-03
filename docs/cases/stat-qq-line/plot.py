"""qq + qq_line：同一份样本上的点与 `line.p` 直线。

参考图由 `pixi run -e refs refs:stat-longtail` 生成（`stat-qq-line` 段）。
`stat_qq_line()` 的默认 geom 是 `abline`（4.0.3），gg4py 侧用
`geom_line(stat = "qq_line")` 表达同一层——统计量相同，绘制走 `line`。
"""

from ggcore.plot import (
    aes,
    geom_line,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    stat_qq,
    theme_void,
)
from ggio.frame import to_column_table

DATA = {"v": [1.2, 2.4, 2.9, 3.1, 3.8, 4.5, 5.1, 5.2, 6.0, 7.7]}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(sample="v"))
        + stat_qq()
        + geom_line(stat="qq_line", colour="#4C78A8")
        + scale_x_continuous(limits=(-1.8, 1.8), expand=(0, 0))
        + scale_y_continuous(limits=(0.5, 8.5), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

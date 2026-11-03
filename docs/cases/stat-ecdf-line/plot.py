"""ecdf：经验累积分布的阶梯（`pad = TRUE` 时两端到 ±Inf）。

参考图由 `pixi run -e refs refs:stat-longtail` 生成（`stat-ecdf-line` 段）。
`stat_ecdf()` 的默认 geom 是 `step`（M2-7 的另一组），这里用 `geom = "line"`
表达同一份 stat 输出；阶梯的拐点由数据本身决定。
"""

from ggcore.plot import (
    aes,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    stat_ecdf,
    theme_void,
)
from ggio.frame import to_column_table

DATA = {"v": [1.2, 2.4, 2.9, 3.1, 3.8, 4.5, 5.1, 5.2, 6.0, 7.7]}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="v"))
        + stat_ecdf(geom="line")
        + scale_x_continuous(limits=(0, 9), expand=(0, 0))
        + scale_y_continuous(limits=(-0.05, 1.05), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

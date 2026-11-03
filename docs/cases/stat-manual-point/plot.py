"""manual：用户函数逐组改数据（这里只留前 4 行）。

参考图由 `pixi run -e refs refs:stat-longtail` 生成（`stat-manual-point` 段）。
`stat_manual()` 的 `fun` 收到一张「列名 → 数组」的表，返回映射或
`ColumnTable`；这里 `lambda data: {key: values[:4] for …}` 与 R 的
`function(d) d[1:4, ]` 是同一件事。
"""

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
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
        + geom_point(
            stat="manual",
            fun=lambda data: {key: values[:4] for key, values in data.items()},
        )
        + scale_x_continuous(limits=(0.5, 4.5), expand=(0, 0))
        + scale_y_continuous(limits=(0.5, 4.5), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

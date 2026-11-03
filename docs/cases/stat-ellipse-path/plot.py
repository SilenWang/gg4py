"""ellipse：正态数据椭圆（`type = "norm"` 的 `cov.wt` 口径）。

参考图由 `pixi run -e refs refs:stat-longtail` 生成（`stat-ellipse-path` 段）：
数据点 + 一条 51 段的椭圆路径，`theme_void` 整页。
"""

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    stat_ellipse,
    theme_void,
)
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3, 4, 5, 6, 7, 8], "y": [2, 1, 3, 2, 5, 4, 6, 7]}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point(size=2, colour="#4C78A8")
        + stat_ellipse(type="norm", geom="path")
        + scale_x_continuous(limits=(0, 9), expand=(0, 0))
        + scale_y_continuous(limits=(0, 8), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

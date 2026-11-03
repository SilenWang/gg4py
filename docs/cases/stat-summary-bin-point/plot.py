"""summary_bin：按箱汇总 `mean`（bins = 4）。

参考图由 `pixi run -e refs refs:stat-longtail` 生成（`stat-summary-bin-point` 段）：
灰点是原始观测，蓝色大点是每个箱的均值（`StatSummaryBin$compute_group()` 先
`bin_cut()` 再按箱汇总，x 落在箱中心）。
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
        + geom_point(size=2, colour="#B0B0B0")
        + geom_point(stat="summary_bin", fun="mean", bins=4, colour="#4C78A8", size=3)
        + scale_x_continuous(limits=(0.5, 12.5), expand=(0, 0))
        + scale_y_continuous(limits=(0, 8), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

"""summary：按 x 汇总 `mean / min / max`（点 + 原始点）。

参考图由 `pixi run -e refs refs:stat-longtail` 生成（`stat-summary-point` 段）。
`stat_summary()` 的默认 geom 是 `pointrange`（M2-7），这里两个点层：
灰点是原始观测，蓝点是 `fun = "mean"` 的汇总值（`fun.min` / `fun.max` 也进数据，
只是点画不出来，逐值对拍在 refs:stat-longtail 的 `summary_minmax`）。
"""

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    scale_y_continuous,
    theme_void,
)
from ggio.frame import to_column_table

DATA = {
    "g": ["a"] * 6 + ["b"] * 6,
    "y": [1, 2, 3, 4, 5, 6, 2, 3, 4, 5, 6, 7],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="g", y="y"))
        + geom_point(size=2, colour="#B0B0B0")
        + geom_point(stat="summary", fun="mean", fun_min="min", fun_max="max", colour="#4C78A8")
        + scale_y_continuous(limits=(0, 8), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

"""ydensity：每组 512 点密度网格（`scale = "area"`）落成点。

参考图由 `pixi run -e refs refs:stat-longtail` 生成（`stat-ydensity-area` 段）。
`stat_ydensity()` 的默认 geom 是 `violin`（M2-7 的另一组），这里用 `point`：
每组 512 点的密度网格 + `violinwidth` 都进同一份 stat 输出，点的竖向分布就是密度。
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
        + geom_point(
            stat="ydensity",
            position="identity",
            colour="#4C78A8",
            size=0.6,
            quantiles=None,
        )
        + scale_y_continuous(limits=(0.5, 7.5), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

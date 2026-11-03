"""density：核密度估计（`bw = "nrd0"`、`n = 512`）。

参考图由 `pixi run -e refs refs:stat-longtail` 生成（`stat-density-area` 段）。
`stat_density()` 的默认 geom 是 `area`、默认 position 是 `stack`；这里单组，
stack 与 identity 等价。曲线本体走的是 R 的「bin + FFT + 线性插值」口径
（见 docs/notes/stat.md §10），不是直接核求和。
"""

from ggcore.plot import (
    aes,
    geom_area,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggio.frame import to_column_table

DATA = {"v": [1.2, 2.4, 2.9, 3.1, 3.8, 4.5, 5.1, 5.2, 6.0, 7.7]}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="v"))
        + geom_area(stat="density", fill="#4C78A8", colour=None)
        + scale_x_continuous(limits=(0, 9), expand=(0, 0))
        + scale_y_continuous(limits=(0, 0.25), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

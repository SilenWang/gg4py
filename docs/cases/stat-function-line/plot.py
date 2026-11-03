"""function：任意函数在 x 范围上的采样曲线。

参考图由 `pixi run -e refs refs:stat-longtail` 生成（`stat-function-line` 段）。
`stat_function()` 的默认 geom 是 `function`（M2-7），这里用
`geom_line(stat = "function", …)`：`fun` / `xlim` / `n` 都走层参数，stat 从
`layer.params` 里取（与 R 的 `elastic` 参数路由同一口径）。
"""

import numpy as np

from ggcore.plot import (
    geom_line,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)

SIZE = [4, 3]


def build():
    p = (
        ggplot()
        + geom_line(
            stat="function",
            fun=lambda x: np.sin(x) + 1.0,
            xlim=(0, 6),
            n=25,
            colour="#4C78A8",
        )
        + scale_x_continuous(limits=(0, 6), expand=(0, 0))
        + scale_y_continuous(limits=(0, 2.2), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

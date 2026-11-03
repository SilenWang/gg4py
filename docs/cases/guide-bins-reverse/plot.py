"""guide：`guide_bins(reverse=TRUE, show.limits=TRUE)`。

R 的 `GuideBins$extract_params()` 在 reverse 时把键行倒序、美学列左旋一格、
`.value <- 1 - .value`；标签 / 键格颜色 / 刻度必须一起翻。
"""

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_bins,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggio.frame import to_column_table

DATA = {
    "x": [0.10, 0.20, 0.35, 0.50, 0.65, 0.80, 0.90, 0.25, 0.75],
    "y": [0.20, 0.50, 0.35, 0.70, 0.45, 0.80, 0.60, 0.85, 0.15],
    "v": [0.00, 0.12, 0.25, 0.38, 0.50, 0.62, 0.75, 0.88, 1.00],
}
SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="v"))
        + geom_point(shape=19, size=3.2)
        + guide_bins("colour", reverse=True, show_limits=True)
        + theme_void()
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
    )
    return {"plot": p, "size": SIZE}

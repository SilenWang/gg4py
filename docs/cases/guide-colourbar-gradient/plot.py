"""guide：`guide_colourbar(display="gradient")`。

IR 的 `fill` 没有渐变类型（docs/notes/ir.md §12），所以仍是 `nbin` 条矩形；
`display="gradient"` 只改缺省 `nbin`（15）与刻度位置（`(0, 1)` 而非箱心）。
"""

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_colourbar,
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
        + guide_colourbar("colour", display="gradient")
        + theme_void()
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
    )
    return {"plot": p, "size": SIZE}

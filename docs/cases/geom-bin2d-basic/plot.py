"""bin2d：stat_bin_2d 形状的矩形（x / y / width / height / count）。

参考图由 `refs:geom` 的 `bin2d_basic` 段生成：3×2 个 bin，`fill` 映射到
`count`，`scale_fill_gradient(low = "#EBEDF0", high = "#2C7FB8")`。
`GeomBin2d` 继承 `GeomTile`：`setup_data()` 用 x ± width/2 得到四角。
"""

from ggcore.plot import (
    aes,
    geom_bin2d,
    ggplot,
    scale_fill_gradient,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.166667, 0.5, 0.833333, 0.166667, 0.5, 0.833333],
    "y": [0.25, 0.25, 0.25, 0.75, 0.75, 0.75],
    "width": [0.333333, 0.333333, 0.333333, 0.333333, 0.333333, 0.333333],
    "height": [0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
    "count": [1.0, 4.0, 2.0, 3.0, 5.0, 2.0],
}


def build():
    p = (
        ggplot(
            to_column_table(DATA), aes(x="x", y="y", fill="count", width="width", height="height")
        )
        + geom_bin2d(stat="identity")
        + scale_fill_gradient(low="#EBEDF0", high="#2C7FB8")
        + scale_x_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + scale_y_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": [4, 3]}

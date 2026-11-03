"""hex：六边形 bin（stat_bin_hex 形状：x / y / width / height / count）。

参考图由 `refs:geom` 的 `hex_basic` 段生成：三个 bin，`fill` 映射到 `count`，
六边形顶点照 `hexbin::hexcoords()`（dx = width/2、dy = height/√3/2）。
"""

from ggcore.plot import (
    aes,
    geom_hex,
    ggplot,
    scale_fill_gradient,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.25, 0.55, 0.8],
    "y": [0.35, 0.6, 0.35],
    "width": [0.3, 0.3, 0.3],
    "height": [0.26, 0.26, 0.26],
    "count": [2.0, 5.0, 3.0],
}


def build():
    p = (
        ggplot(
            to_column_table(DATA),
            aes(x="x", y="y", fill="count", width="width", height="height"),
        )
        + geom_hex(stat="identity")
        + scale_fill_gradient(low="#EBEDF0", high="#2C7FB8")
        + scale_x_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + scale_y_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": [4, 3]}

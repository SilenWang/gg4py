"""上游快照复刻：single hex bin with width and height of 0.1。

源：`geom-hex/single-hex-bin-with-width-and-height-of-0-1.svg`。`test-geom-hex.R` 的 "bin size are
picked up from stat"（vdiffr 名 `single hex bin with width and height of 0.1`）。

R：

    ggplot(data.frame(x = 0, y = 0)) +
      geom_hex(aes(x = x, y = y), binwidth = c(0.1, 0.1)) +
      coord_cartesian(xlim = c(-1, 1), ylim = c(-1, 1))

单个点的计数 1，六边形宽高都是 0.1 数据单位。
"""

from ggcore.plot import aes, coord_cartesian, geom_hex, ggplot, labs
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DAT = {"x": [0.0], "y": [0.0]}


def build():
    p = (
        ggplot(to_column_table(DAT), aes(x="x", y="y"))
        + geom_hex(binwidth=(0.1, 0.1))
        + coord_cartesian(xlim=(-1, 1), ylim=(-1, 1))
        + theme_test()
        + labs(title="single hex bin with width and height of 0.1")
    )
    return {"plot": p, "size": [10, 8]}

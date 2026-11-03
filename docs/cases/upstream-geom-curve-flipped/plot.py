"""上游快照复刻：flipped geom_curve（geom-curve/flipped-geom-curve.svg）。

源：`test-geom-curve.R` 的 "geom_curve flipping works"（vdiffr 名 `flipped geom_curve`）。

R：

    df <- data.frame(x = c(1, 2), xend = c(2, 3), y = 1, yend = c(2, 1.5))
    p <- ggplot(df, aes(x, y, xend = xend, yend = yend)) +
      geom_curve(arrow = arrow())
    p <- p + scale_y_reverse()
"""

from ggcore.plot import aes, arrow, geom_curve, ggplot, labs, scale_y_reverse
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DAT = {
    "x": [1.0, 2.0],
    "xend": [2.0, 3.0],
    "y": [1.0, 1.0],
    "yend": [2.0, 1.5],
}


def build():
    p = (
        ggplot(
            to_column_table(DAT),
            aes(x="x", y="y", xend="xend", yend="yend"),
        )
        + geom_curve(arrow=arrow())
        + scale_y_reverse()
        + theme_test()
        + labs(title="flipped geom_curve")
    )
    return {"plot": p, "size": [10, 8]}

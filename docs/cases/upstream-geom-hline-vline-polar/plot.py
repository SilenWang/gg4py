"""上游快照复刻：polar lines intersect mid-bars。

源：`geom-hline-vline-abline/polar-lines-intersect-mid-bars.svg`。`test-geom-hline-vline-abline.R`
的 "check h/v/abline transformed on basic
projections"（vdiffr 名 `polar lines intersect mid-bars`）。

R：

    dat <- data_frame(x = LETTERS[1:5], y = 1:5)
    plot <- ggplot(dat, aes(x, y)) +
      geom_col(width = 1) +
      geom_point() +
      geom_vline(xintercept = 3, colour = "red") +
      geom_hline(yintercept = 3, colour = "blue") +
      geom_abline(intercept = 0, slope = 1, colour = "purple") +
      labs(x = NULL, y = NULL)
    plot + coord_polar()

离散 x（5 个水平）× 连续 y；三条参考线分别在极坐标的圆周 / 半径方向。
"""

from ggcore.plot import (
    aes,
    coord_polar,
    geom_abline,
    geom_col,
    geom_hline,
    geom_point,
    geom_vline,
    ggplot,
    labs,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DAT = {"x": list("ABCDE"), "y": [1.0, 2.0, 3.0, 4.0, 5.0]}


def build():
    p = (
        ggplot(to_column_table(DAT), aes(x="x", y="y"))
        + geom_col(width=1)
        + geom_point()
        + geom_vline(xintercept=3, colour="red")
        + geom_hline(yintercept=3, colour="blue")
        + geom_abline(intercept=0, slope=1, colour="purple")
        + labs(x=None, y=None)
        + coord_polar()
        + theme_test()
        + labs(title="polar lines intersect mid-bars")
    )
    return {"plot": p, "size": [10, 8]}

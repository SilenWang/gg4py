"""上游快照复刻：line matches points。

源：annotate/line-matches-points.svg（vdiffr 名 "line matches points"）。

R：

    df <- data_frame(x = c(1, 10), y = c(10, 1))
    ggplot(df, aes(x, y)) +
      geom_point() +
      annotate("segment", x = 1, y = 10, xend = 10, yend = 1, colour = "red") +
      scale_y_reverse(NULL, breaks = NULL) +
      scale_x_continuous(NULL, breaks = NULL)

判据是 `annotate()` 的位置美学与数据点走**同一套标度**：`scale_y_reverse()`
之后线段的两个端点仍精确落在两个点上（不是镜像到窗外）。
"""

from ggcore.plot import (
    aes,
    annotate,
    geom_point,
    ggplot,
    labs,
    scale_x_continuous,
    scale_y_reverse,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1.0, 10.0], "y": [10.0, 1.0]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + annotate("segment", x=1, y=10, xend=10, yend=1, colour="red")
        + scale_y_reverse(name=None, breaks=None)
        + scale_x_continuous(name=None, breaks=None)
        + labs(title="line matches points")
        + theme_test()
    )
    return {"plot": p, "size": [10, 8]}

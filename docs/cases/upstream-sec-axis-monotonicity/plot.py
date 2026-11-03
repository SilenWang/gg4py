"""上游快照复刻：sec axis monotonicity test。

源：sec-axis/sec-axis-monotonicity-test.svg（vdiffr 名 "sec axis monotonicity test"）。

R：

    data <- data_frame(x = seq(0, 1, length.out = 100), y = seq(0, 4, length.out = 100))
    ggplot(data, aes(x, y)) +
      geom_line() +
      scale_y_continuous(transform = "sqrt", sec.axis = dup_axis()) +
      theme_linedraw()

主轴是 sqrt 变换、次轴 `dup_axis()`：两条轴的断点位置相同，标签都是数据空间的值
（`dup_axis()` 的恒等变换直接沿用主轴断点）。
"""

from ggcore.plot import aes, dup_axis, geom_line, ggplot, labs, scale_y_continuous
from ggcore.theme import theme_linedraw
from ggio.frame import to_column_table

DATA = {
    "x": [index / 99.0 for index in range(100)],
    "y": [4.0 * index / 99.0 for index in range(100)],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_line()
        + scale_y_continuous(transform="sqrt", **{"sec.axis": dup_axis()})
        + theme_linedraw()
        + labs(title="sec axis monotonicity test")
    )
    return {"plot": p, "size": [10, 8]}

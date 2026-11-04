"""上游快照复刻：align two areas with pos/neg y（stat-align/align-two-areas-with-pos-neg-y.svg）。

源：`test-stat-align.R` 的 "alignment with negative and positive values works"（vdiffr 名 `align two
areas with pos/neg y`）。

R：

    df <- data_frame0(
      g = rep(c("a", "b"), c(4L, 2L)),
      x = c(1.0, 2.0, 3.0, 8.0, 2.0, 6.0),
      y = c(1.0, 4.0, -4.0, 0.0, 4.0, -4.0)
    )
    ggplot(df, aes(x, y, fill = g)) + geom_area(color = "black")
"""

from ggcore.plot import aes, geom_area, ggplot, labs
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DAT = {
    "g": ["a", "a", "a", "a", "b", "b"],
    "x": [1.0, 2.0, 3.0, 8.0, 2.0, 6.0],
    "y": [1.0, 4.0, -4.0, 0.0, 4.0, -4.0],
}


def build():
    p = (
        ggplot(to_column_table(DAT), aes(x="x", y="y", fill="g"))
        + geom_area(colour="black")
        + theme_test()
        + labs(title="align two areas with pos/neg y")
    )
    return {"plot": p, "size": [10, 8]}

"""上游快照复刻：align two areas with cliff（stat-align/align-two-areas-with-cliff.svg）。

源：`test-stat-align.R` 的 "alignment with cliffs works"（vdiffr 名 `align two areas with cliff`）。

R：

    df <- data_frame0(
      g = rep(c("a", "b"), 3:4),
      x = c(1.0, 3.0, 5.0, 2.0, 4.0, 4.0, 6.0),
      y = c(2.0, 5.0, 1.0, 3.0, 3.0, 6.0, 7.0)
    )
    ggplot(df, aes(x, y, fill = g)) + geom_area(color = "black")
"""

from ggcore.plot import aes, geom_area, ggplot, labs
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DAT = {
    "g": ["a", "a", "a", "b", "b", "b", "b"],
    "x": [1.0, 3.0, 5.0, 2.0, 4.0, 4.0, 6.0],
    "y": [2.0, 5.0, 1.0, 3.0, 3.0, 6.0, 7.0],
}


def build():
    p = (
        ggplot(to_column_table(DAT), aes(x="x", y="y", fill="g"))
        + geom_area(colour="black")
        + theme_test()
        + labs(title="align two areas with cliff")
    )
    return {"plot": p, "size": [10, 8]}

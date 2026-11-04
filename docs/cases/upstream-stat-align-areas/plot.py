"""上游快照复刻：align two areas（stat-align/align-two-areas.svg）。

源：`test-stat-align.R` 的 "standard alignment works"（vdiffr 名 `align two areas`）。

R：

    df <- data_frame0(
      g = rep(c("a", "b"), each = 3L),
      x = c(1.0, 3.0, 5.0, 2.0, 4.0, 6.0),
      y = c(2.0, 5.0, 1.0, 3.0, 6.0, 7.0)
    )
    ggplot(df, aes(x, y, fill = g)) + geom_area(color = "black")
"""

from ggcore.plot import aes, geom_area, ggplot, labs
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DAT = {
    "g": ["a", "a", "a", "b", "b", "b"],
    "x": [1.0, 3.0, 5.0, 2.0, 4.0, 6.0],
    "y": [2.0, 5.0, 1.0, 3.0, 6.0, 7.0],
}


def build():
    p = (
        ggplot(to_column_table(DAT), aes(x="x", y="y", fill="g"))
        + geom_area(colour="black")
        + theme_test()
        + labs(title="align two areas")
    )
    return {"plot": p, "size": [10, 8]}

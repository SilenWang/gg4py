"""上游快照复刻：Area stacking（position-stack/area-stacking.svg）。

源：`test-position-stack.R` 的 "Stacking produces the expected output"
（vdiffr 名 `Area stacking`）。

R：

    data <- data_frame(x = rep(1:4, each = 2),
                       category = rep(c("A","B"), 4),
                       value = c(0, 0, 2, 1, 3, 6, -4, 3))
    ggplot(data, aes(x = x, y = value, fill = category)) +
      geom_area(stat = "identity")
"""

from ggcore.plot import aes, geom_area, ggplot, labs
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DAT = {
    "x": [1.0, 1.0, 2.0, 2.0, 3.0, 3.0, 4.0, 4.0],
    "category": ["A", "B"] * 4,
    "value": [0.0, 0.0, 2.0, 1.0, 3.0, 6.0, -4.0, 3.0],
}


def build():
    p = (
        ggplot(
            to_column_table(DAT),
            aes(x="x", y="value", fill="category"),
        )
        + geom_area(stat="identity")
        + theme_test()
        + labs(title="Area stacking")
    )
    return {"plot": p, "size": [10, 8]}

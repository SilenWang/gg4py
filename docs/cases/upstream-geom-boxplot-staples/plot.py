"""上游快照复刻：staples（geom-boxplot/staples.svg）。

源：`test-geom-boxplot.R` 的 "boxplot draws correctly"（vdiffr 名 `staples`）。

R：

    ggplot(mtcars, aes(x = factor(cyl), y = drat, colour = factor(cyl))) +
      geom_boxplot(staplewidth = 0.5)

`mtcars` 的 `cyl` / `drat` 两列按 R 4.5.3 的 `datasets::mtcars` 逐值内联。
"""

from ggcore.plot import aes, geom_boxplot, ggplot, labs
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DAT = {
    "cyl": [
        "6",
        "6",
        "4",
        "6",
        "8",
        "6",
        "8",
        "4",
        "4",
        "6",
        "6",
        "8",
        "8",
        "8",
        "8",
        "8",
        "8",
        "4",
        "4",
        "4",
        "4",
        "8",
        "8",
        "8",
        "8",
        "4",
        "4",
        "4",
        "8",
        "6",
        "8",
        "4",
    ],
    "drat": [
        3.9,
        3.9,
        3.85,
        3.08,
        3.15,
        2.76,
        3.21,
        3.69,
        3.92,
        3.92,
        3.92,
        3.07,
        3.07,
        3.07,
        2.93,
        3.0,
        3.23,
        4.08,
        4.93,
        4.22,
        3.7,
        2.76,
        3.15,
        3.73,
        3.08,
        4.08,
        4.43,
        3.77,
        4.22,
        3.62,
        3.54,
        4.11,
    ],
}


def build():
    p = (
        ggplot(to_column_table(DAT), aes(x="cyl", y="drat", colour="cyl"))
        + geom_boxplot(staplewidth=0.5)
        + theme_test()
        + labs(x="factor(cyl)", colour="factor(cyl)", title="staples")
    )
    return {"plot": p, "size": [10, 8]}

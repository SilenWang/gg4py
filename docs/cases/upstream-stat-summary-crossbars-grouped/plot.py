"""上游快照复刻：summary with crossbars, manual grouping。

源：`stat-sum/summary-with-crossbars-manual-grouping.svg`。`test-stat-sum.R` 的 "summaries are drawn
correctly"（vdiffr 名 `summary with crossbars, manual grouping`）。

R：

    ggplot(mtcars, aes(x = cyl, y = mpg, group = cyl)) +
      geom_point() +
      stat_summary(fun_data="mean_se", colour="red", geom="crossbar", width=0.2)

`mtcars` 的 cyl / mpg / vs 三列按 R 4.5.3 的 `datasets::mtcars` 逐值内联。
"""

from ggcore.plot import aes, geom_point, ggplot, labs, stat_summary
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DAT = {
    "cyl": [
        6.0,
        6.0,
        4.0,
        6.0,
        8.0,
        6.0,
        8.0,
        4.0,
        4.0,
        6.0,
        6.0,
        8.0,
        8.0,
        8.0,
        8.0,
        8.0,
        8.0,
        4.0,
        4.0,
        4.0,
        4.0,
        8.0,
        8.0,
        8.0,
        8.0,
        4.0,
        4.0,
        4.0,
        8.0,
        6.0,
        8.0,
        4.0,
    ],
    "mpg": [
        21.0,
        21.0,
        22.8,
        21.4,
        18.7,
        18.1,
        14.3,
        24.4,
        22.8,
        19.2,
        17.8,
        16.4,
        17.3,
        15.2,
        10.4,
        10.4,
        14.7,
        32.4,
        30.4,
        33.9,
        21.5,
        15.5,
        15.2,
        13.3,
        19.2,
        27.3,
        26.0,
        30.4,
        15.8,
        19.7,
        15.0,
        21.4,
    ],
    "vs": [
        0.0,
        0.0,
        1.0,
        1.0,
        0.0,
        1.0,
        0.0,
        1.0,
        1.0,
        1.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        1.0,
        1.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        1.0,
    ],
}


def build():
    p = (
        ggplot(to_column_table(DAT), aes(x="cyl", y="mpg", group="cyl"))
        + geom_point()
        + stat_summary(fun_data="mean_se", colour="red", geom="crossbar", width=0.2)
        + theme_test()
        + labs(title="summary with crossbars, manual grouping")
    )
    return {"plot": p, "size": [10, 8]}

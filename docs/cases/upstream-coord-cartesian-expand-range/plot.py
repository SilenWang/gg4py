"""上游快照复刻：expand range。

源：coord-cartesian/expand-range.svg（vdiffr 名 "expand range"）。

R：

    ggplot(mtcars, aes(wt, mpg)) + geom_point() +
      coord_cartesian(xlim = c(0, 10), ylim = c(0, 50))

`mtcars` 夹具按 R 4.5.3 的 `datasets::mtcars` 逐值导出（32 行），不是仿制集。
"""

from ggcore.plot import aes, coord_cartesian, geom_point, ggplot, labs
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {
    "wt": [
        2.62,
        2.875,
        2.32,
        3.215,
        3.44,
        3.46,
        3.57,
        3.19,
        3.15,
        3.44,
        3.44,
        4.07,
        3.73,
        3.78,
        5.25,
        5.424,
        5.345,
        2.2,
        1.615,
        1.835,
        2.465,
        3.52,
        3.435,
        3.84,
        3.845,
        1.935,
        2.14,
        1.513,
        3.17,
        2.77,
        3.57,
        2.78,
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
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="wt", y="mpg"))
        + geom_point()
        + coord_cartesian(xlim=(0.0, 10.0), ylim=(0.0, 50.0))
        + theme_test()
        + labs(title="expand range")
    )
    return {"plot": p, "size": [10, 8]}

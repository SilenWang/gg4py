"""上游快照复刻：switched facet strips。

源：facet-strips/switched-facet-strips.svg
（vdiffr 名 "switched facet strips"）。

R：

    p <- ggplot(mtcars, aes(disp, drat)) + geom_point()
    p + facet_grid(am ~ cyl, switch = "both")

`mtcars` 夹具按 R 4.5.3 的 `datasets::mtcars` 逐值内联
（`tools/upstream/fixtures/mtcars.json`）。
"""

from ggcore.plot import aes, facet_grid, geom_point, ggplot, labs
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {
    "disp": [
        160.0,
        160.0,
        108.0,
        258.0,
        360.0,
        225.0,
        360.0,
        146.7,
        140.8,
        167.6,
        167.6,
        275.8,
        275.8,
        275.8,
        472.0,
        460.0,
        440.0,
        78.7,
        75.7,
        71.1,
        120.1,
        318.0,
        304.0,
        350.0,
        400.0,
        79.0,
        120.3,
        95.1,
        351.0,
        145.0,
        301.0,
        121.0,
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
    "am": [
        1,
        1,
        1,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        1,
        1,
        1,
        0,
        0,
        0,
        0,
        0,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
    ],
    "cyl": [
        6,
        6,
        4,
        6,
        8,
        6,
        8,
        4,
        4,
        6,
        6,
        8,
        8,
        8,
        8,
        8,
        8,
        4,
        4,
        4,
        4,
        8,
        8,
        8,
        8,
        4,
        4,
        4,
        8,
        6,
        8,
        4,
    ],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="disp", y="drat"))
        + geom_point()
        + facet_grid(rows="am", cols="cyl", switch="both")
        + theme_test()
        + labs(title="switched facet strips")
    )
    return {"plot": p, "size": [10, 8]}

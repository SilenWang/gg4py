"""上游快照复刻：facet_wrap with omitted inner axis labels。

源：facet-/facet-wrap-with-omitted-inner-axis-labels.svg
（vdiffr 名 "facet_wrap with omitted inner axis labels"）。

R：

    base <- ggplot(mtcars, aes(mpg, disp)) + geom_point() +
      guides(x = "axis", y = "axis", x.sec = "axis", y.sec = "axis")
    base + facet_wrap(vars(cyl, vs), axes = "all", axis.labels = "margins")

`mtcars` 夹具按 R 4.5.3 的 `datasets::mtcars` 逐值内联
（`tools/upstream/fixtures/mtcars.json`）。
"""

from ggcore.plot import aes, facet_wrap, geom_point, ggplot, guides, labs
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {
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
    "vs": [
        0,
        0,
        1,
        1,
        0,
        1,
        0,
        1,
        1,
        1,
        1,
        0,
        0,
        0,
        0,
        0,
        0,
        1,
        1,
        1,
        1,
        0,
        0,
        0,
        0,
        1,
        0,
        1,
        0,
        0,
        0,
        1,
    ],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="mpg", y="disp"))
        + geom_point()
        + guides(**{"x": "axis", "y": "axis", "x.sec": "axis", "y.sec": "axis"})
        + facet_wrap(["cyl", "vs"], axes="all", axis_labels="margins")
        + theme_test()
        + labs(title="facet_wrap with omitted inner axis labels")
    )
    return {"plot": p, "size": [10, 8]}

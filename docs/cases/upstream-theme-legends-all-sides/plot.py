"""上游快照复刻：legends at all sides with justification。

源：theme/legends-at-all-sides-with-justification.svg
（vdiffr 名 "legends at all sides with justification"）。

R：

    ggplot(mtcars) +
      aes(disp, mpg, colour = hp, fill = factor(gear), shape = factor(cyl),
          size = drat, alpha = wt) +
      geom_point() +
      guides(
        shape = guide_legend(position = "top"),
        colour = guide_colourbar(position = "bottom"),
        size = guide_legend(position = "left"),
        alpha = guide_legend(position = "right"),
        fill = guide_legend(position = "inside", override.aes = list(shape = 21))
      ) +
      theme_test() +
      theme(
        legend.justification.top = "left",
        legend.justification.bottom = c(1, 0),
        legend.justification.left = c(0, 1),
        legend.justification.right = "bottom",
        legend.justification.inside = c(0.75, 0.75),
        legend.location = "plot"
      )

`mtcars` 夹具按 R 4.5.3 的 `datasets::mtcars` 逐值内联
（`tools/upstream/fixtures/mtcars.json`）。
"""

import sys
from pathlib import Path

from ggcore.plot import aes, geom_point, ggplot, guide_colourbar, guide_legend, guides, labs
from ggcore.theme import theme, theme_test
from ggio.frame import to_column_table

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _fixtures import factor_column, replace_column

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
    "hp": [
        110,
        110,
        93,
        110,
        175,
        105,
        245,
        62,
        95,
        123,
        123,
        180,
        180,
        180,
        205,
        215,
        230,
        66,
        52,
        65,
        97,
        150,
        150,
        245,
        175,
        66,
        91,
        113,
        264,
        175,
        335,
        109,
    ],
    "gear": [
        4,
        4,
        4,
        3,
        3,
        3,
        3,
        4,
        4,
        4,
        4,
        3,
        3,
        3,
        3,
        3,
        3,
        4,
        4,
        4,
        3,
        3,
        3,
        3,
        3,
        4,
        5,
        5,
        5,
        5,
        5,
        4,
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
    "wt": [
        2.62,
        2.88,
        2.32,
        3.21,
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
        5.42,
        5.34,
        2.2,
        1.61,
        1.83,
        2.46,
        3.52,
        3.44,
        3.84,
        3.85,
        1.94,
        2.14,
        1.51,
        3.17,
        2.77,
        3.57,
        2.78,
    ],
}


def build():
    table = to_column_table(DATA)
    table = replace_column(table, "gear", factor_column(DATA["gear"], sorted(set(DATA["gear"]))))
    table = replace_column(table, "cyl", factor_column(DATA["cyl"], sorted(set(DATA["cyl"]))))
    p = (
        ggplot(
            table,
            aes(
                x="disp",
                y="mpg",
                colour="hp",
                fill="gear",
                shape="cyl",
                size="drat",
                alpha="wt",
            ),
        )
        + geom_point()
        + guides(
            **{
                "shape": guide_legend(position="top"),
                "colour": guide_colourbar(position="bottom"),
                "size": guide_legend(position="left"),
                "alpha": guide_legend(position="right"),
                "fill": guide_legend(position="inside"),
            }
        )
        + theme_test()
        + theme(
            **{
                "legend.justification.top": "left",
                "legend.justification.bottom": (1, 0),
                "legend.justification.left": (0, 1),
                "legend.justification.right": "bottom",
                "legend.justification.inside": (0.75, 0.75),
                "legend.location": "plot",
            }
        )
        # R 的图例标题取自映射表达式 `factor(gear)` / `factor(cyl)`；显式给出同值。
        + labs(
            title="legends at all sides with justification",
            fill="factor(gear)",
            shape="factor(cyl)",
        )
    )
    return {"plot": p, "size": [10, 8]}

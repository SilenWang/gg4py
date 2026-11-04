"""上游快照复刻：basic polygon plot（geom-polygon/basic-polygon-plot.svg）。

源：`test-geom-polygon.R` 的 "geom_polygon draws correctly"
（vdiffr 名 `basic polygon plot`）。

R：

    tbl <- data_frame(
      x = c(0, 10, 10, 0, 20, 30, 30, 20, 22, 28, 28, 22),
      y = c(0, 0, 10, 10, 20, 20, 30, 30, 22, 22, 28, 28),
      group = c(rep(1, 4), rep(2, 8)),
      subgroup = c(rep(1, 8), rep(2, 4))
    )
    ggplot(tbl, aes(x, y, group = group, subgroup = subgroup)) + geom_polygon()
"""

from ggcore.plot import aes, geom_polygon, ggplot, labs
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DAT = {
    "x": [0.0, 10.0, 10.0, 0.0, 20.0, 30.0, 30.0, 20.0, 22.0, 28.0, 28.0, 22.0],
    "y": [0.0, 0.0, 10.0, 10.0, 20.0, 20.0, 30.0, 30.0, 22.0, 22.0, 28.0, 28.0],
    "group": ["1"] * 4 + ["2"] * 8,
    "subgroup": ["1"] * 8 + ["2"] * 4,
}


def build():
    p = (
        ggplot(
            to_column_table(DAT),
            aes(x="x", y="y", group="group", subgroup="subgroup"),
        )
        + geom_polygon()
        + theme_test()
        + labs(title="basic polygon plot")
    )
    return {"plot": p, "size": [10, 8]}

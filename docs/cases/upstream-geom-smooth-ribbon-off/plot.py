"""上游快照复刻：ribbon turned off in geom_smooth。

源：`geom-smooth/ribbon-turned-off-in-geom-smooth.svg`。`test-geom-smooth.R` 的 "geom_smooth()
works with alternative stats"
（vdiffr 名 `ribbon turned off in geom_smooth`）。

R：

    df <- data_frame(x = c(1, 1, 2, 2, 1, 1, 2, 2),
                     y = c(1, 2, 2, 3, 2, 3, 1, 2),
                     fill = c(rep("A", 4), rep("B", 4)))
    ggplot(df, aes(x, y, color = fill, fill = fill)) +
      geom_smooth(stat = "summary", se=False, fun.data = mean_se)

`stat = "summary"` + `fun.data = mean_se`：每个 x 的均值与 ±1 SE 带；
`se = FALSE` 关掉带子，只留折线。
"""

from ggcore.plot import aes, geom_smooth, ggplot, labs
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DAT = {
    "x": [1.0, 1.0, 2.0, 2.0, 1.0, 1.0, 2.0, 2.0],
    "y": [1.0, 2.0, 2.0, 3.0, 2.0, 3.0, 1.0, 2.0],
    "fill": ["A", "A", "A", "A", "B", "B", "B", "B"],
}


def build():
    p = (
        ggplot(
            to_column_table(DAT),
            aes(x="x", y="y", colour="fill", fill="fill"),
        )
        + geom_smooth(stat="summary", se=False, fun_data="mean_se")
        + theme_test()
        + labs(title="ribbon turned off in geom_smooth")
    )
    return {"plot": p, "size": [10, 8]}

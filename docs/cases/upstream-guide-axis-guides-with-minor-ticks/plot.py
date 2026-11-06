"""上游快照复刻：guides with minor ticks。

源：guide-axis/guides-with-minor-ticks.svg
（vdiffr 名 "guides with minor ticks"）。

R：

    ggplot(mtcars, aes(wt, disp)) +
      geom_point() +
      theme(
        axis.ticks.length = unit(1, "cm"),
        axis.ticks.x.bottom = element_line(linetype = 2),
        axis.ticks.length.x.top = unit(-0.5, "cm"),
        axis.minor.ticks.x.bottom = element_line(colour = "red"),
        axis.minor.ticks.length.y.left = unit(-0.5, "cm"),
        axis.minor.ticks.length.x.top = unit(-0.5, "cm"),
        axis.minor.ticks.length.x.bottom = unit(0.75, "cm"),
        axis.minor.ticks.length.y.right = unit(5, "cm")
      ) +
      scale_x_continuous(labels = label_math()) +
      guides(
        x = guide_axis(minor.ticks = TRUE),
        y = guide_axis(minor.ticks = TRUE),
        x.sec = guide_axis(minor.ticks = TRUE),
        y.sec = guide_axis(minor.ticks = FALSE)
      )

x 轴标签是 `label_math()`（缺省 `10^.x`）：`10` 用 8.8pt、指数 6.16pt 两段落字。
`wt` / `disp` 按 R 4.5.3 的 `datasets::mtcars` 逐值内联；`wt` 特意保留 R 的 3 位
小数（`tools/upstream/fixtures/mtcars.json` 里是 2 位四舍五入的，面板 x 映射会
偏 0.5pt，竖网格线整排错位）。
"""

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_axis,
    guides,
    label_math,
    labs,
    scale_x_continuous,
)
from ggcore.theme import element_line, theme
from ggcore.units import unit
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
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="wt", y="disp"))
        + geom_point()
        + scale_x_continuous(labels=label_math())
        + theme(
            **{
                "axis.ticks.length": unit(1.0, "cm"),
                "axis.ticks.x.bottom": element_line(linetype=2),
                "axis.ticks.length.x.top": unit(-0.5, "cm"),
                "axis.minor.ticks.x.bottom": element_line(colour="red"),
                "axis.minor.ticks.length.y.left": unit(-0.5, "cm"),
                "axis.minor.ticks.length.x.top": unit(-0.5, "cm"),
                "axis.minor.ticks.length.x.bottom": unit(0.75, "cm"),
                "axis.minor.ticks.length.y.right": unit(5.0, "cm"),
            }
        )
        + guides(
            x=guide_axis(minor_ticks=True),
            y=guide_axis(minor_ticks=True),
            **{"x.sec": guide_axis(minor_ticks=True), "y.sec": guide_axis(minor_ticks=False)},
        )
        + labs(title="guides with minor ticks")
    )
    return {"plot": p, "size": [10, 8]}

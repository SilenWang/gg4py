"""上游快照复刻：secondary axis ticks and labels。

源：coord-polar/secondary-axis-ticks-and-labels.svg
（vdiffr 名 "secondary axis ticks and labels"）。

R：

    dat <- data_frame(x = LETTERS[1:3], y = 1:3)
    ggplot(dat, aes(x, y, group = factor(y))) +
      geom_blank() +
      scale_y_continuous(sec.axis = sec_axis(~ . * 0.1, name = "sec y")) +
      coord_polar() +
      theme_test() +
      theme(axis.text.x = element_blank())

极坐标下 r 轴的次轴画在右侧（上游 `CoordPolar$render_axis_v()` 的
`r_rescale(r.sec.major, r.sec.range) + 0.5`）；theta 标签被 `axis.text.x` 去掉。
"""

from ggcore.plot import (
    aes,
    coord_polar,
    geom_blank,
    ggplot,
    labs,
    scale_y_continuous,
    sec_axis,
)
from ggcore.theme import element_blank, theme, theme_test
from ggio.frame import to_column_table

DATA = {
    "x": ["A", "B", "C"],
    "y": [1.0, 2.0, 3.0],
    "g": ["1", "2", "3"],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", group="g"))
        + geom_blank()
        + scale_y_continuous(**{"sec.axis": sec_axis(lambda v: v * 0.1, name="sec y")})
        + coord_polar()
        + theme_test()
        + theme(**{"axis.text.x": element_blank()})
        + labs(title="secondary axis ticks and labels")
    )
    return {"plot": p, "size": [10, 8]}

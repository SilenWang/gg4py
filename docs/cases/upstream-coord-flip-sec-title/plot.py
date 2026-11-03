"""上游快照复刻：turning off secondary title with coord_flip。

源：coord-flip/turning-off-secondary-title-with-coord-flip.svg
（vdiffr 名 "turning off secondary title with coord_flip"）。

R：

    ggplot(mtcars, aes(x = mpg, y = cyl)) +
      geom_point() +
      scale_x_continuous(sec.axis = dup_axis(guide = guide_axis(title = NULL))) +
      coord_flip() +
      theme_test() +
      theme(panel.grid.major.y = element_line(colour = "grey80"),
            panel.grid.major.x = element_line(colour = "grey90"))

`cylin` 是连续量（4/6/8），翻转后 x 标度竖起来，`dup_axis()` 的次轴落到右侧；
`guide_axis(title = NULL)` 只去标题，刻度与标签照画。
"""

from ggcore.plot import (
    aes,
    coord_flip,
    dup_axis,
    geom_point,
    ggplot,
    guide_axis,
    labs,
    scale_x_continuous,
)
from ggcore.theme import element_line, theme, theme_test
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
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="mpg", y="cyl"))
        + geom_point()
        + scale_x_continuous(**{"sec.axis": dup_axis(guide=guide_axis(title=None))})
        + coord_flip()
        + theme_test()
        + theme(
            **{
                "panel.grid.major.y": element_line(colour="grey80"),
                "panel.grid.major.x": element_line(colour="grey90"),
            }
        )
        + labs(title="turning off secondary title with coord_flip")
    )
    return {"plot": p, "size": [10, 8]}

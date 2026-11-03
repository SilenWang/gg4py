"""上游快照复刻：sec_axis, sec power transform。

源：sec-axis/sec-axis-sec-power-transform.svg
（vdiffr 名 "sec_axis, sec power transform"）。

R：

    ggplot() +
      geom_point(aes(x = 1:10, y = rep(5, 10))) +
      scale_x_continuous(sec.axis = sec_axis(~ log10(.))) +
      theme_linedraw()

x 主轴是 1..10，次轴是 log10：右轴断点 = 主轴断点取对数后的值。次轴没给
`breaks`，所以按变换后的范围用默认断点推。
"""

import numpy as np

from ggcore.plot import aes, geom_point, ggplot, labs, scale_x_continuous, sec_axis
from ggcore.theme import theme_linedraw
from ggio.frame import to_column_table

DATA = {"x": [float(value) for value in range(1, 11)], "y": [5.0] * 10}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + scale_x_continuous(**{"sec.axis": sec_axis(np.log10)})
        + theme_linedraw()
        + labs(title="sec_axis, sec power transform")
    )
    return {"plot": p, "size": [10, 8]}

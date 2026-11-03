"""上游快照复刻：sec_axis, skewed transform。

源：sec-axis/sec-axis-skewed-transform.svg（vdiffr 名 "sec_axis, skewed transform"）。

R：

    x <- exp(seq(log(0.001), log(1000), length.out = 100))
    foo <- data_frame(x = x, y = x / (1 + x))

    ggplot(foo, aes(x, y)) +
      geom_point() +
      scale_x_continuous(
        name = "Unit A", transform = "log",
        breaks = c(0.001, 0.01, 0.1, 1, 10, 100, 1000),
        sec.axis = sec_axis(~ . * 100, name = "Unit B", labels = derive(), breaks = derive())
      ) +
      theme_linedraw()

主轴是自然对数。`breaks = derive()` / `labels = derive()` 让次轴沿用主轴那套断点
**规格**（在次轴空间里重新求值），所以右轴的断点是主轴断点乘 100。
"""

import numpy as np

from ggcore.axis import DERIVE
from ggcore.plot import aes, geom_point, ggplot, labs, scale_x_continuous, sec_axis
from ggcore.theme import theme_linedraw
from ggio.frame import to_column_table

_X = np.exp(np.linspace(np.log(0.001), np.log(1000.0), 100))

DATA = {
    "x": [float(value) for value in _X],
    "y": [float(value / (1.0 + value)) for value in _X],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + scale_x_continuous(
            name="Unit A",
            transform="log",
            breaks=(0.001, 0.01, 0.1, 1.0, 10.0, 100.0, 1000.0),
            **{
                "sec.axis": sec_axis(
                    lambda v: v * 100.0,
                    name="Unit B",
                    labels=DERIVE,
                    breaks=DERIVE,
                )
            },
        )
        + theme_linedraw()
        + labs(title="sec_axis, skewed transform")
    )
    return {"plot": p, "size": [10, 8]}

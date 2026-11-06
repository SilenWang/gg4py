"""上游快照复刻：bottom half circle with rotated text。

源：coord-polar/bottom-half-circle-with-rotated-text.svg

R：

    theme <- theme(
      axis.line.theta = element_line(colour = "tomato"),
      axis.line.r   = element_line(colour = "dodgerblue")
    )
    df <- data_frame0(
      x = 1:5, lab = c("cat", "strawberry\ncake", "coffee", "window", "fluid")
    )
    ggplot(df, aes(x, label = lab)) +
      geom_text(aes(y = "0 degrees"),  angle = 0) +
      geom_text(aes(y = "90 degrees"), angle = 90) +
      coord_radial(start = 0.5 * pi, end = 1.5 * pi,
                   rotate.angle = TRUE, r.axis.inside = FALSE) +
      theme

上游的 `aes(y = "0 degrees")` 是**常量美学**（字符串字面量，不是列名）。ggcore 的
`aes()` 把字符串按表达式解释，常量要写成带引号的表达式（`aes(y = "'0 degrees'")`），
这里照搬这个写法，不额外补 `labs(y = "y")`——常量美学下 y 轴标题就是默认的 `y`。
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ggcore.plot import aes, coord_radial, geom_text, ggplot, labs
from ggcore.theme import element_line, theme
from ggio.frame import to_column_table

DATA = {
    "x": [1.0, 2.0, 3.0, 4.0, 5.0],
    "lab": ["cat", "strawberry\ncake", "coffee", "window", "fluid"],
}

AXIS_THEME = theme(
    **{
        "axis.line.theta": element_line(colour="tomato"),
        "axis.line.r": element_line(colour="dodgerblue"),
    }
)


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", label="lab"))
        + geom_text(aes(y="'0 degrees'"), angle=0.0)
        + geom_text(aes(y="'90 degrees'"), angle=90.0)
        + AXIS_THEME
        + coord_radial(
            start=0.5 * math.pi,
            end=1.5 * math.pi,
            rotate_angle=True,
            r_axis_inside=False,
        )
        + labs(title="bottom half circle with rotated text")
    )
    return {"plot": p, "size": [10, 8]}

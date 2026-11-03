"""上游快照复刻：clip on by default, only 'inside' visible。

源：coord-cartesian/clip-on-by-default-only-inside-visible.svg
（vdiffr 名 "clip on by default, only 'inside' visible"）。

R：

    p <- ggplot(mapping = aes(x, y, label = label, angle = angle, hjust = hjust, vjust = vjust)) +
      geom_text(data = df.in) + geom_text(data = df.out) +
      scale_x_continuous(breaks = NULL, name = NULL) +
      scale_y_continuous(breaks = NULL, name = NULL) +
      theme(plot.margin = margin(20, 20, 20, 20), panel.spacing = unit(10, "pt"))
    p + coord_cartesian(xlim = c(0, 1), ylim = c(0, 1), expand = FALSE)

`df.in` 的 vjust 把文字压在面板内侧，`df.out` 的 vjust 把它推出去：clip 开着时只
看得见 inside 那一组。
"""

from ggcore.plot import (
    aes,
    coord_cartesian,
    geom_text,
    ggplot,
    labs,
    scale_x_continuous,
    scale_y_continuous,
)
from ggcore.theme import margin, theme
from ggcore.units import unit
from ggio.frame import to_column_table

INSIDE = {
    "label": ["inside", "inside", "inside", "inside"],
    "x": [0.0, 1.0, 0.5, 0.5],
    "y": [0.5, 0.5, 0.0, 1.0],
    "angle": [90.0, 270.0, 0.0, 0.0],
    "hjust": [0.5, 0.5, 0.5, 0.5],
    "vjust": [1.1, 1.1, -0.1, 1.1],
}

OUTSIDE = {
    "label": ["outside", "outside", "outside", "outside"],
    "x": [0.0, 1.0, 0.5, 0.5],
    "y": [0.5, 0.5, 0.0, 1.0],
    "angle": [90.0, 270.0, 0.0, 0.0],
    "hjust": [0.5, 0.5, 0.5, 0.5],
    "vjust": [-0.1, -0.1, 1.1, -0.1],
}


def build():
    p = (
        ggplot(
            mapping=aes(
                x="x",
                y="y",
                label="label",
                angle="angle",
                hjust="hjust",
                vjust="vjust",
            )
        )
        + geom_text(data=to_column_table(INSIDE))
        + geom_text(data=to_column_table(OUTSIDE))
        + scale_x_continuous(breaks=None, name=None)
        + scale_y_continuous(breaks=None, name=None)
        + theme(
            **{
                "plot.margin": margin(20, 20, 20, 20),
                "panel.spacing": unit(10, "pt"),
            }
        )
        + labs(title="clip on by default, only 'inside' visible")
        + coord_cartesian(xlim=(0.0, 1.0), ylim=(0.0, 1.0), expand=False)
    )
    return {"plot": p, "size": [10, 8]}

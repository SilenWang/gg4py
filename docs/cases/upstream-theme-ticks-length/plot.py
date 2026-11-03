"""upstream/theme：四个方向的刻度长度独立。"""

from ggcore.plot import (
    aes,
    dup_axis,
    geom_point,
    ggplot,
    labs,
    scale_x_continuous,
    scale_y_continuous,
)
from ggcore.theme import element_text, margin, theme, theme_test
from ggcore.viewport import unit
from ggio.frame import to_column_table

DATA = {"x": list(range(1, 11)), "y": list(range(1, 11))}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + theme_test()
        + geom_point()
        + scale_x_continuous(sec_axis=dup_axis())
        + scale_y_continuous(sec_axis=dup_axis())
        + theme(
            **{
                "axis.ticks.length.x.top": unit(-0.5, "cm"),
                "axis.ticks.length.x.bottom": unit(-0.25, "cm"),
                "axis.ticks.length.y.left": unit(0.25, "cm"),
                "axis.ticks.length.y.right": unit(0.5, "cm"),
                "axis.text.x.bottom": element_text(margin=margin(t=0.25, unit="cm")),
                "axis.text.x.top": element_text(margin=margin(b=0.25, unit="cm")),
            }
        )
        + labs(title="ticks_length")
    )
    return {"plot": p, "size": [10, 8]}

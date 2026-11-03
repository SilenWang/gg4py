"""upstream/theme：四边轴标题 / 文本 / 刻度 / 轴线独立着色。"""

from ggcore.plot import (
    aes,
    dup_axis,
    geom_point,
    ggplot,
    labs,
    scale_x_continuous,
    scale_y_continuous,
)
from ggcore.theme import element_line, element_text, theme
from ggio.frame import to_column_table

DATA = {"x": list(range(1, 11)), "y": list(range(1, 11))}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + scale_x_continuous(sec_axis=dup_axis())
        + scale_y_continuous(sec_axis=dup_axis())
        + theme(
            **{
                "axis.title.x.top": element_text(colour="red"),
                "axis.title.x.bottom": element_text(colour="green"),
                "axis.title.y.left": element_text(colour="blue"),
                "axis.title.y.right": element_text(colour="yellow"),
                "axis.text.x.top": element_text(colour="red"),
                "axis.text.x.bottom": element_text(colour="green"),
                "axis.text.y.left": element_text(colour="blue"),
                "axis.text.y.right": element_text(colour="yellow"),
                "axis.ticks.x.top": element_line(colour="red"),
                "axis.ticks.x.bottom": element_line(colour="green"),
                "axis.ticks.y.left": element_line(colour="blue"),
                "axis.ticks.y.right": element_line(colour="yellow"),
                "axis.line.x.top": element_line(colour="red"),
                "axis.line.x.bottom": element_line(colour="green"),
                "axis.line.y.left": element_line(colour="blue"),
                "axis.line.y.right": element_line(colour="yellow"),
            }
        )
        + labs(title="axes_styling")
    )
    return {"plot": p, "size": [10, 8]}

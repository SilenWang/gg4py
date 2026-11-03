from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    labs,
    scale_x_continuous,
    scale_y_continuous,
)
from ggcore.theme import element_rect, element_text, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": [1.0], "y": [1.0], "z": ["a"]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="z"))
        + geom_point()
        + labs(title="legend on right")
        + theme_test()
        + theme(
            **{
                "axis.text.x": element_text(angle=90, vjust=0.5),
                "legend.background": element_rect(fill="grey90"),
                "legend.key": element_rect(fill="grey90"),
                "legend.position": "right",
            }
        )
        + scale_x_continuous(breaks=(1,), labels=("very long axis label",))
        + scale_y_continuous(breaks=(1,), labels=("very long axis label",))
    )
    return {"plot": p, "size": [10, 8]}

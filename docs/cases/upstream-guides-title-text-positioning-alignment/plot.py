from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_colourbar,
    guide_legend,
    guides,
    labs,
)
from ggcore.theme import element_text, margin, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 10, 100]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="x", colour="x", size="x"))
        + geom_point()
        + guides(shape=guide_legend(order=1), colour=guide_colourbar(order=2))
        + theme_test()
        + labs(title="guide title and text positioning and alignment via themes")
        + theme(
            **{
                "legend.title": element_text(hjust=0.5, margin=margin(t=30, b=5.5)),
                "legend.text": element_text(hjust=1, margin=margin(l=10.5, t=10, b=10)),
            }
        )
    )
    return {"plot": p, "size": [10, 8]}

"""Scratch: guides/stylised-guide-custom."""

from ggcore.grobs import circle_grob
from ggcore.plot import ggplot, guide_custom, guides, labs
from ggcore.theme import element_rect, element_text, theme
from ggcore.units import unit

SNAPSHOT = "guides/stylised-guide-custom.svg"


def build():
    p = (
        ggplot()
        + guides(custom=guide_custom(circle_grob(r=unit(1.0, "cm")), title="custom guide"))
        + theme(
            **{
                "legend.background": element_rect(fill="grey50"),
                "legend.title.position": "left",
                "legend.title": element_text(angle=90, hjust=0.5),
            }
        )
        + labs(title="stylised guide_custom")
    )
    return {"plot": p, "size": [10, 8]}

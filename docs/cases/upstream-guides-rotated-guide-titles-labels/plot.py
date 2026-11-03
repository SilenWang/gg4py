from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_colourbar,
    guide_legend,
    labs,
    scale_colour_continuous,
    scale_fill_continuous,
)
from ggcore.theme import element_text, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": [5, 10, 15], "f": [10, 5, 0]}


def build():
    p = ggplot(to_column_table(DATA), aes(x="x", y="x", colour="x", fill="f")) + geom_point(
        shape=21, size=5, stroke=3
    )
    p = p + scale_colour_continuous(
        name="value",
        guide=guide_colourbar(
            theme=theme(
                **{
                    "legend.title": element_text(size=11, angle=0, hjust=0.5, vjust=1),
                    "legend.text": element_text(size=0.8 * 11, angle=270, hjust=0.5, vjust=1),
                }
            ),
            order=2,
        ),
    )
    p = p + scale_fill_continuous(
        breaks=(5, 10, 15),
        limits=(5, 15),
        labels=("long 5", "long 10", "long 15"),
        name="fill value",
        guide=guide_legend(
            direction="horizontal",
            theme=theme(
                **{
                    "legend.title.position": "top",
                    "legend.text.position": "bottom",
                    "legend.title": element_text(size=11, angle=180, hjust=0, vjust=1),
                    "legend.text": element_text(size=0.8 * 11, angle=90, hjust=1, vjust=0.5),
                }
            ),
            order=1,
        ),
    )
    p = p + theme_test() + labs(title="rotated guide titles and labels")
    return {"plot": p, "size": [10, 8]}

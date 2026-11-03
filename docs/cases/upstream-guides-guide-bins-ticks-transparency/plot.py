from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_coloursteps,
    guides,
    labs,
    scale_colour_binned,
)
from ggcore.theme import element_line, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 4], "y": [6, 5, 7]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="x"))
        + geom_point()
        + scale_colour_binned(breaks=(1.5, 2, 3))
        + guides(
            colour=guide_coloursteps(
                alpha=0.75,
                theme=theme(
                    **{"legend.ticks": element_line(linewidth=0.5 / 2.845276, colour="white")}
                ),
            )
        )
        + theme_test()
        + labs(title="guide_bins can show ticks and transparancy")
    )
    return {"plot": p, "size": [10, 8]}

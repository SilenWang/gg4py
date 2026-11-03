from ggcore.plot import (
    aes,
    arrow,
    geom_point,
    ggplot,
    guide_bins,
    guides,
    labs,
    scale_size_binned,
)
from ggcore.theme import element_line, theme, theme_test
from ggcore.units import unit
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [6, 5, 7]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", size="x"))
        + geom_point()
        + scale_size_binned()
        + guides(size=guide_bins())
        + theme_test()
        + theme(
            **{
                "legend.axis.line": element_line(
                    linewidth=0.5 / 2.845276,
                    arrow=arrow(length=unit(1.5, "mm"), ends="both"),
                )
            }
        )
        + theme_test()
        + labs(title="guide_bins can show arrows")
    )
    return {"plot": p, "size": [10, 8]}

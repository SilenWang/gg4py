from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_bins,
    guides,
    labs,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [0, 100]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="x", colour="x", fill="x"))
        + geom_point()
        + guides(
            colour=guide_bins(reverse=True, show_limits=True, order=1),
            fill=guide_bins(reverse=True, show_limits=False, order=2, override_aes={"shape": 21}),
        )
        + theme_test()
        + labs(title="reversed guide_bins")
    )
    return {"plot": p, "size": [10, 8]}

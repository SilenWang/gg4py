from ggcore.plot import (
    aes,
    geom_boxplot,
    geom_crossbar,
    ggplot,
    guide_legend,
    guides,
    labs,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {
    "middle": [1, 2],
    "lower": [0, 1],
    "upper": [2, 3],
    "min": [-1, 0],
    "max": [3, 4],
    "group1": ["a", "b"],
    "group2": ["c", "d"],
}


def build():
    p = (
        ggplot(
            to_column_table(DATA),
            aes(
                x="middle",
                xmiddle="middle",
                xlower="lower",
                xupper="upper",
                xmin="min",
                xmax="max",
            ),
        )
        + geom_boxplot(aes(y="group1", colour="group1"), stat="identity")
        + geom_crossbar(aes(y="group2", fill="group2"))
        + guides(colour=guide_legend(order=1))
        + theme_test()
        + labs(title="horizontal boxplot and crossbar")
    )
    return {"plot": p, "size": [10, 8]}

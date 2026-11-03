"""upstream/theme：`plot.title.position = "plot"`。"""

from ggcore.plot import aes, facet_wrap, geom_point, ggplot, labs
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 2, 3], "z": ["a", "b", "c"]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", color="z"))
        + geom_point()
        + facet_wrap("z")
        + labs(
            title="Plot title aligned to entire plot",
            subtitle="Subtitle aligned to entire plot",
            caption="Caption aligned to panels",
        )
        + theme(**{"plot.title.position": "plot"})
    )
    return {"plot": p, "size": [10, 8]}

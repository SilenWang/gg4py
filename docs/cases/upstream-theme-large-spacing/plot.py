"""upstream/theme：`theme(spacing = unit(1, "cm"))`。"""

from ggcore.plot import aes, facet_wrap, geom_point, ggplot, labs
from ggcore.theme import theme, theme_gray
from ggcore.viewport import unit
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 2, 3], "z": ["a", "b", "a"], "a": [1, 1, 1]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="z"))
        + geom_point()
        + facet_wrap("a")
        + theme_gray()
        + theme(**{"spacing": unit(1.0, "cm")})
        + labs(title="large spacing")
    )
    return {"plot": p, "size": [10, 8]}

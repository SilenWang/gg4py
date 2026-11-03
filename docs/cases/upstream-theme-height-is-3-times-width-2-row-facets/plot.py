"""upstream/theme：`theme(aspect.ratio = ...)`。"""

from ggcore.plot import aes, facet_grid, geom_point, ggplot, labs
from ggcore.theme import theme, theme_test
from ggio.frame import to_column_table

DATA = {
    "x": [1, 2, 3, 4, 5, 6, 7, 8],
    "y": [1, 2, 3, 4, 5, 6, 7, 8],
    "f": ["a", "a", "a", "a", "b", "b", "b", "b"],
    "f1": [1, 1, 1, 1, 2, 2, 2, 2],
    "f2": [1, 2, 1, 2, 1, 2, 1, 2],
    "rep": [1, 1, 2, 2, 1, 1, 2, 2],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + theme_test()
        + labs(x=None, y=None)
    )
    p = (
        p
        + theme(**{"aspect.ratio": 3})
        + facet_grid(rows="f")
        + labs(title="height is 3 times width, 2 row facets")
    )
    return {"plot": p, "size": [10, 8]}

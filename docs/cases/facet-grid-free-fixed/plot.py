"""facet：`facet_grid(space = "free")` + `coord_fixed(2)` —— 比例 = ratio × yspan / xspan。"""

from ggcore.plot import aes, coord_fixed, facet_grid, geom_point, ggplot
from ggcore.theme import theme, theme_void
from ggio.frame import to_column_table

DATA = {
    "x": [
        "a",
        "b",
        "a",
        "b",
        "c",
        "a",
        "b",
        "c",
        "a",
        "b",
        "a",
        "b",
        "c",
        "a",
        "b",
        "c",
    ],
    "y": [
        0.2,
        0.5,
        0.35,
        0.7,
        0.45,
        0.3,
        0.6,
        0.25,
        0.65,
        0.4,
        0.55,
        0.2,
        0.75,
        0.5,
        0.3,
        0.8,
    ],
    "r": ["t"] * 8 + ["u"] * 8,
    "c": [
        "l",
        "l",
        "l",
        "l",
        "l",
        "r",
        "r",
        "r",
        "l",
        "r",
        "l",
        "r",
        "l",
        "r",
        "l",
        "r",
    ],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point(shape=19, size=2.8, colour="#4C78A8")
        + facet_grid(rows="r", cols="c", space="free")
        + coord_fixed(2)
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

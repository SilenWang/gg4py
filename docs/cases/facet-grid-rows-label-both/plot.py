"""facet：`facet_grid(r1 + r2 ~ .)` —— 多行变量的右侧 strip（最后一个变量贴面板）。"""

from ggcore.plot import aes, facet_grid, geom_point, ggplot
from ggcore.theme import theme, theme_void
from ggio.frame import to_column_table

DATA = {
    "x": [0.2, 0.6, 0.3, 0.7, 0.25, 0.65, 0.35, 0.75, 0.15, 0.55, 0.4, 0.8],
    "y": [0.3, 0.5, 0.6, 0.4, 0.55, 0.25, 0.45, 0.8, 0.35, 0.65, 0.2, 0.7],
    "r1": ["t"] * 6 + ["u"] * 6,
    "r2": ["a", "b", "a", "b", "a", "b"] * 2,
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point(shape=19, size=2.8, colour="#F58518")
        + facet_grid(rows=("r1", "r2"), labeller="label_both")
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

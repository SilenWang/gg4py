"""facet：`facet_wrap(strip.position = "bottom")`。

strip 落在面板与 x 轴之间，轴标签 / 轴标题在 strip 之外（R `attach_strips()` 的
`shift = 0`）。主题用 `theme_grey()`：轴、网格、strip 背景都在。
"""

from ggcore.plot import aes, facet_wrap, geom_point, ggplot, labs
from ggcore.theme import theme_grey
from ggio.frame import to_column_table

DATA = {
    "x": [0.10, 0.35, 0.60, 0.85, 0.15, 0.40, 0.65, 0.90],
    "y": [0.25, 0.70, 0.40, 0.85, 0.30, 0.65, 0.20, 0.75],
    "g": ["a", "a", "a", "a", "b", "b", "b", "b"],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point(shape=19, size=2.8, colour="#4C78A8")
        + facet_wrap("g", ncol=2, **{"strip.position": "bottom"})
        + labs(x="x value", y="y value")
        + theme_grey()
    )
    return {"plot": p, "size": SIZE}

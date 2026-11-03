"""guide：`guide_axis(cap="both")` 把轴线收到最外一根刻度。

主题里要显式给 `axis.line`（默认主题里它是 `element_blank()`）；R 的
`GuideAxis$extract_decor()` 把端点从 `(-Inf, Inf)` 收到 `range(key)`，
见 docs/notes/guide.md §8.3。
"""

from ggcore.plot import aes, geom_point, ggplot, guide_axis, guides
from ggcore.theme import element_line, theme
from ggio.frame import to_column_table

DATA = {
    "x": [1.5, 1.8, 2.2, 2.6, 3.0, 3.4, 3.8, 4.2, 4.6, 5.0, 5.3, 5.6],
    "y": [26.0, 25.0, 24.5, 23.0, 22.5, 21.0, 20.5, 19.5, 18.0, 17.5, 16.5, 15.0],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point(shape=19, size=1.8)
        + guides(x=guide_axis(cap="both"), y=guide_axis(cap="both"))
        + theme(**{"axis.line": element_line(colour="black")})
    )
    return {"plot": p, "size": SIZE}

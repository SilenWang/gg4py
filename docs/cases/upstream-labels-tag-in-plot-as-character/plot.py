"""upstream/labels：tag 在整张图内（字符位置）。"""

from ggcore.plot import aes, geom_point, ggplot, labs
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {"x": list(range(1, 11)), "y": list(range(10, 0, -1))}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + labs(title="Tag in plot, as character", tag="Fig. A)")
        + theme(**{"plot.tag.position": "bottomleft", "plot.tag.location": "plot"})
    )
    return {"plot": p, "size": [10, 8]}

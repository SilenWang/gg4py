"""upstream/labels：tag 在面板内的 npc 位置。"""

from ggcore.plot import aes, geom_point, ggplot, labs
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {"x": list(range(1, 11)), "y": list(range(10, 0, -1))}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + labs(title="Tag in panel, as numeric", tag="Fig. A)")
        + theme(**{"plot.tag.position": (0.25, 0.25), "plot.tag.location": "panel"})
    )
    return {"plot": p, "size": [10, 8]}

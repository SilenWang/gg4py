"""upstream/theme：`axis.text.x` 旋转 50°、hjust=1。"""

from ggcore.plot import aes, geom_point, ggplot, labs
from ggcore.theme import element_text, theme
from ggio.frame import to_column_table

DATA = {"label": ["short", "medium size", "very long label"], "y": [1, 2, 3]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="label", y="y"))
        + geom_point()
        + theme(**{"axis.text.x": element_text(angle=50, hjust=1)})
        + labs(title="rotated x axis tick labels")
    )
    return {"plot": p, "size": [10, 8]}

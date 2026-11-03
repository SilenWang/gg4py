"""upstream/theme：strip.background.x/.y 独立着色。"""

from ggcore.plot import aes, facet_grid, geom_blank, ggplot, labs
from ggcore.theme import element_rect, theme
from ggio.frame import to_column_table

DATA = {"x": [1, 2], "y": [1, 2]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_blank()
        + facet_grid(rows="x", cols="y")
        + theme(
            **{
                "strip.background.x": element_rect(fill="red"),
                "strip.background.y": element_rect(fill="green"),
            }
        )
        + labs(title="strip_styling")
    )
    return {"plot": p, "size": [10, 8]}

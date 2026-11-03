"""upstream/theme：`legend.spacing.x = unit(1, "null")`。"""

from ggcore.plot import aes, geom_point, ggplot, labs
from ggcore.theme import element_rect, theme
from ggcore.viewport import unit
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 2, 3], "a": ["a", "b", "c"]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="a", shape="x"))
        + geom_point()
        + theme(
            **{
                "legend.box.background": element_rect(colour="blue", fill=None),
                "legend.background": element_rect(colour="red", fill=None),
            }
        )
        + theme(
            **{
                "legend.position": "top",
                "legend.spacing.x": unit(1.0, "null"),
            }
        )
        + labs(title="horizontal legends placed apart")
    )
    return {"plot": p, "size": [10, 8]}

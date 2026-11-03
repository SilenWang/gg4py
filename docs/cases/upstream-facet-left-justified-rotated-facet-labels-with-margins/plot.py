"""upstream/facet：strip 文本旋转后左对齐 + margin。"""

from ggcore.plot import aes, facet_grid, geom_point, ggplot, labs, theme_test
from ggcore.theme import element_text, margin, theme
from ggio.frame import to_column_table

DATA = {
    "x": [1, 2],
    "y": [1, 2],
    "z": ["a", "aaaaaaabc"],
    "g": ["b", "bbbbbbbcd"],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + facet_grid(rows="g", cols="z")
        + theme_test()
        + theme(
            **{
                "strip.text.x": element_text(angle=90, hjust=0, margin=margin(5, 5, 5, 5)),
                "strip.text.y": element_text(angle=0, hjust=0, margin=margin(5, 5, 5, 5)),
            }
        )
        + labs(title="left justified rotated facet labels with margins")
    )
    return {"plot": p, "size": [10, 8]}

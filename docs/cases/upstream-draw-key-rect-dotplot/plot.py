"""Scratch: draw-key/rectangle-and-dotplot-key-glyphs."""

from ggcore.plot import aes, geom_line, geom_point, ggplot, guide_legend, guides, labs
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [3, 2, 1], "z": ["a", "b", "c"], "line": ["line", "line", "line"]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_line(aes(colour="line"), key_glyph="rect")
        + geom_point(aes(fill="z"), shape=21, size=3, **{"stroke": 2}, key_glyph="dotplot")
        + guides(fill=guide_legend(order=1))
        + theme_test()
        + labs(title="rectangle and dotplot key glyphs")
    )
    return {"plot": p, "size": [10, 8]}

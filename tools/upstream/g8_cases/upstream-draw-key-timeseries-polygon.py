"""Scratch: draw-key/time-series-and-polygon-key-glyphs."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from ggcore.plot import aes, geom_line, geom_point, ggplot, guide_legend, guides, labs
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [3, 2, 1], "z": ["a", "b", "c"], "line": ["line", "line", "line"]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_line(aes(colour="line"), key_glyph="timeseries")
        + geom_point(aes(fill="z"), shape=21, size=3, key_glyph="polygon")
        + guides(fill=guide_legend(order=1))
        + theme_test()
        + labs(title="time series and polygon key glyphs")
    )
    return {"plot": p, "size": [10, 8]}

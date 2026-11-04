"""upstream/patterns：单个平铺图案填充（`geom_col(fill = pattern(...))`）。

R 的 `pattern(rectGrob(c(0.25, 0.75), c(0.25, 0.75), width = 0.5, height = 0.5,
gp = gpar(fill = "black", col = NA)), width = unit(1, "cm"), height = unit(1, "cm"),
extend = "repeat")`：1cm 的 tile，内容是两块对角黑方块。
"""

from ggcore.fills import pattern_rect
from ggcore.plot import aes, geom_col, ggplot, labs, theme_test, tile_pattern
from ggio.frame import to_column_table

DATA = {"x": ["A", "B", "C", "D"], "y": [2, 3, 4, 5]}

#: 1cm（= 28.3465pt）的 tile。
TILE = 28.3465


def draw(tile: tuple[float, float, float, float]) -> list:
    x0, y0, x1, y1 = tile
    mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    return [
        pattern_rect((x0, y0, mx, my), "#000000"),
        pattern_rect((mx, my, x1, y1), "#000000"),
    ]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_col(
            fill=tile_pattern(draw, width=TILE, height=TILE, x=TILE / 2, y=TILE / 2, units="pt"),
            colour=None,
        )
        + labs(title="single pattern fill")
        + theme_test()
    )
    return {"plot": p, "size": [10, 8]}

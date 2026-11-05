"""upstream/patterns：单个平铺图案填充（`geom_col(fill = pattern(...))`）。

R 的 `pattern(rectGrob(c(0.25, 0.75), c(0.25, 0.75), width = 0.5, height = 0.5,
gp = gpar(fill = "black", col = NA)), width = unit(1, "cm"), height = unit(1, "cm"),
extend = "repeat")`：1cm 的 tile，内容是两块对角黑方块——内容按**整层 grob 的
包围盒 npc** 摆（SIL-833），tile 只决定裁剪窗口与重复周期。
"""

from ggcore.fills import Box, pattern_npc_rect
from ggcore.plot import aes, geom_col, ggplot, labs, theme_test, tile_pattern
from ggio.frame import to_column_table

DATA = {"x": ["A", "B", "C", "D"], "y": [2, 3, 4, 5]}

#: 1cm = 28.3465pt 的 tile（R `unit(1, "cm")` 的绝对尺寸）。
TILE = 28.3465


def draw(bbox: Box) -> list:
    """`rectGrob(c(0.25, 0.75), c(0.25, 0.75), width = 0.5, height = 0.5)`。"""
    return [
        pattern_npc_rect(bbox, 0.25, 0.25, 0.5, 0.5, "#000000"),
        pattern_npc_rect(bbox, 0.75, 0.75, 0.5, 0.5, "#000000"),
    ]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_col(
            fill=tile_pattern(draw, width=TILE, height=TILE, units="pt"),
            colour=None,
        )
        + labs(title="single pattern fill")
        + theme_test()
    )
    return {"plot": p, "size": [10, 8]}

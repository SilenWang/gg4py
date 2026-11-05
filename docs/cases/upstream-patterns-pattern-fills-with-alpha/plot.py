"""upstream/patterns：逐行混合填充 + 逐行 alpha（`geom_col(fill = patterns, alpha = …)`）。

与 `pattern-fills-no-alpha` 同一份填充列表，另加 `alpha = c(0.8, 0.6, 0.4, 0.2)`：
纯色的 alpha 折进颜色，渐变 / 图案的 alpha 走 `gpar.alpha`（R 那边是
`fill_alpha()` 挂的 `grid::GridMask`，设备把它乘到整个填充上）。
"""

from ggcore.fills import Box, pattern_npc_rect
from ggcore.plot import (
    aes,
    geom_col,
    ggplot,
    labs,
    linear_gradient,
    radial_gradient,
    theme_test,
    tile_pattern,
)
from ggio.frame import to_column_table

DATA = {"x": ["A", "B", "C", "D"], "y": [2, 3, 4, 5]}

#: 1cm = 28.3465pt 的 tile（R `unit(1, "cm")` 的绝对尺寸）。
TILE = 28.3465

#: R 的 `alpha = c(0.8, 0.6, 0.4, 0.2)`。
ALPHA = [0.8, 0.6, 0.4, 0.2]


def draw(bbox: Box) -> list:
    """`rectGrob(c(0.25, 0.75), c(0.25, 0.75), width = 0.5, height = 0.5)`。"""
    return [
        pattern_npc_rect(bbox, 0.25, 0.25, 0.5, 0.5, "#000000"),
        pattern_npc_rect(bbox, 0.75, 0.75, 0.5, 0.5, "#000000"),
    ]


def build():
    patterns = [
        linear_gradient(["#000000", "#FFFFFF"], group=False),
        radial_gradient(["#000000", "#FFFFFF"], group=False),
        tile_pattern(draw, width=TILE, height=TILE, units="pt"),
        "black",
    ]
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_col(fill=patterns, alpha=ALPHA)
        + labs(title="pattern fills, with alpha")
        + theme_test()
    )
    return {"plot": p, "size": [10, 8]}

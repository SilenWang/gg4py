"""upstream/patterns：逐行的渐变 / 图案混合填充（`geom_col(fill = patterns)`）。

R 的 `patterns <- list(linearGradient(group = FALSE), radialGradient(group = FALSE),
pattern(rectGrob(...), width = unit(1, "cm"), height = unit(1, "cm")), "black")`：
四根柱子各吃一个填充，用 R 的按模回收铺到行上。

两个口径同时被守：

- `group = FALSE` 的渐变**逐元素**各用自己的 bbox 折 npc（bar 1 / bar 2）；
- `pattern()` 没有 `group`，内容按**整层** grob 的 bbox 折（bar 3，与
  `single-pattern-fill` 同一份内容，只是 tile 之外多了一层的其它柱子）。
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


def draw(bbox: Box) -> list:
    """`rectGrob(c(0.25, 0.75), c(0.25, 0.75), width = 0.5, height = 0.5)`。"""
    return [
        pattern_npc_rect(bbox, 0.25, 0.25, 0.5, 0.5, "#000000"),
        pattern_npc_rect(bbox, 0.75, 0.75, 0.5, 0.5, "#000000"),
    ]


def patterns() -> list:
    return [
        linear_gradient(["#000000", "#FFFFFF"], group=False),
        radial_gradient(["#000000", "#FFFFFF"], group=False),
        tile_pattern(draw, width=TILE, height=TILE, units="pt"),
        "black",
    ]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_col(fill=patterns())
        + labs(title="pattern fills, no alpha")
        + theme_test()
    )
    return {"plot": p, "size": [10, 8]}

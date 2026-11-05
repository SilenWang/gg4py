"""upstream/patterns：填充值经标度（`scale_fill_manual(values = rev(patterns))`）。

R 的 `aes(x, y, fill = x)` + `scale_fill_manual(values = rev(patterns))`：四个水平
依次拿到 black / pattern / radialGradient / linearGradient，图例键也各拿一个。

标度承载的是**填充对象**（不是颜色串）：`HueScale` 的 `values` 里保留 `FillSpec`，
`build._assemble()` 按水平码把它摊成逐行的填充值（`Column` 没有 object kind）。
"""

from ggcore.fills import Box, pattern_npc_rect
from ggcore.plot import (
    aes,
    geom_col,
    ggplot,
    labs,
    linear_gradient,
    radial_gradient,
    scale_fill_manual,
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
        ggplot(to_column_table(DATA), aes(x="x", y="y", fill="x"))
        + geom_col()
        + scale_fill_manual(values=list(reversed(patterns())))
        + labs(title="pattern fills through scale")
        + theme_test()
    )
    return {"plot": p, "size": [10, 8]}

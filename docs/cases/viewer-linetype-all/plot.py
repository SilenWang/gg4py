"""SVG 渲染器：`lty` 的全部取值（solid / dashed / dotted / dotdash / longdash /
twodash / blank）在同一个面板里各画一条线（M2-12）。

这个 case 守的是 `stroke-dasharray` 的折算口径：IR 的 `lty` 段长是 **lwd 倍数**，
写进 SVG 时要乘线宽、再乘视口变换的平均缩放（√|det|）；`blank` 是「不描边」，
不是「实线」。参考图由 `tools/refs/viewer_cases_ref.R` 生成。
"""

from ggcore.plot import (
    aes,
    geom_line,
    ggplot,
    scale_linetype_manual,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

XS = [0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95]
ZIGZAG = [0.00, 0.03, -0.02, 0.04, -0.03, 0.02, -0.04, 0.03, -0.01, 0.02]
BASES = [0.08, 0.22, 0.36, 0.50, 0.64, 0.78, 0.92]
LINETYPES = ["solid", "dashed", "dotted", "dotdash", "longdash", "twodash", "blank"]
# 离散水平的顺序：ggplot2 对**字符**列按 `sort(unique(x))` 排，不用出现顺序。
# 所以组的名字取 `l1..l7`（字典序 == 想要的顺序），两边才不会各认一套。
LEVELS = [f"l{index + 1}" for index in range(len(LINETYPES))]

DATA = {
    "x": XS * len(BASES),
    "y": [round(base + offset, 6) for base in BASES for offset in ZIGZAG],
    "lt": [level for level in LEVELS for _ in XS],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", linetype="lt", group="lt"))
        + geom_line(linewidth=1.0)
        + scale_linetype_manual(values=list(LINETYPES))
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

"""上游快照复刻：grid 直画的一条轴。

vdiffr 名：`axis guides, vertical rotation`。
源：`guide-axis/axis-guides-vertical-rotation.svg`
（vdiffr 名 `axis guides, vertical rotation`）。

上游 `test_draw_axis()` 不是 ggplot：它用 `draw_axis()` 在 0.05 / 0.9 / 0.05 npc
的三格 gtable 里直画四条轴。这里用一张空面板 + 四条轴（主轴 + `dup_axis()`）复现
同一版式：面板落在页面的 5%..95%，刻度与标签都画在面板内侧
（`axis.ticks.length` 取负值，R 的 guide 就是这么把轴线、刻度、文字排进同一个
单元格的）。
"""

from ggcore.plot import (
    aes,
    dup_axis,
    geom_blank,
    ggplot,
    guide_axis,
    guides,
    labs,
    scale_x_continuous,
    scale_y_continuous,
)
from ggcore.theme import element_line, margin, theme, theme_test
from ggcore.units import unit
from ggio.frame import to_column_table

DATA = {"x": [0.0, 1.0], "y": [0.0, 1.0]}
BREAKS = (
    0.0909090909,
    0.1818181818,
    0.2727272727,
    0.3636363636,
    0.4545454545,
    0.5454545455,
    0.6363636364,
    0.7272727273,
    0.8181818182,
    0.9090909091,
)
LABELS = (
    "1,000",
    "2,000",
    "3,000",
    "4,000",
    "5,000",
    "6,000",
    "7,000",
    "8,000",
    "9,000",
    "10,000",
)

#: 面板落在 5%..95%（上游 gtable 的 0.05 / 0.9 / 0.05 npc）；轴带（刻度 + 文字）
#: 占掉的部分从 36pt 里扣，值由渲染后量面板得到。
MARGIN = margin(-0.298, 26.044, -0.298, 26.044)


def build():
    axis = dict(angle=90)
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_blank()
        + scale_x_continuous(
            limits=(0.0, 1.0),
            expand=(0.0, 0.0),
            breaks=BREAKS,
            labels=LABELS,
            **{"sec.axis": dup_axis()},
        )
        + scale_y_continuous(
            limits=(0.0, 1.0),
            expand=(0.0, 0.0),
            breaks=BREAKS,
            labels=LABELS,
            **{"sec.axis": dup_axis()},
        )
        + labs(x=None, y=None)
        + guides(
            x=guide_axis(**axis),
            y=guide_axis(**axis),
            **{"x.sec": guide_axis(**axis), "y.sec": guide_axis(**axis)},
        )
        + theme_test()
        + theme(
            **{
                "axis.line": element_line(linewidth=0.5),
                "axis.ticks.length": unit(-2.75, "pt"),
                "plot.margin": MARGIN,
            }
        )
    )
    return {"plot": p, "size": [10, 8]}

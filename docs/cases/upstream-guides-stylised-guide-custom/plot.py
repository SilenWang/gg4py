"""上游快照复刻：`stylised guide_custom`。

源：`guides/stylised-guide-custom.svg`

R：

    p <- ggplot() + guides(custom = guide_custom(
      circleGrob(r = unit(1, "cm")), title = "custom guide"))
    p + theme(legend.background = element_rect(fill = "grey50"),
              legend.title.position = "left",
              legend.title = element_text(angle = 90, hjust = 0.5))

图例盒的尺寸由**自定义 grob 的包围盒**决定（`grobWidth()` / `grobHeight()`，这里是
2 × 2 cm 的圆），不是 `legend.key.size`；标题竖排（`angle = 90`）后标题列宽 =
标题高。上游是 `ggplot()`（没有图层），三文件 case 用 `geom_blank()` 铺一层空数据，
像素上没有区别。
"""

from ggcore.grobs import circle_grob
from ggcore.plot import aes, geom_blank, ggplot, guide_custom, guides, labs
from ggcore.theme import element_blank, element_rect, element_text, theme
from ggcore.units import unit
from ggio.frame import to_column_table

EMPTY = {"x": [], "y": []}


def build():
    p = (
        ggplot(to_column_table(EMPTY), aes(x="x", y="y"))
        + geom_blank()
        + guides(custom=guide_custom(circle_grob(r=unit(1.0, "cm")), title="custom guide"))
        + theme(
            **{
                "legend.background": element_rect(fill="grey50"),
                "legend.title.position": "left",
                "legend.title": element_text(angle=90, hjust=0.5),
                # R 的 `ggplot()` 没有图层 → 没有标度，面板上既没有轴也没有网格线。
                # 三文件 case 至少要一层（用 `geom_blank()`），xref 的 breaks 会
                # 画出 0..1 的网格与轴，这里按「没有标度」抹掉。
                "axis.text": element_blank(),
                "axis.ticks": element_blank(),
                "axis.title": element_blank(),
                "panel.grid": element_blank(),
            }
        )
        # vdiffr 把 doppelganger 名写进 `plot.title`。
        + labs(title="stylised guide_custom")
    )
    return {"plot": p, "size": [10, 8]}

"""上游快照复刻：stretchy 横向图例（`legend.key.width = unit(1, "null")`）。

源：theme/stretched-horizontal-legends.svg

R：

    p + guides(
      colour = guide_colourbar(theme = theme(legend.key.width = unit(1, "null"))),
      shape  = guide_legend(theme = theme(legend.key.width = unit(1/3, "null")))
    ) + theme(
      legend.position = "top",
      legend.box.margin = margin(l = 5, r = 10, unit = "mm"),
      legend.margin = margin(l = 10, r = 5, unit = "mm")
    )
"""

from ggcore.plot import aes, geom_point, ggplot, guide_colourbar, guide_legend, guides, labs
from ggcore.theme import element_rect, margin, theme, theme_test
from ggcore.units import unit
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 2, 3], "a": ["a", "b", "c"]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="x", shape="a"))
        + geom_point()
        + theme_test()
        + theme(
            **{
                "legend.box.background": element_rect(colour="blue", fill=None),
                "legend.background": element_rect(colour="red", fill=None),
            }
        )
        + guides(
            # 与 R 的 guide-box 顺序对齐（R 按 `order` + 内容 hash 排序，这条快照里
            # shape 在左）；显式 `order=` 把顺序钉死。
            colour=guide_colourbar(theme=theme(**{"legend.key.width": unit(1.0, "null")}), order=2),
            shape=guide_legend(
                theme=theme(**{"legend.key.width": unit(1.0 / 3.0, "null")}), order=1
            ),
        )
        + theme(
            **{
                "legend.position": "top",
                "legend.box.margin": margin(l=5, r=10, unit="mm"),
                "legend.margin": margin(l=10, r=5, unit="mm"),
            }
        )
        + labs(title="stretched horizontal legends")
    )
    return {"plot": p, "size": [10, 8]}

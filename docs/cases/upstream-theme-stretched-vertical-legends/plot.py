"""上游快照复刻：stretchy 竖向图例（`legend.key.height = unit(1, "null")`）。

源：theme/stretched-vertical-legends.svg

R：

    df <- data_frame(x = 1:3, y = 1:3, a = letters[1:3])
    p <- ggplot(df, aes(x, y, colour = x, shape = a)) + geom_point() + theme_test() +
      theme(
        legend.box.background = element_rect(colour = "blue", fill = NA),
        legend.background = element_rect(colour = "red", fill = NA)
      )
    p + guides(
      colour = guide_colourbar(theme = theme(legend.key.height = unit(1, "null"))),
      shape  = guide_legend(theme = theme(legend.key.height = unit(1/3, "null")))
    ) + theme(
      legend.box.margin = margin(t = 5, b = 10, unit = "mm"),
      legend.margin = margin(t = 10, b = 5, unit = "mm")
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
            # R 4.0.3 的 guide-box 顺序由 `order` + 内容 hash 决定（`Guides$merge()`
            # 里 `split()` 按 `"99_<hash>"` 排），这条快照里 shape 在上。显式
            # `order=` 把同一顺序钉死，避免依赖哈希。
            colour=guide_colourbar(
                theme=theme(**{"legend.key.height": unit(1.0, "null")}), order=2
            ),
            shape=guide_legend(
                theme=theme(**{"legend.key.height": unit(1.0 / 3.0, "null")}), order=1
            ),
        )
        + theme(
            **{
                "legend.box.margin": margin(t=5, b=10, unit="mm"),
                "legend.margin": margin(t=10, b=5, unit="mm"),
            }
        )
        + labs(title="stretched vertical legends")
    )
    return {"plot": p, "size": [10, 8]}

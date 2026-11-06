"""上游快照复刻：logtick axes with customisation。

源：guide-axis/logtick-axes-with-customisation.svg
（vdiffr 名 "logtick axes with customisation"）。

R：

    ggplot(data.frame(x = c(-100, 100), y = c(10, 1000)), aes(x, y)) +
      geom_point() +
      scale_y_continuous(
        transform = transform_compose(transform_log10(), transform_reverse()),
        expand = expansion(add = 0.5)
      ) +
      scale_x_continuous(breaks = c(-100, -10, -1, 0, 1, 10, 100)) +
      coord_transform(x = transform_pseudo_log()) +
      theme_test() +
      theme(axis.line = element_line(colour = "black"),
            panel.border = element_blank(),
            axis.ticks.length.x.top = unit(-2.75, "pt")) +
      guides(
        x = guide_axis_logticks(title = "Pseudo-logticks with 1 as smallest tick",
                                negative.small = 1),
        y = guide_axis_logticks(title = "Inverted logticks with swapped tick lengths",
                                long = 0.75, short = 2.25),
        x.sec = guide_axis_logticks(
          negative.small = 0.1,
          title = "Negative length pseudo-logticks with 0.1 as smallest tick"
        ),
        y.sec = guide_axis_logticks(expanded = FALSE, cap = "both",
                                    title = "Capped and not-expanded inverted logticks")
      )

`expand = expansion(add = 0.5)` 在本仓写成 `expand=(0, 0.5)`（`(mult, add)`）。
"""

from ggcore.plot import (
    aes,
    coord_transform,
    geom_point,
    ggplot,
    guide_axis_logticks,
    guides,
    labs,
    scale_x_continuous,
    scale_y_continuous,
)
from ggcore.scales import (
    transform_compose,
    transform_log10,
    transform_pseudo_log,
    transform_reverse,
)
from ggcore.theme import element_blank, element_line, theme, theme_test
from ggcore.units import unit
from ggio.frame import to_column_table

DATA = {"x": [-100.0, 100.0], "y": [10.0, 1000.0]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + scale_y_continuous(
            transform=transform_compose(transform_log10(), transform_reverse()),
            expand=(0, 0.5),
        )
        + scale_x_continuous(breaks=[-100.0, -10.0, -1.0, 0.0, 1.0, 10.0, 100.0])
        + coord_transform(x=transform_pseudo_log())
        + theme_test()
        + theme(
            **{
                "axis.line": element_line(colour="black"),
                "panel.border": element_blank(),
                "axis.ticks.length.x.top": unit(-2.75, "pt"),
            }
        )
        + guides(
            x=guide_axis_logticks(
                title="Pseudo-logticks with 1 as smallest tick",
                negative_small=1,
            ),
            y=guide_axis_logticks(
                title="Inverted logticks with swapped tick lengths",
                long=0.75,
                short=2.25,
            ),
            **{
                "x.sec": guide_axis_logticks(
                    negative_small=0.1,
                    title="Negative length pseudo-logticks with 0.1 as smallest tick",
                ),
                "y.sec": guide_axis_logticks(
                    expanded=False,
                    cap="both",
                    title="Capped and not-expanded inverted logticks",
                ),
            },
        )
        + labs(title="logtick axes with customisation")
    )
    return {"plot": p, "size": [10, 8]}

"""上游快照复刻。

源：guides/facet-grid-legend-on-bottom.svg（vdiffr 名 'facet_grid, legend on bottom'）。
自动生成：`pixi run snapshots:import`。expected.svg 是上游那份，未改写。
"""

from ggcore.plot import (
    aes,
    facet_grid,
    geom_point,
    ggplot,
    labs,
    scale_x_continuous,
    scale_y_continuous,
)
from ggcore.theme import (
    element_rect,
    element_text,
    theme,
    theme_test,
)
from ggio.frame import to_column_table

DATA = {"x": [1.0], "y": [1.0], "z": ["a"]}


def build():
    base = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="z"))
        + geom_point()
        + labs(title="title of plot")
        + theme_test()
        + theme(
            **{
                "axis.text.x": element_text(angle=90, vjust=0.5),
                "legend.background": element_rect(fill="grey90"),
                "legend.key": element_rect(fill="grey90"),
            }
        )
        + scale_x_continuous(breaks=(1,), labels=("very long axis label",))
        + scale_y_continuous(breaks=(1,), labels=("very long axis label",))
    )
    p = (
        base
        + facet_grid(rows="x", cols="y")
        + theme(**{"legend.position": "bottom"})
        + labs(title="facet_grid, legend on bottom")
    )
    return {"plot": p, "size": [10, 8]}

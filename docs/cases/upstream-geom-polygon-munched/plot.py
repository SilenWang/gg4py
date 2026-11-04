"""上游快照复刻：open and closed munched polygons。

源：`geom-polygon/open-and-closed-munched-polygons.svg`。`test-geom-polygon.R` 的 "geom_polygon
is closed before munching"
（vdiffr 名 `open and closed munched polygons`）。

R：

    df <- data_frame0(x = c(1, 1, 4, 4, 2, 2, 3, 3),
                      y = c(1, 4, 4, 1, 2, 3, 3, 2),
                      sub = c(1, 1, 1, 1, 2, 2, 2, 2))
    p <- ggplot(df, aes(x, y, subgroup = sub)) +
      geom_polygon() + xlim(c(0.5, 4.5)) + ylim(c(0, 5)) + coord_polar()
    built <- ggplot_build(p)
    closed <- coord_munch(coord, data, param, is_closed = TRUE)
    open   <- coord_munch(coord, data, param, is_closed = FALSE)
    ggplot(mapping = aes(x = x, y = y, group = subgroup)) +
      geom_polygon(aes(colour = "closed"), data = closed, fill = NA) +
      geom_polygon(aes(colour = "open"), data = open, fill = NA) +
      theme_void()

两条多边形都先按**极坐标**做 `coord_munch()`（边被细分成弧），再把磨好的 npc
数据当普通数据用笛卡尔坐标画出来——这就是「闭合 / 不闭合」的差别所在。
"""

import numpy as np

from ggcore.build import build_plot
from ggcore.data import Column, ColumnTable
from ggcore.plot import (
    aes,
    coord_munch,
    coord_polar,
    geom_polygon,
    ggplot,
    labs,
    scale_x_continuous,
    scale_y_continuous,
)
from ggcore.theme import theme_void
from ggio.frame import to_column_table

DAT = {
    "x": [1.0, 1.0, 4.0, 4.0, 2.0, 2.0, 3.0, 3.0],
    "y": [1.0, 4.0, 4.0, 1.0, 2.0, 3.0, 3.0, 2.0],
    "sub": ["1", "1", "1", "1", "2", "2", "2", "2"],
}

BASE = (
    ggplot(to_column_table(DAT), aes(x="x", y="y", group="sub"))
    + geom_polygon()
    + scale_x_continuous(limits=(0.5, 4.5))
    + scale_y_continuous(limits=(0.0, 5.0))
    + coord_polar()
)


def _munged(is_closed: bool) -> ColumnTable:
    """`coord_munch(coord, data, param, is_closed = …)`：极坐标下的磨点。"""
    built = build_plot(BASE)
    data = built.layers[0].data
    table = ColumnTable(
        [("x", data.column("x")), ("y", data.column("y")), ("group", data.column("group"))],
        nrows=data.nrows,
    )
    return coord_munch(built.panels[0].panel_params, table, group="group", is_closed=is_closed)


def _with_label(table: ColumnTable, label: str) -> ColumnTable:
    """R 的 `aes(colour = "closed")`：整层一个常量类别（图例两档）。"""
    columns = [(name, table.column(name)) for name in table.names]
    columns.append(("which", Column("str", np.array([label] * table.nrows, dtype=object))))
    return ColumnTable(columns, nrows=table.nrows)


def build():
    closed = _munged(True)
    opened = _munged(False)
    p = (
        ggplot(mapping=aes(x="x", y="y", group="group"))
        + geom_polygon(data=_with_label(closed, "closed"), mapping=aes(colour="which"), fill=None)
        + geom_polygon(data=_with_label(opened, "open"), mapping=aes(colour="which"), fill=None)
        + theme_void()
        + labs(title="open and closed munched polygons")
    )
    return {"plot": p, "size": [10, 8]}

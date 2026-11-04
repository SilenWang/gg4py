"""上游快照复刻：`element_polygon()` 的 `element_grob()`（裸 grob）。

源：theme/polygon-elements.svg

R：

    t <- theme_gray() + theme(polygon = element_polygon(fill = "orchid"))
    e <- calc_element("polygon", t)
    g <- element_grob(
      e,
      x  = c(0, 0.5, 1, 0.5, 0.15, 0.85, 0.85, 0.15),
      y  = c(0.5, 0, 0.5, 1, 0.15, 0.15, 0.85, 0.85),
      id = c(1, 1, 1, 1, 2, 2, 2, 2),
      colour = c("orange", "limegreen")
    )
    grid.newpage(); grid.draw(g)

两段 `id` 由 `pathGrob()` 按组回收 gpar，所以两条菱形各用各的描边色。
"""

from ggcore.theme import (
    calc_element,
    element_grob,
    element_polygon,
    merge_theme,
    theme,
    theme_gray,
)


def build():
    element = calc_element(
        "polygon", merge_theme(theme_gray(), theme(polygon=element_polygon(fill="orchid")))
    )
    grob = element_grob(
        element,
        x=[0.0, 0.5, 1.0, 0.5, 0.15, 0.85, 0.85, 0.15],
        y=[0.5, 0.0, 0.5, 1.0, 0.15, 0.15, 0.85, 0.85],
        id=[1, 1, 1, 1, 2, 2, 2, 2],
        colour=["orange", "limegreen"],
    )
    return {"grob": grob, "size": [10, 8]}

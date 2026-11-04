"""上游快照复刻：`element_point()` 的 `element_grob()`（裸 grob）。

源：theme/point-elements.svg

R：

    t <- theme_gray() + theme(point = element_point(shape = 21, size = 5))
    e <- calc_element("point", t)
    g <- element_grob(
      e,
      x = seq(0.1, 0.9, length.out = 5),
      y = seq(0.9, 0.1, length.out = 5),
      fill = c("orange", "limegreen", "orchid", "turquoise", "grey")
    )
    grid.newpage(); grid.draw(g)

快照不走 ggplot 管线，所以 `build()` 给的是 `{"grob": …}` 形态。
"""

from ggcore.theme import (
    calc_element,
    element_grob,
    element_point,
    merge_theme,
    theme,
    theme_gray,
)


def build():
    element = calc_element(
        "point", merge_theme(theme_gray(), theme(point=element_point(shape=21, size=5)))
    )
    grob = element_grob(
        element,
        x=[0.1 + 0.2 * index for index in range(5)],
        y=[0.9 - 0.2 * index for index in range(5)],
        fill=["orange", "limegreen", "orchid", "turquoise", "grey"],
    )
    return {"grob": grob, "size": [10, 8]}

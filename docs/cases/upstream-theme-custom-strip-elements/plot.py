"""上游快照复刻：strip 可以渲染自定义元素。

源：theme/custom-strip-elements-can-render.svg

R：

    element_test <- S7::new_class("element_test", element_text)
    S7::method(element_grob, element_test) <-
      function(element, label = "", x = NULL, y = NULL, ...) {
        rectGrob(width = unit(1, "cm"), height = unit(1, "cm"))
      }

    df <- data_frame(x = 1:3, y = 1:3, a = letters[1:3])
    ggplot(df, aes(x, y)) + geom_point() + facet_wrap(~a) +
      theme(strip.text = element_test())

Python 侧同一个扩展点：`ElementText` 的子类覆写 `grob()`，strip 的占位与绘制
都走 `element_grob()`（等价于 R 的 `S7::method(element_grob, …)`）。
"""

from dataclasses import dataclass

from ggcore.grobs import rect_grob
from ggcore.plot import aes, facet_wrap, geom_point, ggplot, labs
from ggcore.theme import ElementText, theme
from ggcore.units import unit
from ggcore.viewport import gpar
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 2, 3], "a": ["a", "b", "c"]}


@dataclass(frozen=True, slots=True)
class ElementTest(ElementText):
    """R 快照里的 `S7::new_class("element_test", element_text)`。"""

    def grob(self, **kwargs):
        return rect_grob(
            kwargs.get("x", 0.5),
            kwargs.get("y", 0.5),
            unit(1.0, "cm"),
            unit(1.0, "cm"),
            default_units=kwargs.get("default_units", "npc"),
            gp=gpar(fill="white", col="black", lwd=1.0),
            name=kwargs.get("name"),
        )


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + facet_wrap(["a"])
        + theme(**{"strip.text": ElementTest()})
        + labs(title="custom strip elements can render")
    )
    return {"plot": p, "size": [10, 8]}

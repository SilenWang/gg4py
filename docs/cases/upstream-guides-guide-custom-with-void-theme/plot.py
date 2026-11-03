from ggcore.grobs import circle_grob
from ggcore.plot import (
    aes,
    geom_blank,
    ggplot,
    guide_custom,
    guides,
    labs,
)
from ggcore.theme import theme_void
from ggcore.viewport import unit
from ggio.frame import to_column_table

EMPTY = {"x": [], "y": []}


def build():
    # 上游是 `ggplot()`（没有图层）；三文件 case 要求至少一层，用 `geom_blank()`
    # 铺一个空数据图层，像素上没有区别（不画任何东西）。
    p = (
        ggplot(to_column_table(EMPTY), aes(x="x", y="y"))
        + geom_blank()
        + guides(custom=guide_custom(circle_grob(r=unit(1, "cm")), title="custom guide"))
    )
    p = p + theme_void() + labs(title="guide_custom with void theme")
    return {"plot": p, "size": [10, 8]}

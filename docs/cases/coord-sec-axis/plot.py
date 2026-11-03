"""coord：次轴 `sec_axis(~ . * 2)` —— 断点 / 标签 / top-right 槽。"""

from ggcore.plot import aes, geom_point, ggplot, scale_y_continuous, sec_axis
from ggcore.theme import element_blank, theme
from ggio.frame import to_column_table

DATA = {
    "cls": ["a", "b", "c", "d", "e"],
    "v": [1.0, 2.5, 1.8, 3.0, 2.2],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="cls", y="v"))
        + geom_point(size=3, colour="#4C78A8")
        + scale_y_continuous(**{"sec.axis": sec_axis(lambda v: v * 2, name="double")})
        + theme(
            **{
                "panel.grid": element_blank(),
                "panel.background": element_blank(),
            }
        )
    )
    return {"plot": p, "size": SIZE}

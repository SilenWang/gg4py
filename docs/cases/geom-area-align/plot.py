"""area：三组 x 不齐（stat_align 在并集上线性插值）+ 堆叠。"""

from ggcore.plot import (
    aes,
    geom_area,
    ggplot,
    position_stack,
    scale_fill_discrete,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [1, 2, 4, 1, 3, 4, 2, 3, 4],
    "y": [1.0, 1.6, 1.2, 0.8, 1.0, 0.6, 0.5, 0.9, 0.7],
    "g": ["a", "a", "a", "b", "b", "b", "c", "c", "c"],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", fill="g"))
        + geom_area(position=position_stack())
        + scale_fill_discrete(values={"a": "#4C78A8", "b": "#F58518", "c": "#54A24B"})
        + scale_x_continuous(limits=(0.5, 4.5), expand=(0, 0))
        + scale_y_continuous(limits=(0, 5), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

"""theme：`theme_test()` 完整主题（与 theme-grey-basic 同一份数据/几何，只换主题）。"""

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_test,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [1.0, 2.0, 3.0, 4.0, 5.0, 1.5, 2.5, 3.5, 4.5, 5.5],
    "y": [2.1, 2.8, 3.2, 3.9, 4.5, 3.4, 4.1, 2.6, 4.8, 3.0],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point(shape=19, size=2.4, colour="#619CFF")
        + scale_x_continuous(limits=(0, 6), expand=(0, 0))
        + scale_y_continuous(limits=(1.5, 5.5), expand=(0, 0))
        + theme_test()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

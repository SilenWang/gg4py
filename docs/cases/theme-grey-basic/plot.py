"""theme：`theme_grey()` 完整主题（灰面板 + 主轴 + 网格）。

**ci = false**：当前渲染器还没有画 `panel.grid.*`（见 matrix 缺口清单的
“theme 网格线”），网格线整片缺失会让图级差异远超 2%。参考图仍然照常生成，
等 M2 把网格线接上后把 `ci` 翻成 true 即可。
"""

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_grey,
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
        + geom_point(shape=19, size=2.4, colour="#F8766D")
        + scale_x_continuous(limits=(0, 6), expand=(0, 0))
        + scale_y_continuous(limits=(1.5, 5.5), expand=(0, 0))
        + theme_grey()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

"""geom_boxplot：横向自动方向探测（不写 orientation，SIL-715 #5）。

y 离散、x 连续时 `has_flipped_aes()` 从列类型推出 `flipped_aes = TRUE`；两侧都没有 `orientation`。
"""

from ggcore.plot import (
    aes,
    geom_boxplot,
    ggplot,
    scale_x_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "cls": ["a"] * 6 + ["b"] * 6,
    "v": [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 0.5, 1.0, 1.5, 2.0, 2.5, 5.0],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(y="cls", x="v"))
        + geom_boxplot(fill="#F58518", colour="#333333", width=0.6)
        + scale_x_continuous(limits=(0, 6), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

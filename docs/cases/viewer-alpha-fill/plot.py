"""SVG 渲染器：连续 alpha 映射到**填充**（`fill-opacity`）——M2-12 的合成口径。

与 `geom-point-alpha`（描边色 alpha）互补：柱子只有 fill，`fill-opacity` 必须
等于「颜色自身的 alpha × gpar.alpha」，不是只取其中一项。
"""

from ggcore.plot import (
    aes,
    geom_col,
    ggplot,
    scale_alpha_continuous,
    scale_x_discrete,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "cls": ["a", "b", "c", "d"],
    "v": [0.40, 0.70, 0.50, 0.90],
    "a": [0.20, 0.40, 0.60, 0.80],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="cls", y="v", alpha="a"))
        + geom_col(fill="#4C78A8", colour=None)
        + scale_alpha_continuous(limits=(0, 1))
        + scale_x_discrete()
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

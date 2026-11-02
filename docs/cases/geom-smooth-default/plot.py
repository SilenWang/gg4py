"""smooth：`geom_smooth()` 的默认口径（loess + se，R 的 interpolate 面）。

R 4.0.3 的 `fill = from_theme(fill %||% col_mix(ink, paper, 0.6))` 在 theme_void 下
落到 **黑色**；gg4py 的静态 default_aes 是 grey60（见评论里的缺口清单），所以这里
两边都显式给 `fill = "black"`，让差异只剩拟合本身。
"""

from ggcore.plot import (
    aes,
    geom_smooth,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
    "y": [0.10, 0.32, 0.28, 0.45, 0.52, 0.48, 0.63, 0.70, 0.66, 0.82, 0.95],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_smooth(fill="black")
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1.1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

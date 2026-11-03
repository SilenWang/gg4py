"""geom_ribbon：outline.type = "upper"。

只画上沿轮廓；`both` / `lower` / `full` 走同一个 `outline.type` 分支。
"""

from ggcore.plot import (
    aes,
    geom_ribbon,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.1, 0.3, 0.5, 0.7, 0.9],
    "lo": [0.1, 0.2, 0.15, 0.3, 0.25],
    "hi": [0.4, 0.5, 0.45, 0.6, 0.55],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", ymin="lo", ymax="hi"))
        + geom_ribbon(
            fill="#4C78A8",
            colour="#333333",
            alpha=0.5,
            linewidth=0.9 / 2.845276,
            **{"outline.type": "upper"},
        )
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

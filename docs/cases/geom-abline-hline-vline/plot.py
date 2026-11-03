"""geom_abline / geom_hline / geom_vline：三种参考线。

参考线的端点来自面板的反变换范围；`coord$clip == "on"` 时 `abline` 先把范围扩一个跨度。
"""

from ggcore.plot import (
    aes,
    geom_abline,
    geom_hline,
    geom_rect,
    geom_vline,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "xmin": [0.1, 0.5],
    "xmax": [0.4, 0.8],
    "ymin": [0.1, 0.2],
    "ymax": [0.5, 0.6],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(
            to_column_table(DATA),
            aes(xmin="xmin", xmax="xmax", ymin="ymin", ymax="ymax"),
        )
        + geom_rect(fill="#DDDDDD", colour="#333333", linewidth=0.6 / 2.845276)
        + geom_abline(slope=1, intercept=0.1, linewidth=1.0 / 2.845276, colour="#4C78A8")
        + geom_hline(yintercept=0.75, linetype="dashed", linewidth=0.9 / 2.845276, colour="#E45756")
        + geom_vline(xintercept=0.6, linewidth=0.9 / 2.845276, colour="#54A24B")
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

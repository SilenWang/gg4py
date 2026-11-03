"""text / rotate：逐行旋转角（0 / 45 / 90）。

参考图由 `refs:geom` 的 `text_rotate` 段生成：`angle` 映射到一列，
IR 的 `text.angle` 是单值，所以绘制层按角度分组（视觉等价）。
"""

from ggcore.plot import (
    aes,
    geom_text,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.3, 0.5, 0.7],
    "y": [0.35, 0.6, 0.65],
    "label": ["a", "b", "c"],
    "ang": [0.0, 45.0, 90.0],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", label="label", angle="ang"))
        + geom_text(size=5)
        + scale_x_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + scale_y_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": [4, 3]}

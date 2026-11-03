"""text / wrap：多行标签（`\\n`）与 lineheight。

参考图由 `refs:geom` 的 `text_wrap` 段生成：两行 / 三行标签，
`geom_text(size = 4.5, lineheight = 1.2)`。
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
    "x": [0.3, 0.7],
    "y": [0.5, 0.5],
    "label": ["first\nsecond", "alpha\nbeta\ngamma"],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", label="label"))
        + geom_text(size=4.5, lineheight=1.2)
        + scale_x_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + scale_y_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": [4, 3]}

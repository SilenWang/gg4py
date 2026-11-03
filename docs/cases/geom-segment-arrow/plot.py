"""geom_segment：两端闭合箭头（IR 0.3 的 arrow 标记）。

箭头是 IR 节点参数（arrow / arrow_length / arrow_angle / arrow_type），
箭翼几何由 skia 与查看器各自按端点切向求值。
"""

from ggcore.plot import (
    aes,
    arrow,
    geom_segment,
    ggplot,
    scale_colour_discrete,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.1, 0.5],
    "y": [0.2, 0.55],
    "xend": [0.8, 0.9],
    "yend": [0.7, 0.25],
    "g": ["a", "b"],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", xend="xend", yend="yend", colour="g"))
        + geom_segment(
            linewidth=1.1 / 2.845276,
            arrow=arrow(length=0.15 * 72.0, ends="both", type="closed"),
        )
        + scale_colour_discrete(values={"a": "#4C78A8", "b": "#E45756"})
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

"""contour_filled：分段色带（与 density2d_filled 同一份 band 数据）。

参考图由 `refs:geom` 的 `contour_filled` 段生成：
`geom_contour_filled(stat = "identity")` + `scale_fill_manual()`。
"""

from ggcore.plot import (
    aes,
    geom_contour_filled,
    ggplot,
    scale_fill_manual,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

OUTER = [[0.15, 0.85, 0.85, 0.15, 0.15], [0.15, 0.15, 0.85, 0.85, 0.15]]
HOLE = [[0.35, 0.65, 0.65, 0.35, 0.35], [0.35, 0.35, 0.65, 0.65, 0.35]]

DATA = {
    "x": OUTER[0] + HOLE[0] + HOLE[0],
    "y": OUTER[1] + HOLE[1] + HOLE[1],
    "level": ["(0.2, 0.4]"] * 10 + ["(0.4, 0.6]"] * 5,
    "grp": ["b1"] * 10 + ["b2"] * 5,
    "subgroup": ["s1"] * 5 + ["s2"] * 5 + ["s1"] * 5,
}

FILLS = {"(0.2, 0.4]": "#A6CEE3", "(0.4, 0.6]": "#1F78B4"}


def build():
    p = (
        ggplot(
            to_column_table(DATA),
            aes(x="x", y="y", fill="level", group="grp", subgroup="subgroup"),
        )
        + geom_contour_filled(stat="identity")
        + scale_fill_manual(values=FILLS)
        + scale_x_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + scale_y_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": [4, 3]}

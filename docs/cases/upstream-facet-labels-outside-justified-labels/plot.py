"""upstream/facet-labels：轴标签的外侧对齐（跨面板统一）。

`facet_grid(f1 ~ f2, scales = "free")` + 四边轴（`guides(x.sec = "axis",
y.sec = "axis")`），`axis.text.*` 的 hjust / vjust 按外侧对齐设置。
"""

from ggcore.plot import aes, facet_grid, geom_point, ggplot, guides, labs
from ggcore.theme import element_text, theme
from ggio.frame import to_column_table

DATA = {
    "x": ["X\nX\nX\nX\nX", "X"],
    "y": ["YYYYY", "Y"],
    "f1": ["A", "B"],
    "f2": ["C", "D"],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + facet_grid(rows="f1", cols="f2", scales="free")
        + guides(x="axis", y="axis", **{"x.sec": "axis", "y.sec": "axis"})
        + theme(
            **{
                "axis.text.y.left": element_text(hjust=0),
                "axis.text.y.right": element_text(hjust=1),
                "axis.text.x.top": element_text(vjust=1),
                "axis.text.x.bottom": element_text(vjust=0),
            }
        )
        + labs(title="outside-justified labels")
    )
    return {"plot": p, "size": [10, 8]}

"""upstream/labels：`labs(tag =)` 的缺省位置（`plot.tag.location = "margin"`）。

上游快照由 vdiffr 生成：标题是快照名（`defaults`），主题是 `theme_test()`。
"""

from ggcore.plot import aes, geom_point, ggplot, labs, theme_test
from ggio.frame import to_column_table

DATA = {"x": list(range(1, 11)), "y": list(range(10, 0, -1))}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + labs(title="defaults", tag="Fig. A)")
        + theme_test()
    )
    return {"plot": p, "size": [10, 8]}

"""上游快照复刻：annotation_borders utah。

源：annotate/annotation-borders-utah.svg（vdiffr 名 "annotation_borders utah"）。

R（4.0 起 `borders()` 是 deprecated 的 `annotation_borders()` 别名）：

    borders("state", "utah")

`maps::map("state", "utah")` 的 59 个点逐点内联在 `ggcore.map_data`
（本仓不装 maps 包），多边形描边 grey50、不填充；主题是 vdiffr 快照里的
`theme_test()`，标题是 doppelganger 名。
"""

from ggcore.plot import annotation_borders, ggplot, labs
from ggcore.theme import theme_test


def build():
    p = (
        ggplot()
        + annotation_borders("state", "utah", fill=None, colour="grey50")
        + labs(title="annotation_borders utah")
        + theme_test()
    )
    return {"plot": p, "size": [10, 8]}

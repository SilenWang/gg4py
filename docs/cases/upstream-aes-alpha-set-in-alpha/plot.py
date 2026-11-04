"""上游快照复刻：Alpha set in alpha（aes/alpha-set-in-alpha.svg）。

源：`test-aes.R` 的 "alpha is drawn correctly"（vdiffr 名 `Alpha set in alpha`）。

R：

    d <- data.frame(x = 1, y = 1)
    ggplot(d, aes(x, y)) + geom_point(color = I("#cc0000"), size = I(50), alpha=0.27)

`I()` 是**恒等**（不经过标度）：颜色原样（含 8 位 hex 的 alpha 通道），
`alpha = I(0.27)` 同样原样写进 gpar。
"""

from ggcore.plot import aes, geom_point, ggplot, labs
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DAT = {"x": [1.0], "y": [1.0]}


def build():
    p = (
        ggplot(to_column_table(DAT), aes(x="x", y="y"))
        + geom_point(colour="#cc0000", size=50, alpha=0.27)
        + theme_test()
        + labs(title="Alpha set in alpha")
    )
    return {"plot": p, "size": [10, 8]}

"""上游快照复刻：Alpha set in colour（aes/alpha-set-in-colour.svg）。

源：`test-aes.R` 的 "alpha is drawn correctly"（vdiffr 名 `Alpha set in colour`）。

R：

    d <- data.frame(x = 1, y = 1)
    ggplot(d, aes(x, y)) + geom_point(color = I("#cc000044"), size = I(50))

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
        + geom_point(colour="#cc000044", size=50)
        + theme_test()
        + labs(title="Alpha set in colour")
    )
    return {"plot": p, "size": [10, 8]}

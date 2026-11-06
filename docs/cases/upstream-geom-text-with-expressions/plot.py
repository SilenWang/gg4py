"""上游快照复刻：geom_text with expressions。

源：geom-text/geom-text-with-expressions.svg。

R：

    df <- data_frame0(x = 1:2, y = 1:2)
    df$exp <- expression(alpha + beta^2, gamma * sqrt(delta))
    ggplot(df, aes(x, y, label = exp)) + geom_text()

标签是 expression 向量；本仓的等价写法是 `geom_text(parse = TRUE)` + plotmath
字符串（`ggcore.plotmath`）。
"""

from ggcore.plot import aes, geom_text, ggplot, labs
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {
    "x": [1.0, 2.0],
    "y": [1.0, 2.0],
    "lab": ["alpha + beta^2", "gamma * sqrt(delta)"],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", label="lab"))
        + geom_text(parse=True)
        + theme_test()
        + labs(title="geom_text with expressions")
    )
    return {"plot": p, "size": [10, 8]}

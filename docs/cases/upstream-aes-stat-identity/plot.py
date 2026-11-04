"""上游快照复刻：stat='identity'（aes/stat-identity.svg）。

源：`test-aes.R` 的 "aesthetics are drawn correctly"（vdiffr 名 `stat='identity'`）。

R：

    dat <- data_frame(xvar = letters[1:3], yvar = 7:9)
    ggplot(dat, aes(x = xvar, y = yvar)) + geom_bar(stat = "identity")
"""

from ggcore.plot import aes, geom_bar, ggplot, labs
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DAT = {"xvar": ["a", "b", "c"], "yvar": [7.0, 8.0, 9.0]}


def build():
    p = (
        ggplot(to_column_table(DAT), aes(x="xvar", y="yvar"))
        + geom_bar(stat="identity")
        + theme_test()
        + labs(title="stat='identity'")
    )
    return {"plot": p, "size": [10, 8]}

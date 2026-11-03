"""上游快照复刻：NA linetype（geom-path/na-linetype.svg）。

源：`test-geom-path.R` 的 "NA linetype is dropped with warning"（vdiffr 名
`NA linetype`）。

R：

    df <- data_frame(x = 1:2, y = 1:2, z = "a")
    ggplot(df, aes(x, y)) + geom_path(linetype = NA)

`linetype = NA` 在体量阶段被丢弃（R 侧同时发 warning），图里只剩坐标轴与面板。
"""

from ggcore.plot import aes, geom_path, ggplot, labs
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DAT = {"x": [1.0, 2.0], "y": [1.0, 2.0], "z": ["a", "a"]}


def build():
    p = (
        ggplot(to_column_table(DAT), aes(x="x", y="y"))
        + geom_path(linetype=float("nan"))
        + theme_test()
        + labs(title="NA linetype")
    )
    return {"plot": p, "size": [10, 8]}

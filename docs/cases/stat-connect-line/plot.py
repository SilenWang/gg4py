"""connect：按 `connection = "hv"` 连接的折线。

参考图由 `pixi run -e refs refs:stat-longtail` 生成（`stat-connect-line` 段）：
三个点之间先水平再垂直地走线，比 `geom_line` 多出两个拐点。
"""

from ggcore.plot import (
    aes,
    geom_line,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 3, 2]}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_line(stat="connect", connection="hv", colour="#4C78A8")
        + scale_x_continuous(limits=(0.5, 3.5), expand=(0, 0))
        + scale_y_continuous(limits=(0.5, 3.5), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

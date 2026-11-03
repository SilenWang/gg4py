"""unique：去掉重复行后的散点。

参考图由 `pixi run -e refs refs:stat-longtail` 生成（`stat-unique-point` 段）。
五条观测里 `(1, 1)` 与 `(2, 3)` 各重复一次，`StatUnique` 只留首次出现的三行。
"""

from ggcore.plot import (
    aes,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    stat_unique,
    theme_void,
)
from ggio.frame import to_column_table

DATA = {"x": [1, 1, 2, 2, 2], "y": [1, 1, 2, 3, 3]}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + stat_unique()
        + scale_x_continuous(limits=(0.5, 2.5), expand=(0, 0))
        + scale_y_continuous(limits=(0.5, 3.5), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

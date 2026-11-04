"""上游快照复刻：`legend.spacing.y = unit(1, "null")`。

源：theme/vertical-legends-placed-apart.svg

R：

    p <- ggplot(df, aes(x, y, colour = a, shape = factor(x))) + geom_point() +
      theme(
        legend.box.background = element_rect(colour = "blue", fill = NA),
        legend.background = element_rect(colour = "red", fill = NA)
      )
    p + theme(legend.position = "right", legend.spacing.y = unit(1, "null"))
"""

import sys
from pathlib import Path

from ggcore.data import ColumnTable
from ggcore.plot import aes, geom_point, ggplot, labs
from ggcore.theme import element_rect, theme
from ggcore.units import unit
from ggio.frame import to_column_table

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _fixtures import factor_column

DATA = {"x": [1, 2, 3], "y": [1, 2, 3], "a": ["a", "b", "c"]}


def build():
    base = to_column_table(DATA)
    # R 的 `shape = factor(x)`：x 轴仍是连续 numeric，只有 shape 走离散标度。
    table = ColumnTable(
        [
            *((name, base.column(name)) for name in base.names),
            ("shape_x", factor_column(DATA["x"], sorted(set(DATA["x"])))),
        ]
    )
    p = (
        ggplot(table, aes(x="x", y="y", colour="a", shape="shape_x"))
        + geom_point()
        + theme(
            **{
                "legend.box.background": element_rect(colour="blue", fill=None),
                "legend.background": element_rect(colour="red", fill=None),
            }
        )
        + theme(
            **{
                "legend.position": "right",
                "legend.spacing.y": unit(1.0, "null"),
            }
        )
        # R 的图例标题取自映射表达式 `factor(x)`；gg4py 的 aes() 不解析表达式，
        # 这里显式给同一个标题。
        + labs(title="vertical legends placed apart", shape="factor(x)")
    )
    return {"plot": p, "size": [10, 8]}

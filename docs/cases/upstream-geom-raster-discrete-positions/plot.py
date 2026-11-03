import numpy as np

from ggcore.data import Column, ColumnTable
from ggcore.plot import (
    aes,
    geom_raster,
    ggplot,
    labs,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

# R: expand.grid(x = c('A', 'B'), y = c('C', 'D'))，fill = interaction(x, y)。
# interaction() 的水平顺序是 x 变化最快，所以等级是 A.C / B.C / A.D / B.D。
_LEVELS = ("A.C", "B.C", "A.D", "B.D")
DATA = ColumnTable(
    [
        ("x", Column("str", np.array(["A", "B", "A", "B"]))),
        ("y", Column("str", np.array(["C", "C", "D", "D"]))),
        ("z", Column("categorical", np.array([0, 1, 2, 3], dtype=np.int32), levels=_LEVELS)),
    ]
)


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", fill="z"))
        + geom_raster()
        + theme_test()
        + labs(title="discrete positions", fill="interaction(x, y)")
    )
    return {"plot": p, "size": [10, 8]}

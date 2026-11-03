from ggcore.plot import (
    aes,
    geom_raster,
    ggplot,
    labs,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

# R: expand.grid(x = 1:10, y = 1:10) —— 第一个变量 x 变化最快。
_X = [value for _ in range(10) for value in range(1, 11)]
_Y = [value for value in range(1, 11) for _ in range(10)]
_COL = []
for _x, _y in zip(_X, _Y, strict=True):
    _value = (_x + _y) % 2
    if (_x == 5 and _value == 1) or (_y == 5 and _value == 0):
        _COL.append(None)
    else:
        _COL.append(str(_value))
DATA = {"x": _X, "y": _Y, "z": _COL}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", fill="z"))
        + geom_raster()
        + theme_test()
        + labs(title="irregular categorical", fill="factor(col)")
    )
    return {"plot": p, "size": [10, 8]}

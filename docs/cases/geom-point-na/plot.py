"""point：NA 行按 `handle_na()` 删除（`non_missing_aes` = size/shape/colour）。"""

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.10, 0.20, None, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90],
    "y": [0.20, 0.45, 0.30, 0.55, None, 0.70, 0.40, 0.80, 0.60],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point(shape=19, size=3.2, colour="#4C78A8")
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

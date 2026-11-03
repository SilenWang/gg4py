"""geom_map：map 表 + map_id（最小可用）。

`map` 是 `{x, y, id}` 三列的映射；与数据的 `map_id` 取交集后按 id 画多边形。
"""

from ggcore.plot import (
    aes,
    geom_map,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {"map_id": ["a", "b"]}

MAP = {
    "x": [0.0, 0.4, 0.4, 0.0, 0.5, 0.9, 0.9, 0.5],
    "y": [0.0, 0.0, 0.4, 0.4, 0.5, 0.5, 0.9, 0.9],
    "id": ["a", "a", "a", "a", "b", "b", "b", "b"],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(map_id="map_id"))
        + geom_map(map=MAP, fill="#4C78A8", colour="#333333", linewidth=0.8 / 2.845276)
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

"""SVG 渲染器：`pch` 0..25 全部 26 个符号（M2-12）。

一行一个符号，7 列 4 行。几何常量与 `ggskia.pch` / `web/viewer/src/render.ts`
同一份（R `engine.c` 的 `RADIUS = 0.375`、`TRC0/1/2`、`SQRC`、`DMDC`）；
`21..25` 是「`fill` 填充 + `col` 描边」，其余是「`col` 不填充 / 填充」两档。

每个符号一层（`shape=` 是标量参数，与 ggplot2 一样不能按行给向量）：R 侧同样
是 26 个 `geom_point(shape = s)`。`aes(shape = ...)` 的标度映射归 M2-7 的点族，
本 case 只守渲染器的符号几何。
"""

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

COLS = [0.08, 0.22, 0.36, 0.50, 0.64, 0.78, 0.92]
ROWS = [0.82, 0.60, 0.38, 0.16]
SHAPES = list(range(26))

DATA = {
    "x": [COLS[index % 7] for index in SHAPES],
    "y": [ROWS[index // 7] for index in SHAPES],
    "sh": SHAPES,
}

SIZE = [4, 3]


def build():
    table = to_column_table(DATA)
    p = ggplot(table, aes(x="x", y="y"))
    for shape in SHAPES:
        keep = [item == shape for item in DATA["sh"]]
        subset = {
            name: [value for value, flag in zip(values, keep, strict=True) if flag]
            for name, values in DATA.items()
        }
        p = p + geom_point(
            data=to_column_table(subset),
            shape=shape,
            size=6.0,
            colour="#1F2937",
            fill="#7FB3D5",
        )
    p = (
        p
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}

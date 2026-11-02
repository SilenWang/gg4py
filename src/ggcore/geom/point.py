"""`geom_point` 的绘制（M1-7）。

照 4.0.3 的 `GeomPoint$draw_panel()`：

```r
data$shape <- translate_shape_string(data$shape)
coords <- coord$transform(data, panel_params)
pointsGrob(coords$x, coords$y, pch = coords$shape,
           gp = gg_par(col = alpha(coords$colour, coords$alpha),
                       fill = fill_alpha(coords$fill, coords$alpha),
                       pointsize = coords$size, stroke = coords$stroke))
```

`gg_par(pointsize = size, stroke = stroke)` 把点大小折成 `fontsize = size * .pt +
stroke * .stroke / 2`（pt）；`pointsGrob` 的缺省 `size = unit(1, "char")` 就是
这个字号。IR 的 `points.size` 是**一个**标量，所以逐点尺寸按 `(pch, size)` 分组
画成多个 `pointsGrob`——视觉结果与 grid 的逐元素绘制一致。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from ggcore.geom.base import (
    POINT_PER_MM,
    STROKE_PER_MM,
    GeomError,
    GeomRenderer,
    alpha_colour,
    npc_values,
    table_numeric,
)
from ggcore.grobs import g_tree, null_grob, points_grob
from ggcore.units import unit
from ggcore.viewport import NA

__all__ = ["PointRenderer", "translate_shape"]

#: `translate_shape_string()` 的符号名表（照抄 4.0.3）。
SHAPE_NAMES: dict[str, int] = {
    "square open": 0,
    "circle open": 1,
    "triangle open": 2,
    "plus": 3,
    "cross": 4,
    "diamond open": 5,
    "triangle down open": 6,
    "square cross": 7,
    "asterisk": 8,
    "diamond plus": 9,
    "circle plus": 10,
    "star": 11,
    "square plus": 12,
    "circle cross": 13,
    "square triangle": 14,
    "triangle square": 14,
    "square": 15,
    "circle small": 16,
    "triangle": 17,
    "diamond": 18,
    "circle": 19,
    "bullet": 20,
    "circle filled": 21,
    "square filled": 22,
    "diamond filled": 23,
    "triangle filled": 24,
    "triangle down filled": 25,
}


def translate_shape(value: Any) -> int:
    """`translate_shape_string()`：数字原样，名字按表查（单字符当字符型 pch）。"""
    if isinstance(value, (bool, np.bool_)):
        raise GeomError(f"shape 不能是布尔值：{value!r}")
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if not math.isfinite(number):
            raise GeomError("shape 含缺失值（先经 handle_na 删除，或给 `na_rm=True`）")
        return int(number)
    if isinstance(value, str):
        if len(value) <= 1:
            return ord(value) if value else 1
        if value not in SHAPE_NAMES:
            raise GeomError(f"shape 不认识 {value!r}（见 docs/notes/geom.md 的符号名表）")
        return SHAPE_NAMES[value]
    raise GeomError(f"shape 只能是数字或符号名，收到 {type(value).__name__}")


class PointRenderer(GeomRenderer):
    """`geom_point`：逐点符号 + 分组后的 colour / fill / alpha / stroke。"""

    name = "point"
    non_missing_aes = ("size", "shape", "colour")

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        data = build.data
        if data.nrows == 0:
            return null_grob(name="geom_point")
        x = npc_values(panel, data, "x", "x")
        y = npc_values(panel, data, "y", "y")
        shapes = np.array([translate_shape(item) for item in _shape_values(data)], dtype=np.int64)
        size = table_numeric(data, "size", default=1.5)
        stroke = table_numeric(data, "stroke", default=0.5)
        alpha = table_numeric(data, "alpha", default=math.nan)
        colours = np.array(_colour_values(data, "colour", "black"), dtype=object)
        fills = np.array(_colour_values(data, "fill", None), dtype=object)
        size_pt = size * POINT_PER_MM + stroke * STROKE_PER_MM / 2.0
        lwd = stroke * STROKE_PER_MM / 2.0

        grobs: list[Any] = []
        for pch, points_size in _symbol_groups(shapes, size_pt):
            index = (shapes == pch) & (np.round(size_pt, 9) == points_size)
            grobs.append(
                points_grob(
                    unit(x[index].tolist(), "native"),
                    unit(y[index].tolist(), "native"),
                    pch=int(pch),
                    size=unit(points_size, "bigpts"),
                    size_units="bigpts",
                    default_units="native",
                    gp={
                        "col": [
                            alpha_colour(item, a)
                            for item, a in zip(colours[index], alpha[index], strict=True)
                        ],
                        "fill": [
                            alpha_colour(item, a)
                            for item, a in zip(fills[index], alpha[index], strict=True)
                        ],
                        "lwd": lwd[index].tolist(),
                    },
                )
            )
        if len(grobs) == 1:
            return grobs[0]
        return g_tree(*grobs, name="geom_point")


def _shape_values(data: Any) -> list[Any]:
    """shape 列 → 逐行原值；字符串列直接给名字。"""
    if "shape" not in data:
        return [19] * data.nrows
    column = data.column("shape")
    values = column.values.tolist()
    mask = np.asarray(column.na_mask, dtype=bool).tolist()
    return [19 if missing else value for value, missing in zip(values, mask, strict=True)]


def _colour_values(data: Any, name: str, default: Any) -> list[Any]:
    if name not in data:
        return [default] * data.nrows
    column = data.column(name)
    values = column.values.tolist()
    mask = np.asarray(column.na_mask, dtype=bool).tolist()
    return [NA if missing else value for value, missing in zip(values, mask, strict=True)]


def _symbol_groups(shapes: np.ndarray, sizes: np.ndarray) -> list[tuple[int, float]]:
    """唯一 `(pch, size)` 组合，保持首次出现顺序（确定性）。"""
    seen: dict[tuple[int, float], None] = {}
    for pch, size in zip(shapes.tolist(), np.round(sizes, 9).tolist(), strict=True):
        seen.setdefault((int(pch), float(size)), None)
    return list(seen)

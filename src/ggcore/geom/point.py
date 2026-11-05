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
import warnings
from typing import Any

import numpy as np

from ggcore.geom.base import (
    POINT_PER_MM,
    STROKE_PER_MM,
    GeomError,
    GeomRenderer,
    alpha_colour,
    fill_values,
    npc_values,
    table_numeric,
)
from ggcore.grobs import g_tree, null_grob, points_grob
from ggcore.perf import DownsampleWarning, resolve_max_points, sample_rows
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
        # M3-5：显式降采样预算（`geom_point(max_points=…)`）。缺省不降，见
        # `ggcore.perf` 模块头与 `docs/notes/performance.md`。
        budget = resolve_max_points(build.params.get("max_points"))
        if budget is not None:
            sampled = sample_rows(data, budget)
            if sampled is not None:
                warnings.warn(
                    f"geom_point(): {data.nrows} 行超过 max_points={budget}，"
                    "按行号等距降采样（画出来的点数比数据少）",
                    DownsampleWarning,
                    stacklevel=2,
                )
                data = sampled
        x = npc_values(panel, data, "x", "x")
        y = npc_values(panel, data, "y", "y")
        shapes = _shape_codes(data)
        size = table_numeric(data, "size", default=1.5)
        stroke = table_numeric(data, "stroke", default=0.5)
        alpha = table_numeric(data, "alpha", default=math.nan)
        colours = _colour_values(data, "colour", "black")
        fills = fill_values(data, build.params, None)
        size_pt = size * POINT_PER_MM + stroke * STROKE_PER_MM / 2.0
        lwd = stroke * STROKE_PER_MM / 2.0
        # alpha 全是 NA（缺省）时 `alpha_colour()` 原样返回颜色，整列可以直接给
        # gp，不必逐点调一次 Python 函数。
        plain_alpha = bool(np.all(np.isnan(alpha)))

        grobs: list[Any] = []
        for pch, points_size in _symbol_groups(shapes, size_pt):
            index = (shapes == pch) & (np.round(size_pt, 9) == points_size)
            group = np.flatnonzero(index)
            a = None if plain_alpha else alpha[index]
            grobs.append(
                points_grob(
                    unit(x[index], "native"),
                    unit(y[index], "native"),
                    pch=int(pch),
                    size=unit(points_size, "bigpts"),
                    size_units="bigpts",
                    default_units="native",
                    gp={
                        "col": _group_colour(colours, group, a),
                        "fill": _group_colour(fills, group, a),
                        "lwd": _group_scalar(lwd, group),
                    },
                )
            )
        if len(grobs) == 1:
            return grobs[0]
        return g_tree(*grobs, name="geom_point")


def _group_colour(values: Any, group: np.ndarray, alpha: np.ndarray | None) -> Any:
    """一组的颜色（`col` / `fill`）：整组同值时给标量，否则给逐点列表。

    `alpha` 非空时按 `ggplot2:::alpha()` 折进颜色（`#RRGGBBAA`）。整组同值走标量
    是热路径的关键：10 万点的默认配色只有 "black" 一个值，
    逐点建字符串列表再让 `_gpar_deltas()` 分组是纯浪费。
    """
    if isinstance(values, str) or not isinstance(values, (list, tuple)):
        if alpha is None:
            return values
        if alpha.size == 1:
            return alpha_colour(values, alpha[0])
        return [alpha_colour(values, item) for item in alpha]
    picked = [values[position] for position in group]
    if alpha is not None:
        picked = [alpha_colour(item, a) for item, a in zip(picked, alpha.tolist(), strict=True)]
    if picked and all(isinstance(item, str) for item in picked) and _all_same(picked):
        return picked[0]
    return picked


def _group_scalar(values: np.ndarray, group: np.ndarray) -> float | list[float]:
    picked = values[group]
    if picked.size == 0:
        return 0.0
    first = float(picked[0])
    if picked.size == 1 or bool(np.all(picked == picked[0])):
        return first
    return picked.tolist()


def _shape_codes(data: Any) -> np.ndarray:
    """shape 列 → 逐行 pch（`translate_shape()` 的向量版）。

    数值列整列直接转；字符串列按唯一值查表（`geom_point(shape="circle")` 是一列
    同一个名字，逐点查表是白费的）。
    """
    if "shape" not in data:
        return np.full(data.nrows, 19, dtype=np.int64)
    column = data.column("shape")
    values = column.values
    mask = np.asarray(column.na_mask, dtype=bool)
    if getattr(values, "dtype", None) is not None and values.dtype.kind in "iuf":
        codes = np.asarray(values, dtype=np.float64)
        if np.any(~np.isfinite(codes) & ~mask):
            raise GeomError("shape 含缺失值（先经 handle_na 删除，或给 `na_rm=True`）")
        out = np.where(mask, 19, codes).astype(np.int64)
        return out
    lookup: dict[Any, int] = {}
    raw = values.tolist() if hasattr(values, "tolist") else list(values)
    out = np.empty(data.nrows, dtype=np.int64)
    for position, (value, missing) in enumerate(zip(raw, mask.tolist(), strict=True)):
        if missing:
            out[position] = 19
            continue
        code = lookup.get(value)
        if code is None:
            code = translate_shape(value)
            lookup[value] = code
        out[position] = code
    return out


def _colour_values(data: Any, name: str, default: Any) -> Any:
    """逐行颜色：整列同值（没有该列 / 只有一种颜色）时给标量，否则给逐行列表。"""
    if name not in data:
        return default
    column = data.column(name)
    values = column.values.tolist() if hasattr(column.values, "tolist") else list(column.values)
    mask = np.asarray(column.na_mask, dtype=bool).tolist()
    if any(mask):
        return [NA if missing else value for value, missing in zip(values, mask, strict=True)]
    if _all_same(values):
        return values[0]
    return values


def _all_same(values: list[Any]) -> bool:
    if not values:
        return True
    try:
        return len(set(values)) == 1
    except TypeError:  # pragma: no cover - 不可哈希的取值（渐变规格之类）
        first = values[0]
        return all(item is first or item == first for item in values[1:])


def _symbol_groups(shapes: np.ndarray, sizes: np.ndarray) -> list[tuple[int, float]]:
    """唯一 `(pch, size)` 组合，保持首次出现顺序（确定性）。

    整列同组（10 万点散点图的常态）不摊开比较：先试首元素，命中就只返回一组。
    """
    if shapes.size == 0:
        return []
    rounded = np.round(sizes, 9)
    first = (int(shapes[0]), float(rounded[0]))
    if bool(np.all(shapes == shapes[0])) and bool(np.all(rounded == rounded[0])):
        return [first]
    seen: dict[tuple[int, float], None] = {}
    for pch, size in zip(shapes.tolist(), rounded.tolist(), strict=True):
        seen.setdefault((int(pch), float(size)), None)
    return list(seen)

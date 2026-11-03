"""标注族（M2-S2）：`geom_blank` / `geom_rug` / `geom_map` 的绘制。

照 4.0.3：

- `GeomBlank$draw_panel()`：`nullGrob()`——只参与标度 / 布局，不画。
- `GeomRug$draw_panel()`：按 `sides`（`t` / `b` / `l` / `r` 的组合）在面板四边画
  短刻度线；`length` 缺省 `unit(0.03, "npc")`，`outside = TRUE` 时伸到面板外。
  `coord_flip` 会把 `sides` 的字母对换（`chartr("tblr", "rlbt", sides)`）。
- `GeomMap$draw_panel()`：`map` 与数据的 `map_id` 取交集，`coord_munch(...,
  is_closed = TRUE)` 后按 `id` 画多边形，gp 取对应数据行的 colour / fill / …。

`geom_map` 只做最小可用（不引入地图数据、不做 projection）：`map` 接受
`ColumnTable` 或 `{列名: 数组}`，必须有 `x` / `y` / `id`（可带 `group`）。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from ggcore.data import Column, ColumnTable
from ggcore.geom.base import (
    POINT_PER_MM,
    GeomError,
    GeomRenderer,
    alpha_colour,
    lty_value,
    munch_xy,
    npc_values,
    table_numeric,
    table_values,
)
from ggcore.grobs import g_tree, null_grob, polygon_grob, segments_grob
from ggcore.units import Unit, unit
from ggcore.viewport import NA, gpar

__all__ = ["BlankRenderer", "MapRenderer", "RugRenderer"]


class BlankRenderer(GeomRenderer):
    """`geom_blank`：`nullGrob()`（数据只用来训练标度）。"""

    name = "blank"

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        return null_grob(name="geom_blank")


class RugRenderer(GeomRenderer):
    """`geom_rug`：面板边上的短刻度线。"""

    name = "rug"

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        data = build.data
        if data.nrows == 0:
            return null_grob(name="geom_rug")
        params = build.params
        sides = str(params.get("sides", "bl"))
        if getattr(panel, "flipped", False):
            sides = sides.translate(str.maketrans("tblr", "rlbt"))
        outside = bool(params.get("outside", False))
        length = _rug_length(params.get("length", 0.03))
        near = -length if outside else length
        far = 1.0 + length if outside else 1.0 - length
        gp = {
            "col": [
                alpha_colour(item, value)
                for item, value in zip(
                    table_values(data, "colour", "black"),
                    table_numeric(data, "alpha", default=math.nan),
                    strict=True,
                )
            ],
            "lwd": (table_numeric(data, "linewidth", default=0.5) * POINT_PER_MM).tolist(),
            "lty": lty_value(table_values(data, "linetype", 1)[0]),
            "lineend": str(params.get("lineend", "butt")),
        }
        grobs: list[Any] = []
        if "x" in data:
            x = npc_values(panel, data, "x", "x")
            if "b" in sides:
                grobs.append(_rug_segments(x, np.zeros_like(x), x, np.full_like(x, near), gp))
            if "t" in sides:
                grobs.append(_rug_segments(x, np.ones_like(x), x, np.full_like(x, far), gp))
        if "y" in data:
            y = npc_values(panel, data, "y", "y")
            if "l" in sides:
                grobs.append(_rug_segments(np.zeros_like(y), y, np.full_like(y, near), y, gp))
            if "r" in sides:
                grobs.append(_rug_segments(np.ones_like(y), y, np.full_like(y, far), y, gp))
        if not grobs:
            return null_grob(name="geom_rug")
        if len(grobs) == 1:
            return grobs[0]
        return g_tree(*grobs, name="geom_rug")


def _rug_length(value: Any) -> float:
    """`length` → npc。数值按 npc 解释，`Unit` 只接受简单 `npc` 单位。"""
    if isinstance(value, Unit):
        elements = value.elements
        if len(elements) != 1 or elements[0].kind != "npc":
            raise GeomError(f"geom_rug(length=...) 只支持 npc 单位，收到 {value!r}")
        return float(elements[0].amount)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GeomError(f"geom_rug(length=...) 必须是 npc 数值或单位，收到 {value!r}")
    return float(value)


def _rug_segments(
    x0: np.ndarray, y0: np.ndarray, x1: np.ndarray, y1: np.ndarray, gp: Mapping[str, Any]
) -> Any:
    return segments_grob(
        unit(x0.tolist(), "npc"),
        unit(y0.tolist(), "npc"),
        unit(x1.tolist(), "npc"),
        unit(y1.tolist(), "npc"),
        default_units="npc",
        name="geom_rug",
        gp=gp,
    )


class MapRenderer(GeomRenderer):
    """`geom_map`：`map`（x / y / id）+ 数据的 `map_id` → 多边形。"""

    name = "map"

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        data = build.data
        if data.nrows == 0:
            return null_grob(name="geom_map")
        map_table = _map_table(build.params.get("map"))
        if "map_id" not in data:
            raise GeomError("geom_map 需要 map_id 美学（与 map 的 id 列对应）")
        if "x" not in map_table or "y" not in map_table or "id" not in map_table:
            raise GeomError("geom_map 的 map 必须有 x / y / id 三列")
        ids = table_values(data, "map_id", None)
        keep = np.array([item is not None for item in ids], dtype=bool)
        if not bool(keep.any()):
            return null_grob(name="geom_map")
        data = _slice(data, keep)
        ids = [item for item, flag in zip(ids, keep.tolist(), strict=True) if flag]
        map_ids = [str(item) for item in map_table.column("id").values.tolist()]
        common = [str(item) for item in ids]
        fills = table_values(data, "fill", "grey20")
        colours = table_values(data, "colour", NA)
        alpha = table_numeric(data, "alpha", default=math.nan)
        linewidth = table_numeric(data, "linewidth", default=0.5)
        linetype = table_values(data, "linetype", 1)
        lineend = str(build.params.get("lineend", "butt"))
        linejoin = str(build.params.get("linejoin", "round"))
        linemitre = float(build.params.get("linemitre", 10.0))
        x = table_numeric(map_table, "x", default=float("nan"))
        y = table_numeric(map_table, "y", default=float("nan"))
        grobs: list[Any] = []
        seen: dict[str, int] = {}
        for index, identifier in enumerate(map_ids):
            seen.setdefault(identifier, index)
        for key in list(seen):
            rows = np.array([item == key for item in map_ids], dtype=bool)
            match = next((position for position, item in enumerate(common) if item == key), None)
            if match is None:
                continue
            px, py, group_ids = munch_xy(
                panel, x[rows], y[rows], [0.0] * int(rows.sum()), closed=True
            )
            grobs.append(
                polygon_grob(
                    unit(px.tolist(), "native"),
                    unit(py.tolist(), "native"),
                    id=group_ids,
                    default_units="native",
                    name="geom_map",
                    gp=gpar(
                        col=alpha_colour(colours[match], alpha[match]),
                        fill=alpha_colour(fills[match], alpha[match]),
                        lwd=float(linewidth[match]) * POINT_PER_MM,
                        lty=lty_value(linetype[match]),
                        lineend=lineend,
                        linejoin=linejoin,
                        linemitre=linemitre,
                    ),
                )
            )
        if not grobs:
            return null_grob(name="geom_map")
        if len(grobs) == 1:
            return grobs[0]
        return g_tree(*grobs, name="geom_map")


def _slice(table: ColumnTable, keep: np.ndarray) -> ColumnTable:
    from ggcore.geom.base import row_slice

    return row_slice(table, keep)


def _map_table(value: Any) -> ColumnTable:
    """`map` 参数 → `ColumnTable`（接受 `ColumnTable` 或 `{列名: 数组}`）。"""
    if value is None:
        raise GeomError("geom_map 需要 map=...（x / y / id 三列）")
    if isinstance(value, ColumnTable):
        return value
    if not isinstance(value, Mapping):
        raise GeomError(f"geom_map 的 map 必须是 ColumnTable 或映射，收到 {type(value).__name__}")
    columns: list[tuple[str, Column]] = []
    nrows = 0
    for name, values in value.items():
        if isinstance(values, np.ndarray):
            items = values.tolist()
        elif isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
            items = list(values)
        else:
            raise GeomError(
                f"geom_map 的 map[{name!r}] 必须是一维数组，收到 {type(values).__name__}"
            )
        nrows = max(nrows, len(items))
        mask = np.array([item is None for item in items], dtype=bool)
        if items and all(
            isinstance(item, (int, float)) and not isinstance(item, bool) for item in items
        ):
            data = np.array([np.nan if item is None else float(item) for item in items])
            columns.append((name, Column("float", data, na_mask=mask)))
        elif items and all(isinstance(item, (bool, np.bool_)) for item in items):
            columns.append(
                (
                    name,
                    Column(
                        "bool",
                        np.array([False if item is None else bool(item) for item in items]),
                        na_mask=mask,
                    ),
                )
            )
        else:
            columns.append(
                (
                    name,
                    Column(
                        "str",
                        np.array(
                            ["" if item is None else str(item) for item in items], dtype=object
                        ),
                        na_mask=mask,
                    ),
                )
            )
    return ColumnTable(columns, nrows=nrows)

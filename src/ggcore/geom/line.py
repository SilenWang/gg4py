"""`geom_line` / `geom_path` 的绘制（M1-7）。

照 4.0.3 的 `GeomPath$draw_panel()`：

- 行的顺序由 `setup_data()` 决定（`line` 按 `(PANEL, group, x)` 排序，`path` 保持
  给定顺序）；分组用 `group`；
- 每个 group 一条 `polylineGrob`，gp 取该组第一行的 colour / linewidth /
  linetype / alpha；
- `handle_na()` 用 `keep_mid_true()`：组内**首尾**的缺失行删掉，中间的缺失行
  留着——它把折线断成两段（grid 的 `NA` 断线语义），不把两个端点连起来；
- `arrow` 没有 IR 表达 → 明确报错并点名后续任务。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from ggcore.data import Column, ColumnTable
from ggcore.geom.base import (
    POINT_PER_MM,
    GeomError,
    GeomRenderer,
    alpha_colour,
    flip_data,
    npc_values,
    row_slice,
    table_numeric,
)
from ggcore.grobs import g_tree, null_grob, polyline_grob
from ggcore.units import unit
from ggcore.viewport import NA, gpar

__all__ = ["LineRenderer", "PathRenderer"]


def _keep_mid_true(complete: np.ndarray) -> np.ndarray:
    """`keep_mid_true()`：首个 TRUE 到最后一个 TRUE 之间全保留。"""
    if not bool(complete.any()):
        return np.zeros(complete.size, dtype=bool)
    first = int(np.argmax(complete))
    last = int(complete.size - np.argmax(complete[::-1]))
    keep = np.zeros(complete.size, dtype=bool)
    keep[first:last] = True
    return keep


class PathRenderer(GeomRenderer):
    """`geom_path`：按给定顺序连接（同一 group 一条折线）。"""

    name = "path"
    non_missing_aes = ("linewidth", "colour", "linetype")

    def handle_na(self, geom: Any, data: Any, na_rm: bool) -> Any:
        """按 `(group, PANEL)` 做 `keep_mid_true`（中间 NA 留作断点）。"""
        variables = [name for name in self.na_aesthetics(geom) if name in data]
        if not variables or data.nrows == 0:
            return data
        complete = np.ones(data.nrows, dtype=bool)
        for name in variables:
            complete &= ~np.asarray(data.column(name).na_mask, dtype=bool)
        groups = _group_key(data)
        keep = np.zeros(data.nrows, dtype=bool)
        for key in _keys(groups):
            rows = np.flatnonzero(groups == key)
            keep[rows] = _keep_mid_true(complete[rows])
        if bool(keep.all()):
            return data
        if not na_rm:
            import warnings

            from ggcore.build import BuildWarning

            count = int((~keep).sum())
            noun = "row" if count == 1 else "rows"
            warnings.warn(
                f"Removed {count} {noun} containing missing values or values outside "
                f"the scale range (`geom_{geom.name}()`).",
                BuildWarning,
                stacklevel=4,
            )
        return row_slice(data, keep)

    def setup_data(self, data: Any, params: Any) -> Any:
        return flip_data(data, bool(params.get("flipped_aes", False)))

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        if build.params.get("arrow") is not None:
            raise GeomError(
                f"geom_{self.name}(arrow = ...) 无法表达：IR 的 polyline/segments 没有箭头字段"
                "（见 docs/notes/geom.md「未实现清单」，箭头留给 IR schema 扩展）"
            )
        data = build.data
        if data.nrows == 0:
            return null_grob(name=f"geom_{self.name}")
        flipped = (
            bool(np.any(np.asarray(data.column("flipped_aes").values)))
            if ("flipped_aes" in data)
            else False
        )
        data = flip_data(data, flipped)
        x = npc_values(panel, data, "x", "x")
        y = npc_values(panel, data, "y", "y")
        groups = _group_key(data)
        colours = _values(data, "colour", "black")
        linewidth = table_numeric(data, "linewidth", default=0.5)
        linetype = _values(data, "linetype", 1)
        alpha = table_numeric(data, "alpha", default=math.nan)
        lineend = str(build.params.get("lineend", "butt"))
        linejoin = str(build.params.get("linejoin", "round"))
        linemitre = float(build.params.get("linemitre", 10.0))

        grobs: list[Any] = []
        for key in _keys(groups):
            rows = np.flatnonzero(groups == key)
            if rows.size < 2:
                continue
            xs, ys, ids = _break_at_na(x[rows], y[rows])
            if xs.size < 2:
                continue
            first = rows[0]
            grobs.append(
                polyline_grob(
                    unit(xs.tolist(), "native"),
                    unit(ys.tolist(), "native"),
                    id=ids,
                    default_units="native",
                    gp=gpar(
                        col=alpha_colour(colours[first], alpha[first]),
                        lwd=float(linewidth[first]) * POINT_PER_MM,
                        lty=int(linetype[first])
                        if not isinstance(linetype[first], str)
                        else linetype[first],
                        lineend=lineend,
                        linejoin=linejoin,
                        linemitre=linemitre,
                    ),
                )
            )
        if not grobs:
            return null_grob(name=f"geom_{self.name}")
        if len(grobs) == 1:
            return grobs[0]
        return g_tree(*grobs, name=f"geom_{self.name}")


class LineRenderer(PathRenderer):
    """`geom_line`：`setup_data()` 加 `flipped_aes`，按 `(PANEL, group, x)` 排序。"""

    name = "line"

    def setup_data(self, data: Any, params: Any) -> Any:
        flipped = bool(params.get("flipped_aes", False))
        columns: list[tuple[str, Any]] = [(name, data.column(name)) for name in data.names]
        if "flipped_aes" not in data:
            columns.append(
                ("flipped_aes", Column("bool", np.full(data.nrows, flipped, dtype=bool)))
            )
        frame = flip_data(ColumnTable(columns, nrows=data.nrows), flipped)
        if frame.nrows:
            keys = []
            if "PANEL" in frame:
                keys.append(_numeric_panel(frame))
            if "group" in frame:
                keys.append(table_numeric(frame, "group", default=0.0))
            if "x" in frame:
                keys.append(table_numeric(frame, "x", default=0.0))
            if keys:
                order = np.lexsort(tuple(reversed(keys)))
                frame = row_slice(frame, order)
        return flip_data(frame, flipped)


def _numeric_panel(frame: Any) -> np.ndarray:
    """`PANEL` 按面板编号排序（R 的 factor levels，不是字符串序）。"""
    try:
        return np.asarray(frame.column("PANEL").values, dtype=np.float64)
    except (TypeError, ValueError):
        return np.asarray(frame.column("PANEL").values)


def _break_at_na(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, list[int]]:
    """NA 断线：连续非 NA 段各占一个 id（grid 的 `NA` 断线语义）。"""
    finite = np.isfinite(x) & np.isfinite(y)
    if bool(finite.all()):
        return x, y, [1] * int(x.size)
    ids: list[int] = []
    running = 0
    previous = False
    for value in finite.tolist():
        if value and not previous:
            running += 1
        ids.append(running if value else 0)
        previous = value
    keep = finite
    return x[keep], y[keep], [int(item) for item in np.asarray(ids)[keep].tolist()]


def _group_key(data: Any) -> np.ndarray:
    """分组键：`group` 列（0 起比较），没有就整表一组。"""
    if "group" in data:
        values = np.asarray(data.column("group").values, dtype=np.float64)
        mask = np.asarray(data.column("group").na_mask, dtype=bool)
        return np.where(mask, -1.0, values)
    return np.zeros(data.nrows, dtype=np.float64)


def _keys(groups: np.ndarray) -> list[float]:
    seen: dict[float, None] = {}
    for value in groups.tolist():
        seen.setdefault(float(value), None)
    return list(seen)


def _values(data: Any, name: str, default: Any) -> list[Any]:
    if name not in data:
        return [default] * data.nrows
    column = data.column(name)
    values = column.values.tolist()
    mask = np.asarray(column.na_mask, dtype=bool).tolist()
    return [NA if missing else value for value, missing in zip(values, mask, strict=True)]

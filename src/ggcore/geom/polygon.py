"""多边形族（M2-S2）：`geom_polygon` / `geom_ribbon` / `geom_step` 的绘制。

照 4.0.3：

- `GeomPolygon$draw_panel()`：`coord_munch(..., is_closed = TRUE)` 后按 `group`
  排序；没有 `subgroup` 时一个 `polygonGrob(id = group)`，有 `subgroup` 时
  `pathGrob(id = subgroup, pathId = group, rule = rule)`（带洞的填充）。gp 取每组
  第一行；`fill` 吃 alpha、`col` 不吃。
- `GeomRibbon$setup_data()`：`y = ymin %||% ymax`，按 `(PANEL, group, x)` 排序；
  `draw_group()` 把上沿（正向）与下沿（反向）拼成一个多边形，再按
  `outline.type` 画轮廓：`both` / `upper` / `lower` / `full`（`full` 是多边形自带
  的闭合描边）。沿 ribbon 变化的美学（colour / linewidth / linetype）报错。
- `GeomStep$draw_panel()`：`stairstep()` 逐 group 把数据展开成阶梯折线，再交给
  `GeomPath`；`direction` 是 `hv` / `vh` / `mid`，横向（`flipped_aes`）时
  `hv` ↔ `vh` 互换。
"""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

import numpy as np

from ggcore.build import BuildWarning
from ggcore.data import Column, ColumnTable
from ggcore.geom.base import (
    POINT_PER_MM,
    GeomError,
    GeomRenderer,
    alpha_colour,
    flip_data,
    lty_value,
    munch_xy,
    put_column,
    row_slice,
    table_numeric,
    table_values,
)
from ggcore.geom.line import PathRenderer
from ggcore.grobs import g_tree, null_grob, path_grob, polygon_grob, polyline_grob
from ggcore.units import unit
from ggcore.viewport import NA, gpar

__all__ = ["PolygonRenderer", "RibbonRenderer", "StepRenderer"]


def _group_values(data: Any) -> np.ndarray:
    if "group" in data:
        return np.asarray(data.column("group").values, dtype=np.float64)
    return np.zeros(data.nrows, dtype=np.float64)


def _keys(values: np.ndarray) -> list[float]:
    seen: dict[float, None] = {}
    for value in values.tolist():
        seen.setdefault(float(value), None)
    return list(seen)


def _is_flipped(data: Any) -> bool:
    if "flipped_aes" not in data:
        return False
    return bool(np.any(np.asarray(data.column("flipped_aes").values, dtype=bool)))


class PolygonRenderer(GeomRenderer):
    """`geom_polygon`：每组一个闭合多边形（`subgroup` 用 path + 填充规则）。"""

    name = "polygon"

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        data = build.data
        if data.nrows == 0:
            return null_grob(name="geom_polygon")
        if data.nrows == 1:
            return null_grob(name="geom_polygon")  # R: zeroGrob()
        params = build.params
        rule = str(params.get("rule", "evenodd"))
        lineend = str(params.get("lineend", "butt"))
        linejoin = str(params.get("linejoin", "round"))
        linemitre = float(params.get("linemitre", 10.0))
        fills = table_values(data, "fill", "grey20")
        colours = table_values(data, "colour", NA)
        alpha = table_numeric(data, "alpha", default=math.nan)
        linewidth = table_numeric(data, "linewidth", default=0.5)
        linetype = table_values(data, "linetype", 1)
        groups = _group_values(data)
        subgroups = (
            np.asarray(data.column("subgroup").values, dtype=np.float64)
            if "subgroup" in data
            else None
        )
        x = table_numeric(data, "x", default=float("nan"))
        y = table_numeric(data, "y", default=float("nan"))

        grobs: list[Any] = []
        for key in _keys(groups):
            rows = np.flatnonzero(groups == key)
            if rows.size < 2:
                continue
            first = int(rows[0])
            gp = gpar(
                col=alpha_colour(colours[first], alpha[first]),
                fill=alpha_colour(fills[first], alpha[first]),
                lwd=float(linewidth[first]) * POINT_PER_MM,
                lty=lty_value(linetype[first]),
                lineend=lineend,
                linejoin=linejoin,
                linemitre=linemitre,
            )
            if subgroups is None:
                px, py, ids = munch_xy(
                    panel,
                    x[rows],
                    y[rows],
                    [0.0] * rows.size,
                    closed=True,
                )
                grobs.append(
                    polygon_grob(
                        unit(px.tolist(), "native"),
                        unit(py.tolist(), "native"),
                        id=ids,
                        default_units="native",
                        name="geom_polygon",
                        gp=gp,
                    )
                )
            else:
                order = np.lexsort((subgroups[rows],))
                rows = rows[order]
                codes = _codes(subgroups[rows])
                px, py, _ids = munch_xy(
                    panel,
                    x[rows],
                    y[rows],
                    subgroups[rows].tolist(),
                    closed=True,
                )
                grobs.append(
                    path_grob(
                        unit(px.tolist(), "native"),
                        unit(py.tolist(), "native"),
                        id=codes,
                        rule=rule,
                        default_units="native",
                        name="geom_polygon",
                        gp=gp,
                    )
                )
        if not grobs:
            return null_grob(name="geom_polygon")
        if len(grobs) == 1:
            return grobs[0]
        return g_tree(*grobs, name="geom_polygon")


def _codes(values: np.ndarray) -> list[int]:
    """`match(subgroup, unique(subgroup))`：子路径编号从 1 开始、按首次出现排。"""
    seen: dict[float, int] = {}
    for value in values.tolist():
        seen.setdefault(float(value), len(seen) + 1)
    return [seen[float(value)] for value in values.tolist()]


class RibbonRenderer(GeomRenderer):
    """`geom_ribbon`：`ymin..ymax` 的带 + `outline.type` 轮廓。"""

    name = "ribbon"
    detect_flipped = True
    range_is_orthogonal = True

    # -- setup ------------------------------------------------------------

    def setup_data(self, data: ColumnTable, params: Any) -> ColumnTable:
        flip = bool(params.get("flipped_aes", False))
        columns = [(name, data.column(name)) for name in data.names]
        put_column(columns, "flipped_aes", Column("bool", np.full(data.nrows, flip, dtype=bool)))
        table = flip_data(ColumnTable(columns, nrows=data.nrows), flip)
        if "ymin" not in table and "ymax" not in table:
            raise GeomError(
                "geom_ribbon 需要 ymin 或 ymax 之一" + ("（横向时是 xmin / xmax）" if flip else "")
            )
        if table.nrows:
            order = _sorted_rows(table)
            table = row_slice(table, order)
        y = table_numeric(table, "ymin") if "ymin" in table else table_numeric(table, "ymax")
        columns = [(name, table.column(name)) for name in table.names]
        put_column(columns, "y", Column("float", y))
        return flip_data(ColumnTable(columns, nrows=table.nrows), flip)

    def handle_na(self, geom: Any, data: ColumnTable, na_rm: bool) -> ColumnTable:
        """`GeomRibbon$handle_na()`：按方向取 x 族 / y 族的首个备选名删行并重编组。"""
        if data.nrows == 0:
            return data
        flip = _is_flipped(data)
        first = [name.split("|")[0] for name in geom.required_aes]
        if flip:
            from ggcore.aes import flipped_names

            names = flipped_names(True)
            first = [names.get(name, name) for name in first]
        variables = [name for name in first + list(self.non_missing_aes) if name in data]
        missing = np.zeros(data.nrows, dtype=bool)
        for name in variables:
            missing |= np.asarray(data.column(name).na_mask, dtype=bool)
        if not bool(missing.any()):
            return data
        if not na_rm:
            count = int(missing.sum())
            noun = "row" if count == 1 else "rows"
            import warnings

            warnings.warn(
                f"Removed {count} {noun} containing missing values or values outside "
                f"the scale range (`geom_{geom.name}()`).",
                BuildWarning,
                stacklevel=4,
            )
        groups = _group_values(data)
        runs = np.zeros(data.nrows, dtype=np.int64)
        code = 0
        previous: tuple[float, bool] | None = None
        for index in range(data.nrows):
            key = (float(groups[index]), bool(missing[index]))
            if key != previous:
                code += 1
                previous = key
            runs[index] = code
        columns = []
        for name in data.names:
            column = data.column(name)
            if name == "group":
                column = Column("int", runs.astype(np.int64))
            columns.append((name, column))
        return row_slice(ColumnTable(columns, nrows=data.nrows), ~missing)

    # -- draw -------------------------------------------------------------

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        data = build.data
        if data.nrows == 0:
            return null_grob(name="geom_ribbon")
        params = build.params
        outline = str(params.get("outline.type", "both"))
        if outline not in ("both", "upper", "lower", "full"):
            raise GeomError(
                "geom_ribbon(outline.type=...) 只能是 both / upper / lower / full，"
                f"收到 {outline!r}"
            )
        lineend = str(params.get("lineend", "butt"))
        linejoin = str(params.get("linejoin", "round"))
        linemitre = float(params.get("linemitre", 10.0))
        flip = _is_flipped(data)
        x = table_numeric(data, "x", default=float("nan"))
        low = table_numeric(data, "ymin", default=float("nan"))
        high = table_numeric(data, "ymax", default=float("nan"))
        groups = _group_values(data)
        grobs: list[Any] = []
        for key in _keys(groups):
            rows = np.flatnonzero(groups == key)
            if rows.size == 0:
                continue
            first = int(rows[0])
            gp = _ribbon_gpar(data, rows, first, outline, lineend, linejoin, linemitre)
            _check_constant(data, rows, key)
            ids = _missing_ids(x[rows], low[rows], high[rows])
            upper_x, upper_y, upper_id = _positions(x[rows], high[rows], ids)
            lower_x, lower_y, lower_id = _positions(x[rows][::-1], low[rows][::-1], ids[::-1])
            if flip:
                upper_x, upper_y = upper_y, upper_x
                lower_x, lower_y = lower_y, lower_x
            px_u, py_u, id_u = munch_xy(panel, upper_x, upper_y, upper_id.tolist())
            px_l, py_l, id_l = munch_xy(panel, lower_x, lower_y, lower_id.tolist())
            px = np.concatenate([px_u, px_l])
            py = np.concatenate([py_u, py_l])
            offset = int(np.max(id_u)) if id_u else 0
            # 多边形是**一个环**（上沿正向 + 下沿反向，id 相同）；偏移只给轮廓线用。
            ids_all = list(id_u) + [int(item) for item in id_l]
            if outline == "full":
                grobs.append(
                    polygon_grob(
                        unit(px.tolist(), "native"),
                        unit(py.tolist(), "native"),
                        id=ids_all,
                        default_units="native",
                        name="geom_ribbon",
                        gp=gp,
                    )
                )
                continue
            fill_gp = gpar(
                fill=gp.fill,
                col=NA,
                lwd=0.0,
                lineend=lineend,
                linejoin=linejoin,
            )
            grobs.append(
                polygon_grob(
                    unit(px.tolist(), "native"),
                    unit(py.tolist(), "native"),
                    id=ids_all,
                    default_units="native",
                    name="geom_ribbon",
                    gp=fill_gp,
                )
            )
            line_gp = gpar(
                col=gp.col,
                lwd=gp.lwd,
                lty=gp.lty,
                lineend=lineend,
                linejoin=linejoin,
                linemitre=linemitre,
            )
            edges = []
            if outline in ("both", "upper"):
                edges.append((px_u, py_u, id_u))
            if outline in ("both", "lower"):
                edges.append((px_l, py_l, [int(item) + offset for item in id_l]))
            for edge_x, edge_y, edge_id in edges:
                grobs.append(
                    polyline_grob(
                        unit(edge_x.tolist(), "native"),
                        unit(edge_y.tolist(), "native"),
                        id=edge_id,
                        default_units="native",
                        name="geom_ribbon",
                        gp=line_gp,
                    )
                )
        if not grobs:
            return null_grob(name="geom_ribbon")
        if len(grobs) == 1:
            return grobs[0]
        return g_tree(*grobs, name="geom_ribbon")


def _ribbon_gpar(
    data: Any,
    rows: np.ndarray,
    first: int,
    outline: str,
    lineend: str,
    linejoin: str,
    linemitre: float,
) -> gpar:
    fills = table_values(data, "fill", "grey20")
    colours = table_values(data, "colour", NA)
    alpha = table_numeric(data, "alpha", default=math.nan)
    linewidth = table_numeric(data, "linewidth", default=0.5)
    linetype = table_values(data, "linetype", 1)
    del rows
    return gpar(
        fill=alpha_colour(fills[first], alpha[first]),
        col=None if outline == "full" else alpha_colour(colours[first], alpha[first]),
        lwd=float(linewidth[first]) * POINT_PER_MM,
        lty=lty_value(linetype[first]),
        lineend=lineend,
        linejoin=linejoin,
        linemitre=linemitre,
    )


def _check_constant(data: Any, rows: np.ndarray, key: float) -> None:
    """`Aesthetics can not vary along a ribbon`：组内 colour / linewidth / … 必须唯一。"""
    varying: list[str] = []
    for name in ("colour", "linewidth", "linetype", "alpha"):
        if name not in data:
            continue
        column = data.column(name)
        values = np.asarray(column.values)[rows]
        if np.unique(values.astype(str)).size > 1:
            varying.append(name)
    if varying:
        raise GeomError(
            "Aesthetics can not vary along a ribbon: " + ", ".join(varying) + f"（group {key:g}）"
        )


def _missing_ids(*arrays: np.ndarray) -> np.ndarray:
    missing = np.zeros(arrays[0].size, dtype=bool)
    for array in arrays:
        missing |= ~np.isfinite(array)
    ids = np.cumsum(missing) + 1
    ids[missing] = 0
    return ids


def _positions(
    along: np.ndarray, across: np.ndarray, ids: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    keep = ids != 0
    return along[keep], across[keep], ids[keep]


def _sorted_rows(table: ColumnTable) -> np.ndarray:
    keys: list[np.ndarray] = []
    if "PANEL" in table:
        keys.append(np.asarray(table.column("PANEL").values))
    keys.append(table_numeric(table, "group", default=0.0))
    keys.append(table_numeric(table, "x", default=0.0))
    return np.lexsort(tuple(reversed(keys)))


# ---------------------------------------------------------------------------
# geom_step
# ---------------------------------------------------------------------------


def _stairstep(
    x: np.ndarray, y: np.ndarray, direction: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """`stairstep()`：输入已按 x 排好序，返回展开后的 `(x, y, 源行下标)`。"""
    if direction not in ("hv", "vh", "mid"):
        raise GeomError(f"geom_step(direction=...) 只能是 hv / vh / mid，收到 {direction!r}")
    n = x.size
    if n <= 1:
        return np.empty(0), np.empty(0), np.empty(0, dtype=np.int64)
    if direction == "vh":
        xs = np.repeat(np.arange(n), 2)[:-1]
        ys = np.concatenate(([0], np.repeat(np.arange(1, n), 2)))
        return x[xs], y[ys], xs.astype(np.int64)
    if direction == "hv":
        ys = np.repeat(np.arange(n), 2)[:-1]
        xs = np.concatenate(([0], np.repeat(np.arange(1, n), 2)))
        return x[xs], y[ys], xs.astype(np.int64)
    gaps = x[1:] - x[:-1]
    middle = x[:-1] + gaps / 2
    xs = np.repeat(np.arange(n - 1), 2)
    ys = np.repeat(np.arange(n), 2)
    out_x = np.concatenate(([x[0]], middle[xs], [x[-1]]))
    out_y = y[ys]
    rows = np.concatenate(([0], xs, [n - 1])).astype(np.int64)
    return out_x, out_y, rows


class StepRenderer(PathRenderer):
    """`geom_step`：逐 group 展开成阶梯折线，绘制同 `geom_path`。"""

    name = "step"
    detect_flipped = True
    ambiguous_flipped = True

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        data = build.data
        if data.nrows == 0:
            return null_grob(name="geom_step")
        params = dict(build.params)
        flip = _is_flipped(data)
        direction = str(params.get("direction", "hv"))
        if flip:
            direction = {"hv": "vh", "vh": "hv"}.get(direction, direction)
        frame = flip_data(data, flip)
        x = table_numeric(frame, "x", default=float("nan"))
        y = table_numeric(frame, "y", default=float("nan"))
        groups = _group_values(frame)
        xs: list[np.ndarray] = []
        ys: list[np.ndarray] = []
        rows: list[np.ndarray] = []
        for key in _keys(groups):
            group_rows = np.flatnonzero(groups == key)
            order = np.argsort(x[group_rows], kind="stable")
            step_x, step_y, local = _stairstep(
                x[group_rows][order], y[group_rows][order], direction
            )
            if step_x.size == 0:
                continue
            xs.append(step_x)
            ys.append(step_y)
            rows.append(group_rows[order][local])
        if not rows:
            return null_grob(name="geom_step")
        expanded = row_slice(frame, np.concatenate(rows))
        columns = [(name, expanded.column(name)) for name in expanded.names]
        put_column(columns, "x", Column("float", np.concatenate(xs)))
        put_column(columns, "y", Column("float", np.concatenate(ys)))
        expanded = ColumnTable(columns, nrows=int(np.concatenate(xs).size))
        expanded = flip_data(expanded, flip)
        return PathRenderer.draw(
            self,
            geom,
            SimpleNamespace(data=expanded, params=params),
            panel,
            coord,
            theme,
            metrics,
        )

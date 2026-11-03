"""`geom_bar` / `geom_col` / `geom_histogram` / `geom_area` 的绘制（M1-7）。

柱与面积都直接用 M1-9 算好的 `xmin/xmax/ymin/ymax`，**不重新实现位置逻辑**：
`stack` / `fill` / `dodge` 的结果已经在 `build.data` 里，这里只把它们映射成面板
npc 再画矩形 / 多边形。

照 4.0.3：

- `GeomBar$setup_data()`：`flipped_aes` → `compute_data_size()`（width）→
  `ymin = pmin(y, 0)`、`ymax = pmax(y, 0)`、`xmin = x - width*just`、
  `xmax = x + width*(1-just)`，然后去掉 `width` / `just`；
- `GeomBar$draw_panel()`：`rectGrob(xmin, ymax, width = xmax - xmin,
  height = ymax - ymin, just = c("left", "top"))`，`fill` 吃 alpha、`col` 不吃
  （R 的 `gg_par(col = coords$colour, fill = fill_alpha(...))`）；
- `GeomArea$setup_data()`：按 `(PANEL, group, x)` 排序，`ymin = 0`、`ymax = y`；
- `GeomArea$draw_group()`：上沿正向 + 下沿反向的多边形（`fill` 吃 alpha，
  沿 `x` 断成多段），再画上下两条轮廓折线（`outline.type = "both"`）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from ggcore.build import BuildWarning
from ggcore.data import Column, ColumnTable
from ggcore.geom.base import (
    POINT_PER_MM,
    GeomError,
    GeomRenderer,
    alpha_colour,
    default_size,
    flip_data,
    lty_value,
    munch_xy,
    npc_values,
    row_slice,
    table_numeric,
)
from ggcore.grobs import g_tree, null_grob, polygon_grob, polyline_grob, rect_grob
from ggcore.units import unit
from ggcore.viewport import NA, gpar

__all__ = ["AreaRenderer", "BarRenderer", "HistogramRenderer"]


def _put(columns: list[tuple[str, Column]], name: str, column: Column) -> list[tuple[str, Column]]:
    for position, (key, _) in enumerate(columns):
        if key == name:
            columns[position] = (name, column)
            return columns
    columns.append((name, column))
    return columns


def _width_column(table: ColumnTable, params: Any, default: float) -> np.ndarray:
    if "width" in table:
        values = table_numeric(table, "width", default=default)
        return values
    value = params.get("width")
    if value is None:
        return np.full(table.nrows, float(default))
    return np.full(table.nrows, float(value))


def _default_width(data: ColumnTable, params: Any) -> float:
    """R `compute_data_size(data, default = 0.9, zero = FALSE)`。

    离散位置（`mapped_discrete`）→ 恒为 0.9；连续位置 → `resolution(x) * 0.9`。
    """
    if params.get("_discrete_position"):
        return 0.9
    return default_size(data, "x")


class BarRenderer(GeomRenderer):
    """`geom_bar` / `geom_col`（`histogram` 的绘制与柱相同）。"""

    name = "bar"
    non_missing_aes = ("xmin", "xmax", "ymin", "ymax")
    detect_flipped = True

    def setup_data(self, data: ColumnTable, params: Any) -> ColumnTable:
        flip = bool(params.get("flipped_aes", False))
        columns = [(name, data.column(name)) for name in data.names]
        columns = _put(
            columns, "flipped_aes", Column("bool", np.full(data.nrows, flip, dtype=bool))
        )
        table = ColumnTable(columns, nrows=data.nrows)
        frame = flip_data(table, flip)
        width = _width_column(frame, params, _default_width(frame, params))
        just = float(params.get("just", 0.5))
        y = table_numeric(frame, "y")
        x = table_numeric(frame, "x")
        columns = [(name, frame.column(name)) for name in frame.names]
        columns = _put(columns, "ymin", Column("float", np.minimum(y, 0.0)))
        columns = _put(columns, "ymax", Column("float", np.maximum(y, 0.0)))
        columns = _put(columns, "xmin", Column("float", x - width * just))
        columns = _put(columns, "xmax", Column("float", x + width * (1.0 - just)))
        columns = [(name, column) for name, column in columns if name not in ("width", "just")]
        return flip_data(ColumnTable(columns, nrows=data.nrows), flip)

    @staticmethod
    def _default_width(data: ColumnTable, params: Any = None) -> float:
        """R `compute_data_size(data, default = 0.9, zero = FALSE)`（兼容旧调用点）。"""
        return _default_width(data, params or {})

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        data = build.data
        if data.nrows == 0:
            return null_grob(name=f"geom_{self.name}")
        xmin = npc_values(panel, data, "xmin", "x")
        xmax = npc_values(panel, data, "xmax", "x")
        ymin = npc_values(panel, data, "ymin", "y")
        ymax = npc_values(panel, data, "ymax", "y")
        colours = _values(data, "colour", None)
        fills = _values(data, "fill", "grey35")
        alpha = table_numeric(data, "alpha", default=math.nan)
        linewidth = table_numeric(data, "linewidth", default=0.5)
        linetype = _values(data, "linetype", 1)
        linejoin = str(build.params.get("linejoin", "mitre"))
        lineend = str(build.params.get("lineend", "butt"))
        if not getattr(panel, "is_linear", True):
            # 极坐标 / 非线性变换：矩形要按 `coord_munch()` 逐边细分，否则上下边
            # 是弦而不是弧（R 的 `GeomRect$draw_panel()` 走 `GeomPolygon` 同一条路）。
            return _munch_rects(
                data,
                panel,
                fills=fills,
                colours=colours,
                alpha=alpha,
                linewidth=linewidth,
                linetype=linetype,
                linejoin=linejoin,
                lineend=lineend,
                name=f"geom_{self.name}",
            )
        return rect_grob(
            x=((xmin + xmax) / 2.0).tolist(),
            y=((ymin + ymax) / 2.0).tolist(),
            width=(xmax - xmin).tolist(),
            height=(ymax - ymin).tolist(),
            just="centre",
            default_units="native",
            name=f"geom_{self.name}",
            gp={
                "col": colours,
                "fill": [
                    alpha_colour(item, value) for item, value in zip(fills, alpha, strict=True)
                ],
                "lwd": (linewidth * POINT_PER_MM).tolist(),
                "lty": lty_value(linetype[0]) if linetype else 1,
                "linejoin": linejoin,
                "lineend": lineend,
            },
        )


def _munch_rects(
    data: Any,
    panel: Any,
    *,
    fills: list[Any],
    colours: list[Any],
    alpha: np.ndarray,
    linewidth: np.ndarray,
    linetype: list[Any],
    linejoin: str,
    lineend: str,
    name: str,
) -> Any:
    """每根柱按四个角细分出的多边形（极坐标的楔形由 `coord_munch` 的采样表达）。"""
    xmin = table_numeric(data, "xmin")
    xmax = table_numeric(data, "xmax")
    ymin = table_numeric(data, "ymin")
    ymax = table_numeric(data, "ymax")
    polygons: list[Any] = []
    for index in range(data.nrows):
        if not all(
            math.isfinite(value) for value in (xmin[index], xmax[index], ymin[index], ymax[index])
        ):
            continue
        xs = [xmin[index], xmin[index], xmax[index], xmax[index]]
        ys = [ymin[index], ymax[index], ymax[index], ymin[index]]
        px, py, ids = munch_xy(panel, xs, ys, [0, 0, 0, 0], closed=True)
        polygons.append(
            polygon_grob(
                px.tolist(),
                py.tolist(),
                id=ids,
                default_units="native",
                name=name,
                gp=gpar(
                    fill=alpha_colour(fills[index], alpha[index]),
                    col=colours[index],
                    lwd=float(linewidth[index]) * POINT_PER_MM,
                    lty=lty_value(linetype[index]),
                    linejoin=linejoin,
                    lineend=lineend,
                ),
            )
        )
    if not polygons:
        return null_grob(name=name)
    if len(polygons) == 1:
        return polygons[0]
    return g_tree(*polygons, name=name)


class HistogramRenderer(BarRenderer):
    """`geom_histogram`：数据来自 `stat_bin`（M1-8），绘制同柱。"""

    name = "histogram"


class AreaRenderer(GeomRenderer):
    """`geom_area`：`ymin = 0` 到 `ymax = y` 的多边形 + 轮廓线。"""

    name = "area"
    detect_flipped = True
    ambiguous_flipped = True

    def handle_na(self, geom: Any, data: ColumnTable, na_rm: bool) -> ColumnTable:
        """`GeomArea$handle_na()`：按 orientation 取 x 族/ y 族的必需列，删行后重编组。"""
        if data.nrows == 0:
            return data
        flip = (
            bool(np.any(np.asarray(data.column("flipped_aes").values)))
            if ("flipped_aes" in data)
            else False
        )
        first = [name.split("|")[0] for name in geom.required_aes]
        if flip:
            flipped = {
                "x": "y",
                "y": "x",
                "xmin": "ymin",
                "xmax": "ymax",
                "ymin": "xmin",
                "ymax": "xmax",
                "xlower": "ylower",
                "xupper": "yupper",
            }
            first = [flipped.get(name, name) for name in first]
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
        # `data$group <- vec_identify_runs(data_frame0(missing, data$group))`：
        # 删行后按「缺失 → 非缺失」的连续段重编组，断开的面积不会连成一笔。
        keep = ~missing
        groups = (
            np.asarray(data.column("group").values, dtype=np.float64)
            if "group" in data
            else np.zeros(data.nrows)
        )
        runs = np.zeros(data.nrows, dtype=np.int64)
        previous: tuple[float, bool] | None = None
        code = 0
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
        renumbered = ColumnTable(columns, nrows=data.nrows)
        return row_slice(renumbered, keep)

    def setup_data(self, data: ColumnTable, params: Any) -> ColumnTable:
        flip = bool(params.get("flipped_aes", False))
        columns = [(name, data.column(name)) for name in data.names]
        columns = _put(
            columns, "flipped_aes", Column("bool", np.full(data.nrows, flip, dtype=bool))
        )
        table = flip_data(ColumnTable(columns, nrows=data.nrows), flip)
        if table.nrows:
            keys = [
                np.asarray(table.column("PANEL").values)
                if "PANEL" in table
                else np.zeros(table.nrows),
                table_numeric(table, "group", default=0.0),
                table_numeric(table, "x", default=0.0),
            ]
            table = row_slice(table, np.lexsort(tuple(reversed(keys))))
        y = table_numeric(table, "y")
        columns = [(name, table.column(name)) for name in table.names]
        columns = _put(columns, "ymin", Column("float", np.zeros(table.nrows)))
        columns = _put(columns, "ymax", Column("float", y))
        return flip_data(ColumnTable(columns, nrows=table.nrows), flip)

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        data = build.data
        if data.nrows == 0:
            return null_grob(name="geom_area")
        flip = (
            bool(np.any(np.asarray(data.column("flipped_aes").values)))
            if ("flipped_aes" in data)
            else False
        )
        if not getattr(panel, "is_linear", True) and not flip:
            # 非线性坐标（极坐标 / coord_trans）：上沿 + 下沿的多边形逐边细分。
            return _munch_area(
                data,
                panel,
                fills=_values(data, "fill", "grey20"),
                colours=_values(data, "colour", None),
                alpha=table_numeric(data, "alpha", default=math.nan),
                linewidth=table_numeric(data, "linewidth", default=0.5),
                linetype=_values(data, "linetype", 1),
                lineend=str(build.params.get("lineend", "butt")),
                linejoin=str(build.params.get("linejoin", "round")),
            )
        if flip:
            # 横向面积：先按纵向语义（along = 类别轴、low/high = 长度轴）拼多边形，
            # 再照 R 的 `flip_data(positions)` 把 x / y 对调 —— 最终多边形沿长度
            # 轴 x 从 0 铺到 value、在类别轴 y 上取分类位置。直接把 along 当 x 会
            # 把两条轴对调（类别轴 ↔ 长度轴）。
            along = npc_values(panel, data, "y", "y")
            low = npc_values(panel, data, "xmin", "x")
            high = npc_values(panel, data, "xmax", "x")
        else:
            along = npc_values(panel, data, "x", "x")
            low = npc_values(panel, data, "ymin", "y")
            high = npc_values(panel, data, "ymax", "y")
        fill = _values(data, "fill", "grey20")
        colour = _values(data, "colour", None)
        alpha = table_numeric(data, "alpha", default=math.nan)
        linewidth = table_numeric(data, "linewidth", default=0.5)
        linetype = _values(data, "linetype", 1)
        lineend = str(build.params.get("lineend", "butt"))
        linejoin = str(build.params.get("linejoin", "round"))
        outline = str(build.params.get("outline.type", "both") or "both")
        if outline not in ("both", "upper", "lower", "full"):
            raise GeomError(f"outline.type 只能是 both / upper / lower / full，收到 {outline!r}")
        groups = (
            np.asarray(data.column("group").values, dtype=np.float64)
            if "group" in data
            else np.zeros(data.nrows)
        )

        polygons: list[Any] = []
        outlines: list[Any] = []
        for key in _keys(groups):
            rows = np.flatnonzero(groups == key)
            ids = _segment_ids(along[rows], low[rows], high[rows])
            upper_x, upper_y, upper_id = _positions(along[rows], high[rows], ids)
            lower_x, lower_y, lower_id = _positions(along[rows][::-1], low[rows][::-1], ids[::-1])
            # 不按「行数 < 2」丢组：横向面积每组只有一行（类别是分组依据），R 的
            # `GeomArea$draw_group()` 照样出 2 点退化多边形（= 沿长度轴的线段）。
            if upper_x.size + lower_x.size == 0:
                continue
            first = rows[0]
            poly_x = np.concatenate([upper_x, lower_x])
            poly_y = np.concatenate([upper_y, lower_y])
            if flip:
                # R 的 `flip_data(positions)`：纵向语义拼好的 x / y 在这里对调。
                poly_x, poly_y = poly_y, poly_x
            polygons.append(
                polygon_grob(
                    unit(poly_x.tolist(), "native"),
                    unit(poly_y.tolist(), "native"),
                    id=[int(item) for item in np.concatenate([upper_id, lower_id]).tolist()],
                    default_units="native",
                    gp=gpar(
                        fill=alpha_colour(fill[first], alpha[first]),
                        col=NA,
                        lwd=0.0,
                    ),
                )
            )
            if colour[first] is not None and colour[first] is not NA:
                edges: list[tuple[np.ndarray, np.ndarray, list[int]]] = []
                if outline in ("both", "upper", "full"):
                    edges.append((upper_x, upper_y, upper_id))
                if outline in ("both", "lower", "full"):
                    edges.append((lower_x, lower_y, lower_id))
                for px, py, pid in edges:
                    if flip:
                        px, py = py, px
                    outlines.append(
                        polyline_grob(
                            unit(px.tolist(), "native"),
                            unit(py.tolist(), "native"),
                            id=[int(item) + int(np.max(ids)) for item in pid],
                            default_units="native",
                            gp=gpar(
                                col=alpha_colour(colour[first], alpha[first]),
                                lwd=float(linewidth[first]) * POINT_PER_MM,
                                lty=lty_value(linetype[first]),
                                lineend=lineend,
                                linejoin=linejoin,
                            ),
                        )
                    )
        grobs = polygons + outlines
        if not grobs:
            return null_grob(name="geom_area")
        if len(grobs) == 1:
            return grobs[0]
        return g_tree(*grobs, name="geom_area")


def _munch_area(
    data: Any,
    panel: Any,
    *,
    fills: list[Any],
    colours: list[Any],
    alpha: np.ndarray,
    linewidth: np.ndarray,
    linetype: list[Any],
    lineend: str,
    linejoin: str,
) -> Any:
    """`geom_area` 在非线性坐标下的多边形：上沿正向 + 下沿反向，逐边细分。"""
    x = table_numeric(data, "x")
    low = table_numeric(data, "ymin")
    high = table_numeric(data, "ymax")
    groups = (
        np.asarray(data.column("group").values, dtype=np.float64)
        if "group" in data
        else np.zeros(data.nrows)
    )
    grobs: list[Any] = []
    for key in _keys(groups):
        rows = np.flatnonzero(groups == key)
        if rows.size == 0:
            continue
        keep = np.isfinite(x[rows]) & np.isfinite(low[rows]) & np.isfinite(high[rows])
        rows = rows[keep]
        if rows.size == 0:
            continue
        xs = np.concatenate([x[rows], x[rows][::-1]])
        ys = np.concatenate([high[rows], low[rows][::-1]])
        px, py, ids = munch_xy(panel, xs, ys, [0] * xs.size, closed=True)
        first = int(rows[0])
        grobs.append(
            polygon_grob(
                px.tolist(),
                py.tolist(),
                id=ids,
                default_units="native",
                name="geom_area",
                gp=gpar(
                    fill=alpha_colour(fills[first], alpha[first]),
                    col=NA,
                    lwd=0.0,
                ),
            )
        )
        if colours[first] is not None and colours[first] is not NA:
            for xs_edge, ys_edge in (
                (xs[: rows.size], ys[: rows.size]),
                (xs[rows.size :][::-1], ys[rows.size :][::-1]),
            ):
                ex, ey, eid = munch_xy(panel, xs_edge, ys_edge, [0] * xs_edge.size)
                grobs.append(
                    polyline_grob(
                        ex.tolist(),
                        ey.tolist(),
                        id=eid,
                        default_units="native",
                        name="geom_area",
                        gp=gpar(
                            col=alpha_colour(colours[first], alpha[first]),
                            lwd=float(linewidth[first]) * POINT_PER_MM,
                            lty=lty_value(linetype[first]),
                            lineend=lineend,
                            linejoin=linejoin,
                        ),
                    )
                )
    if not grobs:
        return null_grob(name="geom_area")
    if len(grobs) == 1:
        return grobs[0]
    return g_tree(*grobs, name="geom_area")


def _segment_ids(*arrays: np.ndarray) -> list[int]:
    """按任意一个坐标缺失切段（R 的 `ids <- cumsum(missing_pos) + 1`）。"""
    missing = np.zeros(arrays[0].size, dtype=bool)
    for array in arrays:
        missing |= ~np.isfinite(array)
    ids: list[int] = []
    current = 0
    for value in missing.tolist():
        if not value:
            if not ids or ids[-1] == 0:
                current += 1
        ids.append(0 if value else current)
    return ids


def _positions(
    x: np.ndarray, y: np.ndarray, ids: list[int]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    keep = np.array([item != 0 for item in ids], dtype=bool)
    return x[keep], y[keep], np.asarray(ids)[keep]


def _values(data: Any, name: str, default: Any) -> list[Any]:
    if name not in data:
        return [default] * data.nrows
    column = data.column(name)
    values = column.values.tolist()
    mask = np.asarray(column.na_mask, dtype=bool).tolist()
    return [NA if missing else value for value, missing in zip(values, mask, strict=True)]


def _keys(groups: np.ndarray) -> list[float]:
    seen: dict[float, None] = {}
    for value in groups.tolist():
        seen.setdefault(float(value), None)
    return list(seen)

"""矩形族（M2-S2）：`geom_rect` / `geom_tile` / `geom_raster` 的绘制。

照 4.0.3：

- `GeomRect$setup_data()`：四个角只要缺一个，就按 `resolve_rect()` 用
  `(min, max, center, length)` 里的其余两个补；缺的 aes 先从 `params` 取同名值。
- `GeomRect$draw_panel()`：`rectGrob(xmin, ymax, width = xmax - xmin,
  height = ymax - ymin, just = c("left", "top"))`，`fill` 吃 alpha、`col` 不吃；
  非线性坐标拆成多边形逐边细分（`GeomPolygon` 那条路）。
- `GeomTile$setup_data()`：`compute_data_size(..., panels = "by", discrete = TRUE)`
  求 `width` / `height`（缺省是 1，不是 0.9），再派生 `xmin/xmax/ymin/ymax`。
- `GeomRaster$setup_data()`：像素间距必须等距，否则 warn 并取最小间距；
  `hjust` / `vjust` 决定像素往哪边偏。
- `GeomRaster$draw_panel()`：把一格一个颜色铺成矩阵（列 = x 位置，行 = y 位置，
  首行在上），交给 `rasterGrob(interpolate = interpolate)`；非线性坐标降级成
  `GeomRect`（`linewidth = 0.3`、`colour = fill`）。

`geom_raster` 的位图在写 IR 之前折成一张 RGBA PNG（`ggcore.png`），IR 的 `raster`
节点只带 blob id + 目标矩形 + `interpolate`——bulk 像素不进 JSON（X1）。
"""

from __future__ import annotations

import math
import warnings
from typing import Any

import numpy as np

from ggcore.build import BuildWarning
from ggcore.data import Column, ColumnTable
from ggcore.geom.base import (
    POINT_PER_MM,
    GeomError,
    GeomRenderer,
    alpha_colour,
    lty_value,
    npc_values,
    put_column,
    resolve_rect_axis,
    table_numeric,
    table_values,
)
from ggcore.grobs import null_grob, raster_grob, rect_grob
from ggcore.png import encode_rgba
from ggcore.viewport import NA

__all__ = ["RasterRenderer", "RectRenderer", "TileRenderer"]


def _column_or_none(data: ColumnTable, name: str) -> np.ndarray | None:
    return table_numeric(data, name) if name in data else None


def _params_column(params: Any, name: str, nrows: int) -> np.ndarray | None:
    if name not in params or params[name] is None:
        return None
    return np.full(nrows, float(params[name]))


def _panel_resolution_by(data: ColumnTable, name: str, *, discrete: bool) -> np.ndarray:
    """`compute_data_size(panels = "by")`：逐 PANEL 求 resolution，广播回每一行。

    `discrete = TRUE` 且该轴是离散位置（R 的 `mapped_discrete`）时直接给 1
    （与 `resolution(x, discrete = TRUE)` 同一分支）。
    """
    if discrete:
        return np.ones(data.nrows)
    values = table_numeric(data, name, default=float("nan"))
    panels = _panel_labels(data)
    out = np.ones(data.nrows)
    for label in sorted(set(panels)):
        rows = np.array([item == label for item in panels])
        out[rows] = _resolution(values[rows])
    return out


def _resolution(values: np.ndarray) -> float:
    """`resolution(x, zero = FALSE)` 的数值分支（离散位置已经在调用方折成 1）。"""
    finite = values[np.isfinite(values)]
    if finite.size < 2:
        return 1.0
    unique = np.unique(finite)
    if unique.size < 2:
        return 1.0
    diffs = np.diff(unique)
    tolerance = float(np.sqrt(np.finfo(np.float64).eps))
    positive = diffs[diffs > tolerance]
    return float(positive.min()) if positive.size else 1.0


def _panel_labels(data: ColumnTable) -> list[str]:
    if "PANEL" not in data or data.nrows == 0:
        return ["1"] * data.nrows
    return [str(item) for item in data.column("PANEL").values.tolist()]


def _data_size(
    data: ColumnTable, params: Any, target: str, default: float, *, discrete: bool
) -> np.ndarray:
    """`compute_data_size()`：列 > 参数 > 逐面板 resolution × default。"""
    if target in data:
        return table_numeric(data, target)
    given = _params_column(params, target, data.nrows)
    if given is not None:
        return given
    axis = "y" if target == "height" else "x"
    return _panel_resolution_by(data, axis, discrete=discrete) * float(default)


class RectRenderer(GeomRenderer):
    """`geom_rect`：直接画 `xmin/xmax/ymin/ymax`（缺的角按 `resolve_rect` 补）。"""

    name = "rect"
    rename_size = True

    def setup_data(self, data: ColumnTable, params: Any) -> ColumnTable:
        names = set(data.names)
        if {"xmin", "xmax", "ymin", "ymax"} <= names:
            return data
        columns = [(name, data.column(name)) for name in data.names]
        required = ["x|width|xmin|xmax", "y|height|ymin|ymax"]
        missing = [name for group in required for name in group.split("|") if name not in names]
        for name in missing:
            if name in params and params[name] is not None:
                put_column(columns, name, Column("float", np.full(data.nrows, float(params[name]))))
        table = ColumnTable(columns, nrows=data.nrows)
        columns = [(name, table.column(name)) for name in table.names]
        for names4 in (
            ("xmin", "xmax", "x", "width"),
            ("ymin", "ymax", "y", "height"),
        ):
            minimum = _column_or_none(table, names4[0])
            maximum = _column_or_none(table, names4[1])
            centre = _column_or_none(table, names4[2])
            length = _column_or_none(table, names4[3])
            if minimum is not None and maximum is not None:
                continue
            resolved = resolve_rect_axis(minimum, maximum, centre, length, names=names4, fun="rect")
            if resolved is None:  # pragma: no cover - 两个都给过会走上面的 continue
                continue
            low, high = resolved
            if minimum is None:
                put_column(columns, names4[0], Column("float", np.asarray(low, dtype=np.float64)))
            if maximum is None:
                put_column(columns, names4[1], Column("float", np.asarray(high, dtype=np.float64)))
        return ColumnTable(columns, nrows=data.nrows)

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        data = build.data
        if data.nrows == 0:
            return null_grob(name="geom_rect")
        return _draw_rects(self.name, data, build.params, panel)


def _draw_rects(name: str, data: ColumnTable, params: Any, panel: Any) -> Any:
    """`rectGrob(xmin, ymax, width, height, just = c("left", "top"))` 的等价物。"""
    if not getattr(panel, "is_linear", True):
        from ggcore.geom.bar import _munch_rects

        return _munch_rects(
            data,
            panel,
            fills=table_values(data, "fill", "grey35"),
            colours=table_values(data, "colour", NA),
            alpha=table_numeric(data, "alpha", default=math.nan),
            linewidth=table_numeric(data, "linewidth", default=0.5),
            linetype=table_values(data, "linetype", 1),
            linejoin=str(params.get("linejoin", "mitre")),
            lineend=str(params.get("lineend", "butt")),
            name=f"geom_{name}",
        )
    xmin = npc_values(panel, data, "xmin", "x")
    xmax = npc_values(panel, data, "xmax", "x")
    ymin = npc_values(panel, data, "ymin", "y")
    ymax = npc_values(panel, data, "ymax", "y")
    fills = table_values(data, "fill", "grey35")
    colours = table_values(data, "colour", NA)
    alpha = table_numeric(data, "alpha", default=math.nan)
    linewidth = table_numeric(data, "linewidth", default=0.5)
    linetype = table_values(data, "linetype", 1)
    return rect_grob(
        x=((xmin + xmax) / 2.0).tolist(),
        y=((ymin + ymax) / 2.0).tolist(),
        width=(xmax - xmin).tolist(),
        height=(ymax - ymin).tolist(),
        just="centre",
        default_units="native",
        name=f"geom_{name}",
        gp={
            "col": colours,
            "fill": [alpha_colour(item, value) for item, value in zip(fills, alpha, strict=True)],
            "lwd": (linewidth * POINT_PER_MM).tolist(),
            "lty": lty_value(linetype[0]) if linetype else 1,
            "linejoin": str(params.get("linejoin", "mitre")),
            "lineend": str(params.get("lineend", "butt")),
        },
    )


class TileRenderer(RectRenderer):
    """`geom_tile`：以 `(x, y)` 为中心、`width` / `height` 为边长的矩形。"""

    name = "tile"

    def setup_data(self, data: ColumnTable, params: Any) -> ColumnTable:
        width = _data_size(
            data,
            params,
            "width",
            1.0,
            discrete=bool(params.get("_discrete_position")),
        )
        # 高度沿 y 轴：离散位置只可能来自 x（tile 不翻转），所以这里按连续求 resolution。
        height = _data_size(data, params, "height", 1.0, discrete=False)
        x = table_numeric(data, "x", default=float("nan"))
        y = table_numeric(data, "y", default=float("nan"))
        columns = [(name, data.column(name)) for name in data.names]
        put_column(columns, "xmin", _float(x - width / 2.0))
        put_column(columns, "xmax", _float(x + width / 2.0))
        put_column(columns, "ymin", _float(y - height / 2.0))
        put_column(columns, "ymax", _float(y + height / 2.0))
        return ColumnTable(
            [(name, column) for name, column in columns if name not in ("width", "height")],
            nrows=data.nrows,
        )


def _float(values: Any) -> Column:
    return Column("float", np.asarray(values, dtype=np.float64))


class RasterRenderer(RectRenderer):
    """`geom_raster`：等距像素 → 一张 RGBA 位图（`interpolate` 走节点参数）。"""

    name = "raster"

    def setup_data(self, data: ColumnTable, params: Any) -> ColumnTable:
        if data.nrows == 0:
            return data
        precision = math.sqrt(float(np.finfo(np.float64).eps))
        hjust = float(params.get("hjust", 0.5) if params.get("hjust") is not None else 0.5)
        vjust = float(params.get("vjust", 0.5) if params.get("vjust") is not None else 0.5)
        x = table_numeric(data, "x", default=float("nan"))
        y = table_numeric(data, "y", default=float("nan"))
        w = _even_spacing(x, "horizontal", precision)
        h = _even_spacing(y, "horizontal", precision)
        columns = [(name, data.column(name)) for name in data.names]
        put_column(columns, "xmin", _float(x - w * (1 - hjust)))
        put_column(columns, "xmax", _float(x + w * hjust))
        put_column(columns, "ymin", _float(y - h * (1 - vjust)))
        put_column(columns, "ymax", _float(y + h * vjust))
        return ColumnTable(columns, nrows=data.nrows)

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        data = build.data
        if data.nrows == 0:
            return null_grob(name="geom_raster")
        if "x" not in data or "y" not in data or "xmin" not in data or "xmax" not in data:
            # 图例 key 的假数据没有像素网格：R 的 `draw_key_raster()` 画的也是
            # 一个整格矩形（不是位图）。
            return _draw_rects(
                "raster",
                ColumnTable(
                    [
                        ("xmin", _float(np.zeros(data.nrows))),
                        ("xmax", _float(np.ones(data.nrows))),
                        ("ymin", _float(np.zeros(data.nrows))),
                        ("ymax", _float(np.ones(data.nrows))),
                        ("fill", data.column("fill")),
                    ],
                    nrows=data.nrows,
                ),
                build.params,
                _KeyPanel(),
            )
        if not getattr(panel, "is_linear", True):
            # R：`geom_raster` 只支持线性坐标，降级成 GeomRect（lwd = 0.3、colour = fill）。
            warnings.warn(
                "geom_raster only works with linear coordinate systems; falling back to geom_rect",
                BuildWarning,
                stacklevel=2,
            )
            columns = [(name, data.column(name)) for name in data.names]
            put_column(columns, "linewidth", _float(np.full(data.nrows, 0.3)))
            if "fill" in data:
                # R：`data$colour <- data$fill`（像素降级成小矩形时用填充色描边）。
                source = data.column("fill")
                put_column(
                    columns,
                    "colour",
                    Column(source.kind, np.array(source.values), source.levels, source.na_mask),
                )
            return _draw_rects(
                "raster", ColumnTable(columns, nrows=data.nrows), build.params, panel
            )
        raster = _raster_matrix(data)
        interpolate = bool(build.params.get("interpolate", False))
        xmin = npc_values(panel, data, "xmin", "x")
        xmax = npc_values(panel, data, "xmax", "x")
        ymin = npc_values(panel, data, "ymin", "y")
        ymax = npc_values(panel, data, "ymax", "y")
        x_low, x_high = float(np.nanmin(xmin)), float(np.nanmax(xmax))
        y_low, y_high = float(np.nanmin(ymin)), float(np.nanmax(ymax))
        return raster_grob(
            raster["data"],
            raster["width_px"],
            raster["height_px"],
            x=(x_low + x_high) / 2.0,
            y=(y_low + y_high) / 2.0,
            width=x_high - x_low,
            height=y_high - y_low,
            just="centre",
            interpolate=interpolate,
            default_units="native",
            name="geom_raster",
        )


class _KeyPanel:
    """图例 key 的 0..1 面板（`ggcore.guide._KeyPanel` 的同口径副本）。"""

    x_range = (0.0, 1.0)
    y_range = (0.0, 1.0)
    x_limits = (0.0, 1.0)
    y_limits = (0.0, 1.0)
    clip = "on"
    flipped = False
    is_linear = True

    def transform_column(self, table: Any, name: str, axis: str) -> Any:
        from ggcore.data import Column

        column = table.column(name)
        values = np.asarray(column.values, dtype=np.float64)
        mask = np.asarray(column.na_mask, dtype=bool)
        return Column("float", values, na_mask=mask)

    def project_xy(self, xs: Any, ys: Any) -> tuple[np.ndarray, np.ndarray]:
        return np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)


def _even_spacing(values: np.ndarray, label: str, precision: float) -> float:
    """R 的像素间距：等距取首差，不等距 warn 并取最小间距，单值给 1。"""
    finite = np.unique(values[np.isfinite(values)])
    if finite.size == 0:
        return 1.0
    if finite.size == 1:
        return 1.0
    diffs = np.diff(finite)
    if bool(np.any(np.abs(np.diff(diffs)) > precision)):
        warnings.warn(
            f"Raster pixels are placed at uneven {label} intervals and will be shifted. "
            "Consider using `geom_tile()` instead.",
            BuildWarning,
            stacklevel=3,
        )
        return float(diffs.min())
    return float(diffs[0])


def _raster_matrix(data: ColumnTable) -> dict[str, Any]:
    """R 的 `GeomRaster$draw_panel()`：格点 → (nrow, ncol, 4) 的像素矩阵。"""
    x = table_numeric(data, "x")
    y = table_numeric(data, "y")
    fills = table_values(data, "fill", "grey20")
    alpha = table_numeric(data, "alpha", default=math.nan)
    resolution_x = _resolution(x)
    resolution_y = _resolution(y)
    x_pos = np.floor((x - np.nanmin(x)) / resolution_x + 1e-9).astype(np.int64)
    y_pos = np.floor((y - np.nanmin(y)) / resolution_y + 1e-9).astype(np.int64)
    nrow = int(y_pos.max()) + 1
    ncol = int(x_pos.max()) + 1
    pixels = np.zeros((nrow, ncol, 4), dtype=np.uint8)
    for index in range(data.nrows):
        colour = fills[index]
        if colour is NA or colour is None:
            continue
        rgba = alpha_colour(colour, alpha[index])
        red, green, blue, a = _rgba(rgba)
        pixels[nrow - 1 - int(y_pos[index]), int(x_pos[index])] = (red, green, blue, a)
    return {
        "data": encode_rgba(ncol, nrow, pixels),
        "width_px": ncol,
        "height_px": nrow,
    }


def _rgba(colour: Any) -> tuple[int, int, int, int]:
    from ggcore.grobs import parse_colour

    try:
        return parse_colour(colour)
    except ValueError as exc:  # pragma: no cover - 解析失败只在颜色名写错时出现
        raise GeomError(f"geom_raster 的 fill 颜色无法解析：{colour!r}") from exc

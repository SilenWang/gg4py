"""区间族（M2-S2）：`geom_linerange` / `geom_errorbar` / `geom_errorbarh` /
`geom_pointrange` / `geom_crossbar` 的绘制。

照 4.0.3：

- `GeomLinerange$setup_params()`：`has_flipped_aes(..., range_is_orthogonal = TRUE)`；
  横向（`flipped_aes`）时长度轴在 x。`setup_data()` 只补 `flipped_aes` 列。
- `GeomLinerange$draw_panel()`：`flip_data` → `xend = x, y = ymin, yend = ymax` →
  翻回 → `GeomSegment`。等价于纵向 `(x, ymin)-(x, ymax)`、横向
  `(xmin, y)-(xmax, y)`。
- `GeomErrorbar$setup_data()`：`width` 走 `compute_data_size(..., zero = FALSE,
  discrete = TRUE)`（缺省 0.9），`xmin/xmax = x ∓ width/2`，然后丢掉 `width`。
  `setup_params()` 里 `height` 在横向时改名叫 `width`（R 会 inform 一句）。
- `GeomErrorbar$draw_panel()`：每行 8 个顶点（上帽、竖线、下帽），中间用 `NA`
  断开——等价于一条 `polylineGrob`（设备把 NaN 当断点）。
- `GeomPointrange$draw_panel()`：linerange + 点在 `(x, y)`，点大小 `size * fatten`
  （4.0.3 里 `fatten` 已弃用、固定 4）。
- `GeomErrorbarh`：4.0.3 起是 `geom_errorbar(orientation = "y")` 的软弃用别名；
  这里共用同一实现（方向仍由 `range_is_orthogonal` 推断）。
- `GeomCrossbar$draw_panel()`：箱体多边形 + 中位线（`linewidth * fatten`，
  `fatten = 2.5`）；`middle.*` / `box.*` 参数覆盖对应的图形参数。
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

import numpy as np

from ggcore.data import Column, ColumnTable
from ggcore.geom.base import (
    POINT_PER_MM,
    GeomError,
    GeomRenderer,
    alpha_colour,
    default_size,
    flip_data,
    lty_value,
    npc_values,
    put_column,
    table_numeric,
    table_values,
)
from ggcore.geom.point import PointRenderer
from ggcore.grobs import g_tree, null_grob, polygon_grob, polyline_grob, segments_grob
from ggcore.units import unit
from ggcore.viewport import NA, gpar

__all__ = [
    "CrossbarRenderer",
    "ErrorbarRenderer",
    "ErrorbarhRenderer",
    "LinerangeRenderer",
    "PointrangeRenderer",
]


def _flipped(data: Any) -> bool:
    if "flipped_aes" not in data:
        return False
    return bool(np.any(np.asarray(data.column("flipped_aes").values, dtype=bool)))


def _stroke_gp(data: Any, params: Any) -> dict[str, Any]:
    colours = table_values(data, "colour", "black")
    alpha = table_numeric(data, "alpha", default=math.nan)
    linewidth = table_numeric(data, "linewidth", default=0.5)
    linetype = table_values(data, "linetype", 1)
    return {
        "col": [alpha_colour(item, value) for item, value in zip(colours, alpha, strict=True)],
        "lwd": (linewidth * POINT_PER_MM).tolist(),
        "lty": lty_value(linetype[0]) if linetype else 1,
        "lineend": str(params.get("lineend", "butt")),
    }


def _width(data: ColumnTable, params: Any) -> np.ndarray:
    """`compute_data_size(data, params$width, default = 0.9, discrete = TRUE)`。"""
    if "width" in data:
        return table_numeric(data, "width", default=0.9)
    if params.get("width") is not None:
        return np.full(data.nrows, float(params["width"]))
    if params.get("_discrete_position"):
        return np.full(data.nrows, 0.9)
    return np.full(data.nrows, default_size(data, "x"))


class LinerangeRenderer(GeomRenderer):
    """`geom_linerange`：`(x, ymin) → (x, ymax)`（横向是 `(xmin, y) → (xmax, y)`）。"""

    name = "linerange"
    detect_flipped = True
    range_is_orthogonal = True

    def setup_params(
        self,
        data: ColumnTable,
        params: Any,
        *,
        raw: ColumnTable | None = None,
    ) -> dict[str, Any]:
        resolved = super().setup_params(data, params, raw=raw)
        if not resolved.get("flipped_aes"):
            names = set(data.names) | set(params)
            if not {"x", "ymin", "ymax"} <= names:
                raise GeomError("Either, x, ymin, and ymax or y, xmin, and xmax must be supplied.")
        return resolved

    def setup_data(self, data: ColumnTable, params: Any) -> ColumnTable:
        columns = [(name, data.column(name)) for name in data.names]
        put_column(
            columns,
            "flipped_aes",
            Column("bool", np.full(data.nrows, bool(params.get("flipped_aes", False)))),
        )
        return ColumnTable(columns, nrows=data.nrows)

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        data = build.data
        if data.nrows == 0:
            return null_grob(name=f"geom_{self.name}")
        flip = _flipped(data)
        if flip:
            x0 = npc_values(panel, data, "xmin", "x")
            x1 = npc_values(panel, data, "xmax", "x")
            y0 = y1 = npc_values(panel, data, "y", "y")
        else:
            x0 = x1 = npc_values(panel, data, "x", "x")
            y0 = npc_values(panel, data, "ymin", "y")
            y1 = npc_values(panel, data, "ymax", "y")
        return segments_grob(
            unit(x0.tolist(), "native"),
            unit(y0.tolist(), "native"),
            unit(x1.tolist(), "native"),
            unit(y1.tolist(), "native"),
            default_units="native",
            name=f"geom_{self.name}",
            gp=_stroke_gp(data, build.params),
        )


class ErrorbarRenderer(LinerangeRenderer):
    """`geom_errorbar`：上帽 + 竖线 + 下帽（8 个顶点一条折线，NA 断开）。"""

    name = "errorbar"

    def setup_params(
        self,
        data: ColumnTable,
        params: Any,
        *,
        raw: ColumnTable | None = None,
    ) -> dict[str, Any]:
        resolved = super().setup_params(data, params, raw=raw)
        if resolved.get("flipped_aes") and "height" in resolved and "width" not in resolved:
            resolved["width"] = resolved.pop("height")
        return resolved

    def setup_data(self, data: ColumnTable, params: Any) -> ColumnTable:
        flip = bool(params.get("flipped_aes", False))
        columns = [(name, data.column(name)) for name in data.names]
        put_column(columns, "flipped_aes", Column("bool", np.full(data.nrows, flip)))
        frame = flip_data(ColumnTable(columns, nrows=data.nrows), flip)
        width = _width(frame, params)
        x = table_numeric(frame, "x", default=float("nan"))
        columns = [(name, frame.column(name)) for name in frame.names]
        put_column(columns, "xmin", Column("float", x - width / 2.0))
        put_column(columns, "xmax", Column("float", x + width / 2.0))
        frame = ColumnTable(
            [(name, column) for name, column in columns if name != "width"],
            nrows=frame.nrows,
        )
        return flip_data(frame, flip)

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        data = build.data
        if data.nrows == 0:
            return null_grob(name=f"geom_{self.name}")
        if _flipped(data):
            # 横向：两顶帽在 x = xmin / xmax 上（沿类别轴 y 撑开），中间的线沿 x。
            xmin = npc_values(panel, data, "xmin", "x")
            xmax = npc_values(panel, data, "xmax", "x")
            xs = _interleave(xmax, xmax, xmax, xmin, xmin, xmin)
            ys = _interleave(
                npc_values(panel, data, "ymin", "y"),
                npc_values(panel, data, "ymax", "y"),
                npc_values(panel, data, "y", "y"),
                npc_values(panel, data, "y", "y"),
                npc_values(panel, data, "ymin", "y"),
                npc_values(panel, data, "ymax", "y"),
            )
        else:
            xmin = npc_values(panel, data, "xmin", "x")
            xmax = npc_values(panel, data, "xmax", "x")
            x = npc_values(panel, data, "x", "x")
            xs = _interleave(xmin, xmax, x, x, xmin, xmax)
            ys = _interleave(
                npc_values(panel, data, "ymax", "y"),
                npc_values(panel, data, "ymax", "y"),
                npc_values(panel, data, "ymax", "y"),
                npc_values(panel, data, "ymin", "y"),
                npc_values(panel, data, "ymin", "y"),
                npc_values(panel, data, "ymin", "y"),
            )
        # 一行一个 `polylineGrob`：IR 的 gpar 是**每个节点一份**，一行一条折线
        # 才能让逐行 colour / linewidth 生效（R 是把它们 `rep(each = 8)` 后交给
        # `GeomPath`，每个 id 组一份 gp，等价）。
        gp = _stroke_gp(data, build.params)
        grobs: list[Any] = []
        for index in range(data.nrows):
            row = slice(index * 8, (index + 1) * 8)
            grobs.append(
                polyline_grob(
                    unit(xs[row].tolist(), "native"),
                    unit(ys[row].tolist(), "native"),
                    id=[index + 1] * 8,
                    default_units="native",
                    name=f"geom_{self.name}",
                    gp=_single_row(gp, index),
                )
            )
        if len(grobs) == 1:
            return grobs[0]
        return g_tree(*grobs, name=f"geom_{self.name}")


def _single_row(gp: Mapping[str, Any], index: int) -> dict[str, Any]:
    return {
        name: (values[index] if isinstance(values, list) else values) for name, values in gp.items()
    }


def _interleave(*columns: np.ndarray) -> np.ndarray:
    """按行交错若干列，并在段与段之间插 `NaN`（R 的 `vec_interleave(..., NA, ...)`）。

    调用方给的每一列都是「一行一个值」；输出是每行 8 个顶点：
    `[c0, c1, NaN, c2, c3, NaN, c4, c5]`——`errorbar` 的两条帽线与中间的竖线。
    """
    count = np.asarray(columns[0]).size
    out = np.empty(count * 8, dtype=np.float64)
    out[0::8] = columns[0]
    out[1::8] = columns[1]
    out[2::8] = np.nan
    out[3::8] = columns[2]
    out[4::8] = columns[3]
    out[5::8] = np.nan
    out[6::8] = columns[4]
    out[7::8] = columns[5]
    return out


class ErrorbarhRenderer(ErrorbarRenderer):
    """`geom_errorbarh`：4.0.3 起是 `geom_errorbar(orientation = "y")` 的别名。"""

    name = "errorbarh"


class PointrangeRenderer(LinerangeRenderer):
    """`geom_pointrange`：linerange + 中点（点大小 `size * 4`）。"""

    name = "pointrange"

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        line = LinerangeRenderer.draw(self, geom, build, panel, coord, theme, metrics)
        data = build.data
        flip = _flipped(data)
        if ("xmin" if flip else "ymin") not in data:
            return line
        columns = [(name, data.column(name)) for name in data.names]
        size = table_numeric(data, "size", default=0.5) * 4.0
        put_column(columns, "size", Column("float", size))
        points = PointRenderer().draw(
            geom,
            SimpleNamespace(data=ColumnTable(columns, nrows=data.nrows), params=build.params),
            panel,
            coord,
            theme,
            metrics,
        )
        return g_tree(line, points, name="geom_pointrange")


class CrossbarRenderer(ErrorbarRenderer):
    """`geom_crossbar`：箱体多边形 + 中位线（`fatten = 2.5`）。"""

    name = "crossbar"

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        data = build.data
        if data.nrows == 0:
            return null_grob(name="geom_crossbar")
        for notch in ("ynotchlower", "ynotchupper"):
            if notch in data and bool(np.any(np.isfinite(table_numeric(data, notch)))):
                raise GeomError(
                    "geom_crossbar 的缺口（ynotchlower / ynotchupper）没有 IR 表达，"
                    "见 docs/notes/geom.md「未实现清单」"
                )
        params = build.params
        flip = _flipped(data)
        fills = table_values(data, "fill", NA)
        colours = table_values(data, "colour", "black")
        alpha = table_numeric(data, "alpha", default=math.nan)
        linewidth = table_numeric(data, "linewidth", default=0.5)
        linetype = table_values(data, "linetype", 1)
        lineend = str(params.get("lineend", "butt"))
        linejoin = str(params.get("linejoin", "mitre"))
        fatten = params.get("fatten")
        fatten = 2.5 if fatten is None else float(fatten)
        box_colour = params.get("box.colour") or params.get("box.color")
        box_linewidth = params.get("box.linewidth")
        box_linetype = params.get("box.linetype")
        middle_colour = params.get("middle.colour") or params.get("middle.color")
        middle_linewidth = params.get("middle.linewidth")
        middle_linetype = params.get("middle.linetype")
        if flip:
            across_low = npc_values(panel, data, "ymin", "y")
            across_high = npc_values(panel, data, "ymax", "y")
            length_low = npc_values(panel, data, "xmin", "x")
            length_high = npc_values(panel, data, "xmax", "x")
            middle = npc_values(panel, data, "y", "x")
        else:
            across_low = npc_values(panel, data, "xmin", "x")
            across_high = npc_values(panel, data, "xmax", "x")
            length_low = npc_values(panel, data, "ymin", "y")
            length_high = npc_values(panel, data, "ymax", "y")
            middle = npc_values(panel, data, "y", "y")

        def place(across: np.ndarray, length: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
            return (length, across) if flip else (across, length)

        boxes: list[Any] = []
        middle_grobs: list[Any] = []
        for index in range(data.nrows):
            xs, ys = place(
                np.array(
                    [across_low[index], across_low[index], across_high[index], across_high[index]]
                ),
                np.array(
                    [length_high[index], length_low[index], length_low[index], length_high[index]]
                ),
            )
            boxes.append(
                polygon_grob(
                    unit(xs.tolist(), "native"),
                    unit(ys.tolist(), "native"),
                    default_units="native",
                    name="geom_crossbar",
                    gp=gpar(
                        col=alpha_colour(
                            box_colour if box_colour is not None else colours[index],
                            alpha[index],
                        ),
                        fill=alpha_colour(fills[index], alpha[index]),
                        lwd=float(box_linewidth if box_linewidth is not None else linewidth[index])
                        * POINT_PER_MM,
                        lty=lty_value(
                            box_linetype if box_linetype is not None else linetype[index]
                        ),
                        lineend=lineend,
                        linejoin=linejoin,
                    ),
                )
            )
            mx, my = place(
                np.array([across_low[index], across_high[index]]),
                np.array([middle[index], middle[index]]),
            )
            middle_grobs.append(
                segments_grob(
                    unit(mx[0:1].tolist(), "native"),
                    unit(my[0:1].tolist(), "native"),
                    unit(mx[1:2].tolist(), "native"),
                    unit(my[1:2].tolist(), "native"),
                    default_units="native",
                    name="geom_crossbar",
                    gp=gpar(
                        col=alpha_colour(
                            middle_colour if middle_colour is not None else colours[index],
                            NA if middle_colour is not None else alpha[index],
                        ),
                        lwd=float(
                            middle_linewidth
                            if middle_linewidth is not None
                            else linewidth[index] * fatten
                        )
                        * POINT_PER_MM,
                        lty=lty_value(
                            middle_linetype if middle_linetype is not None else linetype[index]
                        ),
                        lineend=lineend,
                    ),
                )
            )
        return g_tree(*boxes, *middle_grobs, name="geom_crossbar")

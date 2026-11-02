"""`geom_boxplot` 的绘制（M1-7）。

照 4.0.3 的 `GeomBoxplot$draw_group()`（`notch = FALSE`、`staplewidth = 0`）：

- 两根须线：`(x, upper) → (x, ymax)` 与 `(x, lower) → (x, ymin)`；
- 箱体：`(xmin, upper) → (xmin, lower) → (xmax, lower) → (xmax, upper)` 的多边形
  （`fill` 吃 alpha、`col` 是描边）；
- 中位线：`(xmin, middle) → (xmax, middle)`，线宽是 `linewidth * fatten`（`fatten = 2`）；
- 离群点：`GeomPoint$draw_panel()`，shape / size 走 default aes。

`flipped_aes`（横向箱线）按 R 的做法：先把数据名翻成纵向（`flip_data`），画完再翻
回来，所以五个统计量在横向时走 `xmin/xlower/xmiddle/xupper/xmax`，纵向时走
`ymin/lower/middle/upper/ymax`。

`notch = TRUE` / `staplewidth != 0` 没有 IR 表达 → 明确报错（见
`docs/notes/geom.md`「未实现清单」）。
"""

from __future__ import annotations

import math
import re
from typing import Any

import numpy as np

from ggcore.data import Column, ColumnTable
from ggcore.geom.base import (
    POINT_PER_MM,
    STROKE_PER_MM,
    GeomError,
    GeomRenderer,
    alpha_colour,
    flip_data,
    lty_value,
    npc_values,
    table_numeric,
)
from ggcore.geom.point import translate_shape
from ggcore.grobs import g_tree, null_grob, points_grob, polygon_grob, segments_grob
from ggcore.units import unit
from ggcore.viewport import NA, gpar

__all__ = ["BoxplotRenderer"]


def _put(columns: list[tuple[str, Column]], name: str, column: Column) -> list[tuple[str, Column]]:
    for position, (key, _) in enumerate(columns):
        if key == name:
            columns[position] = (name, column)
            return columns
    columns.append((name, column))
    return columns


def _npc(panel: Any, values: np.ndarray, axis: str) -> np.ndarray:
    low, high = panel.x_range if axis == "x" else panel.y_range
    span = high - low
    if span == 0:
        raise GeomError(f"{axis} 面板范围跨度为 0，无法把箱线图映射到 npc")
    return (np.asarray(values, dtype=np.float64) - low) / span


class BoxplotRenderer(GeomRenderer):
    """`geom_boxplot`：五数 + 须线 + 离群点。"""

    name = "boxplot"
    detect_flipped = True

    def setup_data(self, data: ColumnTable, params: Any) -> ColumnTable:
        flip = bool(params.get("flipped_aes", False))
        columns = [(name, data.column(name)) for name in data.names]
        columns = _put(
            columns, "flipped_aes", Column("bool", np.full(data.nrows, flip, dtype=bool))
        )
        frame = flip_data(ColumnTable(columns, nrows=data.nrows), flip)
        if params.get("outliers") is False and "outliers" in frame:
            frame = ColumnTable(
                [(name, frame.column(name)) for name in frame.names if name != "outliers"],
                nrows=frame.nrows,
            )
        if "outliers" in frame and "ymin_final" not in frame:
            low = np.full(frame.nrows, math.nan)
            high = np.full(frame.nrows, math.nan)
            for index in range(frame.nrows):
                values = _outliers(frame, index)
                if values:
                    low[index] = min(values)
                    high[index] = max(values)
            columns = [(name, frame.column(name)) for name in frame.names]
            columns = _put(
                columns,
                "ymin_final",
                Column("float", np.fmin(low, table_numeric(frame, "ymin"))),
            )
            columns = _put(
                columns,
                "ymax_final",
                Column("float", np.fmax(high, table_numeric(frame, "ymax"))),
            )
            frame = ColumnTable(columns, nrows=frame.nrows)
        width = _width_column(frame, params, 0.9)
        x = table_numeric(frame, "x")
        if params.get("varwidth") and "relvarwidth" in frame:
            relative = table_numeric(frame, "relvarwidth", default=1.0)
            finite = relative[np.isfinite(relative)]
            maximum = float(finite.max()) if finite.size else 1.0
            relative = relative / maximum if maximum else relative
            low = x - relative * width / 2.0
            high = x + relative * width / 2.0
        else:
            low = x - width / 2.0
            high = x + width / 2.0
        columns = [(name, frame.column(name)) for name in frame.names]
        columns = _put(columns, "xmin", Column("float", low))
        columns = _put(columns, "xmax", Column("float", high))
        columns = [
            (name, column) for name, column in columns if name not in ("width", "relvarwidth")
        ]
        return flip_data(ColumnTable(columns, nrows=frame.nrows), flip)

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        params = build.params
        if params.get("notch"):
            raise GeomError(
                "geom_boxplot(notch = TRUE) 没有 IR 表达（缺口多边形），"
                "见 docs/notes/geom.md「未实现清单」"
            )
        if float(params.get("staplewidth", 0.0) or 0.0) != 0.0:
            raise GeomError(
                "geom_boxplot(staplewidth != 0) 没有 IR 表达（须帽），"
                "见 docs/notes/geom.md「未实现清单」"
            )
        data = build.data
        if data.nrows == 0:
            return null_grob(name="geom_boxplot")
        flip = (
            bool(np.any(np.asarray(data.column("flipped_aes").values)))
            if "flipped_aes" in data
            else False
        )
        # 纵向：分类轴 = x，长度轴 = y；横向反过来（R 的 flip_data）。
        across_axis = "y" if flip else "x"
        centre_name = "y" if flip else "x"
        across = npc_values(panel, data, centre_name, across_axis)
        if flip:
            hinge_low = npc_values(panel, data, "xlower", "x")
            hinge_high = npc_values(panel, data, "xupper", "x")
            middle = npc_values(panel, data, "xmiddle", "x")
            whisker_low = npc_values(panel, data, "xmin", "x")
            whisker_high = npc_values(panel, data, "xmax", "x")
            box_low = npc_values(panel, data, "ymin", "y")
            box_high = npc_values(panel, data, "ymax", "y")
        else:
            hinge_low = npc_values(panel, data, "lower", "y")
            hinge_high = npc_values(panel, data, "upper", "y")
            middle = npc_values(panel, data, "middle", "y")
            whisker_low = npc_values(panel, data, "ymin", "y")
            whisker_high = npc_values(panel, data, "ymax", "y")
            box_low = npc_values(panel, data, "xmin", "x")
            box_high = npc_values(panel, data, "xmax", "x")

        colours = _values(data, "colour", "grey20")
        fills = _values(data, "fill", "white")
        alpha = table_numeric(data, "alpha", default=math.nan)
        linewidth = table_numeric(data, "linewidth", default=0.5)
        linetype = _values(data, "linetype", 1)
        lineend = str(params.get("lineend", "butt"))
        linejoin = str(params.get("linejoin", "mitre"))
        fatten = float(params.get("fatten", 2.0))

        indices = np.arange(data.nrows)
        # 须线：每行两段（upper→ymax、lower→ymin）。
        whiskers = segments_grob(
            unit(np.concatenate([across, across]).tolist(), "native"),
            unit(np.concatenate([hinge_high, hinge_low]).tolist(), "native"),
            unit(np.concatenate([across, across]).tolist(), "native"),
            unit(np.concatenate([whisker_high, whisker_low]).tolist(), "native"),
            default_units="native",
            gp={
                "col": [
                    alpha_colour(colours[i], alpha[i])
                    for i in np.concatenate([indices, indices]).tolist()
                ],
                "lwd": (linewidth[np.concatenate([indices, indices])] * POINT_PER_MM).tolist(),
                "lty": lty_value(linetype[0]) if linetype else 1,
                "lineend": lineend,
                "linejoin": linejoin,
            },
        )

        # 箱体：IR 的 polygon 一个节点只带一份 gp，所以**每个箱一只 polygon**
        # （R 的 GeomCrossbar$draw_panel 也是逐 group 画）。
        boxes: list[Any] = []
        for index in range(data.nrows):
            low, high = float(box_low[index]), float(box_high[index])
            top, bottom = float(hinge_high[index]), float(hinge_low[index])
            boxes.append(
                polygon_grob(
                    unit([low, low, high, high, low], "native"),
                    unit([top, bottom, bottom, top, top], "native"),
                    default_units="native",
                    gp=gpar(
                        col=alpha_colour(colours[index], alpha[index]),
                        fill=alpha_colour(fills[index], alpha[index]),
                        lwd=float(linewidth[index]) * POINT_PER_MM,
                        lty=lty_value(linetype[index]),
                        lineend=lineend,
                        linejoin=linejoin,
                    ),
                )
            )

        median = segments_grob(
            unit(box_low.tolist(), "native"),
            unit(middle.tolist(), "native"),
            unit(box_high.tolist(), "native"),
            unit(middle.tolist(), "native"),
            default_units="native",
            gp={
                "col": colours,
                "lwd": (linewidth * fatten * POINT_PER_MM).tolist(),
                "lty": lty_value(linetype[0]) if linetype else 1,
                "lineend": lineend,
                "linejoin": linejoin,
            },
        )

        grobs: list[Any] = [whiskers, *boxes, median]
        grobs.extend(_outlier_points(panel, data, flip, across))
        return g_tree(*grobs, name="geom_boxplot")


def _outlier_points(panel: Any, data: ColumnTable, flip: bool, across: np.ndarray) -> list[Any]:
    """离群点：沿长度轴的值 → npc；colour / shape / size / stroke 走 default aes。

    IR 的 points 一个节点只带一份 gp，所以逐行一个 pointsGrob（与 R 逐 group
    调用 `GeomPoint$draw_panel()` 的结构一致）。
    """
    if "outliers" not in data:
        return []
    shapes = _values(data, "shape", 19.0)
    size = table_numeric(data, "size", default=1.5)
    stroke = table_numeric(data, "stroke", default=0.5)
    colours = _values(data, "colour", "grey20")
    alpha = table_numeric(data, "alpha", default=math.nan)
    out: list[Any] = []
    for index in range(data.nrows):
        values = _outliers(data, index)
        if not values:
            continue
        along = _npc(panel, np.array(values), "x" if flip else "y")
        xs = along.tolist() if flip else [float(across[index])] * len(values)
        ys = [float(across[index])] * len(values) if flip else along.tolist()
        out.append(
            points_grob(
                unit(xs, "native"),
                unit(ys, "native"),
                pch=translate_shape(shapes[index]) if shapes else 19,
                size=unit(float(size[index]) * POINT_PER_MM, "bigpts"),
                size_units="bigpts",
                default_units="native",
                gp=gpar(
                    col=alpha_colour(colours[index], alpha[index]),
                    fill=NA,
                    lwd=float(stroke[index]) * STROKE_PER_MM / 2.0,
                ),
            )
        )
    return out


def _outliers(data: ColumnTable, index: int) -> list[float]:
    """离群点列 → 该行的数值列表。

    当前 `ColumnTable` 没有「列表列」这一 kind（M1-8 的 `stat_boxplot` 会补）；
    绘制层接受三种写法：数值列（每行一个值）、`str` 列的 `1;2` / `c(1, 2)` /
    `[1, 2]` 分隔文本、以及缺失（没有离群点）。
    """
    if "outliers" not in data:
        return []
    column = data.column("outliers")
    if bool(np.asarray(column.na_mask, dtype=bool)[index]):
        return []
    raw = column.values.tolist()[index]
    if isinstance(raw, (int, float, np.integer, np.floating)):
        number = float(raw)
        return [number] if math.isfinite(number) else []
    text = str(raw)
    numbers = re.findall(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", text)
    return [float(item) for item in numbers if math.isfinite(float(item))]


def _width_column(table: ColumnTable, params: Any, default: float) -> np.ndarray:
    if "width" in table:
        return table_numeric(table, "width", default=default)
    value = params.get("width")
    if value is None:
        return np.full(table.nrows, float(default))
    return np.full(table.nrows, float(value))


def _values(data: ColumnTable, name: str, default: Any) -> list[Any]:
    if name not in data:
        return [default] * data.nrows
    column = data.column(name)
    values = column.values.tolist()
    mask = np.asarray(column.na_mask, dtype=bool).tolist()
    return [NA if missing else value for value, missing in zip(values, mask, strict=True)]

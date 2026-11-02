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
    default_size,
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
        # R `compute_data_size(data, default = 0.9, zero = FALSE, discrete = TRUE)`：
        # 离散位置恒为 0.9；连续位置是 resolution(x) * 0.9（不是写死的 0.9）。
        default_width = 0.9 if params.get("_discrete_position") else default_size(frame, "x")
        width = _width_column(frame, params, default_width)
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

        def axes(
            across_values: np.ndarray, length_values: np.ndarray
        ) -> tuple[np.ndarray, np.ndarray]:
            """（粗细轴, 长度轴）→ 页面的（x, y）：纵向粗细沿 x，横向反过来。

            `flip_data()` 之后横向下 x 是长度轴、y 是粗细轴；须线 / 箱体 / 中位线
            都在这一对坐标上拼，所以只在这一处对换（R 的 `GeomBoxplot$draw_group()`
            同样先把两组值算好再按 `flipped_aes` 摆位置）。
            """
            if flip:
                return length_values, across_values
            return across_values, length_values

        # 须线：每行两段（upper→ymax、lower→ymin）。
        wx1, wy1 = axes(across, hinge_high)
        wx2, wy2 = axes(across, hinge_low)
        wx3, wy3 = axes(across, whisker_high)
        wx4, wy4 = axes(across, whisker_low)
        whiskers = segments_grob(
            unit(np.concatenate([wx1, wx2]).tolist(), "native"),
            unit(np.concatenate([wy1, wy2]).tolist(), "native"),
            unit(np.concatenate([wx3, wx4]).tolist(), "native"),
            unit(np.concatenate([wy3, wy4]).tolist(), "native"),
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
            xs, ys = axes(
                np.array([low, low, high, high, low]),
                np.array([top, bottom, bottom, top, top]),
            )
            boxes.append(
                polygon_grob(
                    unit(xs.tolist(), "native"),
                    unit(ys.tolist(), "native"),
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

        mx1, my1 = axes(box_low, middle)
        mx2, my2 = axes(box_high, middle)
        median = segments_grob(
            unit(mx1.tolist(), "native"),
            unit(my1.tolist(), "native"),
            unit(mx2.tolist(), "native"),
            unit(my2.tolist(), "native"),
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
        # `GeomPoint$draw_panel()`：fontsize = size * .pt + stroke * .stroke / 2。
        size_pt = float(size[index]) * POINT_PER_MM + float(stroke[index]) * STROKE_PER_MM / 2.0
        out.append(
            points_grob(
                unit(xs, "native"),
                unit(ys, "native"),
                pch=translate_shape(shapes[index]) if shapes else 19,
                size=unit(size_pt, "bigpts"),
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

    当前 `ColumnTable` 没有「列表列」这一 kind（`stat_boxplot` 产 `c(…)` 文本）；
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

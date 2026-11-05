"""分布 / 2D 族 geom 的绘制（M2-7 长尾 B）。

本模块只做**绘制**：统计量（`stat_density` / `stat_ydensity` / `stat_bindot` /
`stat_bin_2d` / `stat_bin_hex` / `stat_contour` / `stat_density_2d` / `stat_qq` /
`stat_quantile` / `stat_function` / `stat_sum`）归 stat 侧的任务，这里消费它们
输出的列（逐列口径见 `docs/notes/stat.md` 与 `docs/notes/geom.md`）。

| geom | R 父类 | 绘制口径 |
| --- | --- | --- |
| `density` | `GeomDensity` → `GeomArea` | 与 area 同一多边形，`outline.type = "upper"` |
| `violin` | `GeomViolin` | 按 `violinwidth` 收窄边界，闭合多边形（可选分位线） |
| `dotplot` | `GeomDotplot` | `count` 展开成点，`stackpos` 沿堆叠轴偏移，圆半径按另一轴 |
| `hex` | `GeomHex` | 每行一个六边形（`hexbin::hexcoords()` 的 6 个顶点） |
| `bin2d` / `bin_2d` | `GeomBin2d` → `GeomTile` | `x/y/width/height` → 四角，画矩形 |
| `contour` | `GeomContour` → `GeomPath` | 每个 `group` 一条折线 |
| `contour_filled` | `GeomContourFilled` → `GeomPolygon` | 每 band 一条带洞路径 |
| `density_2d` / `density2d` | `GeomDensity2d` → `GeomPath` | 同 contour，默认 `accent` 色 |
| `density_2d_filled` / `density2d_filled` | `GeomDensity2dFilled` | 同 contour_filled |
| `qq` | `StatQq` + `GeomPoint` | 点（默认色点） |
| `qq_line` | `StatQqLine` + `GeomPath` | 折线 |
| `quantile` | `GeomQuantile` → `GeomPath` | 折线（`accent` 色） |
| `function` | `GeomFunction` → `GeomPath` | 折线；多个 group 时发警告 |
| `count` | `GeomPoint` + `StatSum` | 点（count 走 stat 的 `size = after_stat(n)`） |
| `jitter` | `GeomPoint` + `position_jitter` | 点（抖动在 position 阶段） |

2D 等值带的填充语义：`geom_contour_filled` 的 `fill` 由 `stat_contour_filled`
给的 `level`（factor）映射，每个 band 一个 `group`；band 内部的洞用 `subgroup`
拆成多条子路径，按 `rule = "evenodd"` 填充（R `GeomPolygon$draw_panel()`）。
"""

from __future__ import annotations

import math
import warnings
from dataclasses import replace
from typing import Any

import numpy as np

from ggcore.build import BuildWarning
from ggcore.data import Column, ColumnTable
from ggcore.geom.bar import AreaRenderer, _munch_rects
from ggcore.geom.base import (
    POINT_PER_MM,
    GeomError,
    GeomRenderer,
    _is_discrete,
    alpha_colour,
    default_size,
    flip_data,
    lty_value,
    munch_xy,
    npc_values,
    resolution,
    row_slice,
    table_numeric,
)
from ggcore.geom.line import PathRenderer, _values
from ggcore.geom.point import PointRenderer
from ggcore.grobs import (
    circle_grob,
    g_tree,
    null_grob,
    path_grob,
    polygon_grob,
    polyline_grob,
    rect_grob,
)
from ggcore.units import unit
from ggcore.viewport import NA, gpar

__all__ = [
    "Bin2dRenderer",
    "ContourFilledRenderer",
    "ContourRenderer",
    "CountRenderer",
    "Density2dFilledRenderer",
    "Density2dRenderer",
    "DensityRenderer",
    "DotplotRenderer",
    "FunctionRenderer",
    "HexRenderer",
    "JitterRenderer",
    "QqLineRenderer",
    "QqRenderer",
    "QuantileRenderer",
    "ViolinRenderer",
]

#: 主题 `geom` 元素的默认色（`theme_grey()$geom`，4.0.3 的 `from_theme(...)`）。
INK = "black"
PAPER = "white"
ACCENT = "#3366FF"
GREY20 = "#333333"
GREY35 = "#595959"
GREY80 = "#808080"


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------


def _put(columns: list[tuple[str, Column]], name: str, column: Column) -> list[tuple[str, Column]]:
    for position, (key, _) in enumerate(columns):
        if key == name:
            columns[position] = (name, column)
            return columns
    columns.append((name, column))
    return columns


def _width_column(table: ColumnTable, params: Any, default: float) -> np.ndarray:
    """`compute_data_size()` 的宽度：数据列 > 参数 > 缺省。"""
    if "width" in table:
        return table_numeric(table, "width", default=default)
    value = params.get("width")
    if value is None:
        return np.full(table.nrows, float(default))
    return np.full(table.nrows, float(value))


def _group_keys(data: ColumnTable) -> list[Any]:
    """分组键（`group` 可以是 str 列的因子水平，也可以是数值）。"""
    if "group" not in data:
        return [0] * data.nrows
    column = data.column("group")
    values = column.values.tolist()
    mask = np.asarray(column.na_mask, dtype=bool).tolist()
    return [None if missing else value for value, missing in zip(values, mask, strict=True)]


def _group_rows(data: ColumnTable) -> list[tuple[Any, np.ndarray]]:
    """按 `group` 拆行，保持首次出现顺序。"""
    keys = _group_keys(data)
    order: list[Any] = []
    buckets: dict[Any, list[int]] = {}
    for index, key in enumerate(keys):
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(index)
    return [(key, np.asarray(buckets[key], dtype=np.int64)) for key in order]


def _axis_ratio(panel: Any) -> float:
    """面板宽/高比（英寸）：`geom_dotplot` 的 mm 直径在两根轴之间换算要用。"""
    width = getattr(panel, "panel_width_in", None)
    height = getattr(panel, "panel_height_in", None)
    if width and height:
        return float(width) / float(height)
    return 1.0


# ---------------------------------------------------------------------------
# density
# ---------------------------------------------------------------------------


class DensityRenderer(AreaRenderer):
    """`geom_density`：与 `geom_area` 同一多边形，默认只描上沿。"""

    name = "density"
    detect_flipped = True
    ambiguous_flipped = True

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        # `geom_density(outline.type = "upper")` 是构造器里写死的默认参数（R 的
        # `make_constructor(..., outline.type = "upper")`），不是 aes。
        if "outline.type" not in (build.params or {}):
            build = replace(build, params={**dict(build.params or {}), "outline.type": "upper"})
        return super().draw(geom, build, panel, coord, theme, metrics)


# ---------------------------------------------------------------------------
# violin
# ---------------------------------------------------------------------------


class ViolinRenderer(GeomRenderer):
    """`geom_violin`：按 `violinwidth` 收窄的闭合多边形（+ 可选分位数线）。"""

    name = "violin"
    detect_flipped = True
    ambiguous_flipped = True

    def setup_data(self, data: ColumnTable, params: Any) -> ColumnTable:
        flip = bool(params.get("flipped_aes", False))
        columns = [(name, data.column(name)) for name in data.names]
        columns = _put(
            columns, "flipped_aes", Column("bool", np.full(data.nrows, flip, dtype=bool))
        )
        frame = flip_data(ColumnTable(columns, nrows=data.nrows), flip)
        default_width = 0.9 if params.get("_discrete_position") else default_size(frame, "x")
        width = _width_column(frame, params, default_width)
        x = table_numeric(frame, "x")
        columns = [(name, frame.column(name)) for name in frame.names]
        columns = _put(columns, "xmin", Column("float", x - width / 2.0))
        columns = _put(columns, "xmax", Column("float", x + width / 2.0))
        columns = [(name, column) for name, column in columns if name != "width"]
        return flip_data(ColumnTable(columns, nrows=frame.nrows), flip)

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        data = build.data
        if data.nrows == 0:
            return null_grob(name="geom_violin")
        flip = (
            bool(np.any(np.asarray(data.column("flipped_aes").values)))
            if "flipped_aes" in data
            else False
        )
        frame = flip_data(data, flip)
        colours = _values(frame, "colour", GREY20)
        fills = _values(frame, "fill", PAPER)
        alpha = table_numeric(frame, "alpha", default=math.nan)
        linewidth = table_numeric(frame, "linewidth", default=0.5)
        linetype = _values(frame, "linetype", 1)
        violinwidth = table_numeric(frame, "violinwidth", default=1.0)
        lineend = str(build.params.get("lineend", "butt"))
        linejoin = str(build.params.get("linejoin", "round"))
        linemitre = float(build.params.get("linemitre", 10.0))
        # `geom_violin()` 在 4.0.3 里把 `quantile.*` 收成 `quantile_gp` 塞进图层
        # 参数（`quantile.color` 优先于 `quantile.colour`，`linetype` 缺省 0 =
        # 不画分位线）。绘制层拿到的是图层参数，所以在这里解析同一口径。
        quantile_colour = build.params.get("quantile.color")
        if quantile_colour is None:
            quantile_colour = build.params.get("quantile.colour")
        quantile_linetype = build.params.get("quantile.linetype", 0)
        quantile_linewidth = build.params.get("quantile.linewidth")

        grobs: list[Any] = []
        for _key, rows in _group_rows(frame):
            if rows.size == 0:
                continue
            order = rows[
                np.argsort(table_numeric(row_slice(frame, rows), "y", default=0.0), kind="stable")
            ]
            xs = table_numeric(frame, "x")[order]
            ys = table_numeric(frame, "y")[order]
            xmins = table_numeric(frame, "xmin")[order]
            xmaxs = table_numeric(frame, "xmax")[order]
            widths = violinwidth[order]
            left = xs - widths * (xs - xmins)
            right = xs + widths * (xmaxs - xs)
            poly_x = np.concatenate([left, right[::-1], left[:1]])
            poly_y = np.concatenate([ys, ys[::-1], ys[:1]])
            if flip:
                px, py = panel.project_xy(poly_y, poly_x)
            else:
                px, py = panel.project_xy(poly_x, poly_y)
            first = int(order[0])
            grobs.append(
                polygon_grob(
                    px.tolist(),
                    py.tolist(),
                    default_units="native",
                    name="geom_violin",
                    gp=gpar(
                        fill=alpha_colour(fills[first], alpha[first]),
                        col=alpha_colour(colours[first], alpha[first]),
                        lwd=float(linewidth[first]) * POINT_PER_MM,
                        lty=lty_value(linetype[first]),
                        lineend=lineend,
                        linejoin=linejoin,
                        linemitre=linemitre,
                    ),
                )
            )
            if "quantile" in frame and quantile_linetype not in (0, "blank", None):
                grobs.extend(
                    _violin_quantiles(
                        frame,
                        panel,
                        order,
                        left,
                        right,
                        ys,
                        flip,
                        colour=quantile_colour,
                        linetype=quantile_linetype,
                        linewidth=quantile_linewidth,
                    )
                )
        if not grobs:
            return null_grob(name="geom_violin")
        if len(grobs) == 1:
            return grobs[0]
        return g_tree(*grobs, name="geom_violin")


def _violin_quantiles(
    frame: ColumnTable,
    panel: Any,
    order: np.ndarray,
    left: np.ndarray,
    right: np.ndarray,
    ys: np.ndarray,
    flip: bool,
    *,
    colour: Any,
    linetype: Any,
    linewidth: Any,
) -> list[Any]:
    """`create_quantile_segment_frame()`：每个分位数一条横线（左右边界之间）。"""
    quantiles = table_numeric(frame, "quantile", default=math.nan)[order]
    base_colour = _values(frame, "colour", GREY20)[int(order[0])]
    base_width = table_numeric(frame, "linewidth", default=0.5)[int(order[0])]
    grobs: list[Any] = []
    seen: dict[float, None] = {}
    for index, value in enumerate(quantiles.tolist()):
        if not math.isfinite(value):
            continue
        seen.setdefault(float(value), None)
        segment_x = [left[index], right[index]]
        segment_y = [ys[index], ys[index]]
        if flip:
            px, py = panel.project_xy(segment_y, segment_x)
        else:
            px, py = panel.project_xy(segment_x, segment_y)
        grobs.append(
            polyline_grob(
                unit(px.tolist(), "native"),
                unit(py.tolist(), "native"),
                default_units="native",
                gp=gpar(
                    col=alpha_colour(colour if colour is not None else base_colour, None),
                    lwd=float(linewidth if linewidth is not None else base_width) * POINT_PER_MM,
                    lty=lty_value(linetype),
                ),
                name="geom_violin-quantile",
            )
        )
    return grobs


# ---------------------------------------------------------------------------
# dotplot
# ---------------------------------------------------------------------------


def _stack_functions(stackdir: str) -> tuple[Any, float, float]:
    """`GeomDotplot$setup_data()` 的 `stackdots` 与堆叠轴范围。"""
    if stackdir == "up":
        return (lambda a: a - 0.5), 0.0, 1.0
    if stackdir == "down":
        return (lambda a: -a + 0.5), -1.0, 0.0
    if stackdir == "center":
        return (lambda a: a - 1.0 - max(a - 1.0) / 2.0), -0.5, 0.5
    if stackdir == "centerwhole":
        return (lambda a: a - 1.0 - math.floor(max(a - 1.0) / 2.0)), -0.5, 0.5
    raise GeomError(f"stackdir 只能是 up / down / center / centerwhole，收到 {stackdir!r}")


class DotplotRenderer(GeomRenderer):
    """`geom_dotplot`：`count` 展开成点，沿堆叠轴按 `stackpos` 偏移。"""

    name = "dotplot"
    detect_flipped = False

    def setup_params(
        self, data: ColumnTable, params: Any, *, raw: ColumnTable | None = None
    ) -> dict[str, Any]:
        resolved = super().setup_params(data, params, raw=raw)
        source = raw if raw is not None else data
        # R 的 `is_mapped_discrete()`：只有 binaxis = "x" 时的 `y` 用得上（离散
        # y 的堆叠从该水平的位置起算）。映射前的列类型是唯一可靠来源。
        for axis in ("x", "y"):
            column = source.column(axis) if axis in source else None
            resolved[f"_discrete_{axis}"] = _is_discrete(column)
        return resolved

    def setup_data(self, data: ColumnTable, params: Any) -> ColumnTable:
        if data.nrows == 0:
            return data
        binaxis = str(params.get("binaxis", "x") or "x")
        if binaxis not in ("x", "y"):
            raise GeomError(f"binaxis 只能是 'x' 或 'y'，收到 {binaxis!r}")
        stackdir = str(params.get("stackdir", "up") or "up")
        stackfn, stackmin, stackmax = _stack_functions(stackdir)
        stackgroups = bool(params.get("stackgroups", False))
        width = _width_column(data, params, 0.9)
        columns = [(name, data.column(name)) for name in data.names]
        columns = _put(columns, "width", Column("float", width))
        table = ColumnTable(columns, nrows=data.nrows)
        count = table_numeric(table, "count", default=1.0)
        count = np.where(np.isfinite(count), np.maximum(count, 0), 0.0)
        # 索引数组一律 `np.intp`：`np.repeat()` 会把 repeats 按 **safe** 规则转成
        # 索引 dtype，而 wasm32（Pyodide）的 `np.intp` 是 int32——传 int64 数组会直接
        # `TypeError`，同一份代码在浏览器里就跑不起来（SIL-824 的全量 case 门禁
        # 发现的问题）。intp 在两侧都是「索引该有的宽度」，值域也够（行数 < 2^31）。
        expanded = np.repeat(np.arange(table.nrows, dtype=np.intp), count.astype(np.intp))
        table = row_slice(table, expanded)
        table = ColumnTable([(name, table.column(name)) for name in table.names], nrows=table.nrows)
        # 行数变了：width 也要按展开后的行取（R 的 `data[rep(...), ]` 之后）。
        width = table_numeric(table, "width", default=0.9)
        # R 的 `plyvars = c(binaxis, "PANEL")`；`stackgroups = FALSE` 时再按 group
        # 拆，`stackaxis == "x"`（binaxis = "y"）时再按 x 拆。
        ply_names = [binaxis]
        if "PANEL" in table:
            ply_names.append("PANEL")
        if not stackgroups:
            ply_names.append("group")
        if binaxis == "y":
            ply_names.append("x")
        ply_values: list[list[Any]] = []
        for name in ply_names:
            column = table.column(name)
            mask = np.asarray(column.na_mask, dtype=bool).tolist()
            ply_values.append(
                [
                    ("<na>",) if missing else value
                    for value, missing in zip(column.values.tolist(), mask, strict=True)
                ]
            )
        ply_keys = list(zip(*ply_values, strict=True))
        stackpos = np.zeros(table.nrows, dtype=np.float64)
        countidx = np.zeros(table.nrows, dtype=np.float64)
        buckets: dict[Any, list[int]] = {}
        for index, key in enumerate(ply_keys):
            buckets.setdefault(key, []).append(index)
        for rows in buckets.values():
            values = np.arange(1, len(rows) + 1, dtype=np.float64)
            countidx[rows] = values
            stackpos[rows] = stackfn(values)
        columns = [(name, table.column(name)) for name in table.names]
        columns = _put(columns, "countidx", Column("float", countidx))
        columns = _put(columns, "stackpos", Column("float", stackpos))
        x = table_numeric(table, "x")
        y = table_numeric(table, "y")
        binwidth = table_numeric(table, "binwidth", default=0.0)
        if binaxis == "x":
            yoffset = y if bool(params.get("_discrete_y", False)) else np.zeros(table.nrows)
            columns = _put(columns, "xmin", Column("float", x - binwidth / 2.0))
            columns = _put(columns, "xmax", Column("float", x + binwidth / 2.0))
            columns = _put(columns, "ymin", Column("float", yoffset + stackmin))
            columns = _put(columns, "ymax", Column("float", yoffset + stackmax))
            columns = _put(columns, "y", Column("float", yoffset))
        else:
            low = np.full(table.nrows, math.nan)
            high = np.full(table.nrows, math.nan)
            # R 的 `dapply(data, c("group", "PANEL"), …)`：每个面板的每组一条
            # ymin / ymax（跨面板混在一起会把范围拉大）。
            panel_values = (
                np.asarray(table.column("PANEL").values).tolist()
                if "PANEL" in table
                else [0] * table.nrows
            )
            group_values = (
                np.asarray(table.column("group").values).tolist()
                if "group" in table
                else [0] * table.nrows
            )
            buckets_panel: dict[Any, list[int]] = {}
            for index, key in enumerate(zip(group_values, panel_values, strict=True)):
                buckets_panel.setdefault(key, []).append(index)
            for rows_list in buckets_panel.values():
                rows = np.asarray(rows_list, dtype=np.int64)
                values = y[rows]
                low[rows] = np.nanmin(values) - binwidth[rows][0] / 2.0
                high[rows] = np.nanmax(values) + binwidth[rows][0] / 2.0
            columns = _put(columns, "ymin", Column("float", low))
            columns = _put(columns, "ymax", Column("float", high))
            columns = _put(columns, "xmin", Column("float", x + width * stackmin))
            columns = _put(columns, "xmax", Column("float", x + width * stackmax))
        return ColumnTable(columns, nrows=table.nrows)

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        data = build.data
        if data.nrows == 0:
            return null_grob(name="geom_dotplot")
        if not getattr(panel, "is_linear", True):
            warnings.warn(
                "geom_dotplot does not work properly with non-linear coordinates.",
                BuildWarning,
                stacklevel=2,
            )
        binaxis = str(build.params.get("binaxis", "x") or "x")
        stackdir = str(build.params.get("stackdir", "up") or "up")
        stackratio = float(build.params.get("stackratio", 1.0) or 1.0)
        dotsize = float(build.params.get("dotsize", 1.0) or 1.0)
        x = npc_values(panel, data, "x", "x")
        y = npc_values(panel, data, "y", "y")
        stackpos = table_numeric(data, "stackpos", default=0.0)
        binwidth = table_numeric(data, "binwidth", default=0.0)
        colours = _values(data, "colour", INK)
        fills = _values(data, "fill", INK)
        alpha = table_numeric(data, "alpha", default=math.nan)
        stroke = table_numeric(data, "stroke", default=1.0)
        linetype = _values(data, "linetype", 1)
        # R 的 `draw_group()` 先按 coord 翻转 binaxis：coord_flip 下 bin 轴与堆叠轴
        # 都落在屏幕的对侧，直径取「非堆叠轴」（`dotdia` 的 npc 口径）。
        flipped = bool(getattr(panel, "flipped", False))
        if flipped:
            binaxis = "y" if binaxis == "x" else "x"
        if binaxis == "x":
            span = float(np.asarray(panel.x_range, dtype=np.float64)[1] - panel.x_range[0])
            # 偏移落在堆叠轴（屏幕 y）上是绝对长度；x 的 npc → y 的 npc 乘宽高比。
            ratio = _axis_ratio(panel)
            r_axis = "x"
        else:
            span = float(np.asarray(panel.y_range, dtype=np.float64)[1] - panel.y_range[0])
            ratio = 1.0 / _axis_ratio(panel)
            r_axis = "y"
        stackoffset = (1.0 - stackratio) / 2.0 if stackdir in ("up", "down") else 0.0
        if stackdir == "down":
            stackoffset = -stackoffset
        # R 的 `draw_group()` 逐组画：一组的点直径相同（binwidth 组内恒定），
        # `lty` / `lwd` 在组内也恒定，所以每组一个 circleGrob。
        grobs: list[Any] = []
        for _key, rows in _group_rows(data):
            first = int(rows[0])
            radius = dotsize * float(binwidth[first]) / span / 2.0 if span else 0.0
            offset = radius * 2.0 * (stackpos[rows] * stackratio + stackoffset) * ratio
            if binaxis == "x":
                dot_x = x[rows]
                dot_y = y[rows] + offset
            else:
                dot_x = x[rows] + offset
                dot_y = y[rows]
            grobs.append(
                circle_grob(
                    unit(dot_x.tolist(), "native"),
                    unit(dot_y.tolist(), "native"),
                    r=unit(radius, "npc"),
                    r_axis=r_axis,
                    default_units="native",
                    gp={
                        "col": alpha_colour(colours[first], alpha[first]),
                        "fill": alpha_colour(fills[first], alpha[first]),
                        "lwd": float(stroke[first]),
                        "lty": lty_value(linetype[first]),
                    },
                )
            )
        return g_tree(*grobs, name="geom_dotplot")


# ---------------------------------------------------------------------------
# hex
# ---------------------------------------------------------------------------


#: `hexbin::hexcoords(dx, dy, n = 1)` 的 6 个顶点（dx = width/2，dy = height/√3/2）。
def _hex_offsets(dx: float, dy: float) -> tuple[list[float], list[float]]:
    return (
        [dx, dx, 0.0, -dx, -dx, 0.0],
        [dy, -dy, -2.0 * dy, -dy, dy, 2.0 * dy],
    )


class HexRenderer(GeomRenderer):
    """`geom_hex`：每个 bin 一个六边形，`fill` 逐行作用到整个多边形。"""

    name = "hex"

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        data = build.data
        if data.nrows == 0:
            return null_grob(name="geom_hex")
        width = table_numeric(data, "width", default=math.nan)
        height = table_numeric(data, "height", default=math.nan)
        x = table_numeric(data, "x")
        y = table_numeric(data, "y")
        if np.isfinite(width[0]):
            dx = float(width[0]) / 2.0
        else:
            dx = resolution(x)
        if np.isfinite(height[0]):
            dy = float(height[0]) / math.sqrt(3.0) / 2.0
        else:
            dy = resolution(y) / math.sqrt(3.0) / 2.0 * 1.15
        offsets_x, offsets_y = _hex_offsets(dx, dy)
        colours = _values(data, "colour", NA)
        fills = _values(data, "fill", GREY80)
        alpha = table_numeric(data, "alpha", default=math.nan)
        linewidth = table_numeric(data, "linewidth", default=0.5)
        linetype = _values(data, "linetype", 1)
        lineend = str(build.params.get("lineend", "butt"))
        linejoin = str(build.params.get("linejoin", "mitre"))
        linemitre = float(build.params.get("linemitre", 10.0))

        polygons: list[Any] = []
        styles: dict[tuple[Any, ...], list[int]] = {}
        for index in range(data.nrows):
            if not (math.isfinite(float(x[index])) and math.isfinite(float(y[index]))):
                continue
            style = (
                colours[index],
                alpha_colour(fills[index], alpha[index]),
                round(float(linewidth[index]), 12),
                lty_value(linetype[index]),
            )
            styles.setdefault(style, []).append(index)
        for (colour, fill, lwd, lty), rows in styles.items():
            poly_x: list[float] = []
            poly_y: list[float] = []
            for index in rows:
                for ox, oy in zip(offsets_x, offsets_y, strict=True):
                    poly_x.append(float(x[index]) + ox)
                    poly_y.append(float(y[index]) + oy)
            # 上游 `GeomHex$draw_group()` 用的是 `coord$transform()`（**逐个顶点**
            # 投影，不做 `coord_munch()` 的细分）：六边形的边在非线性坐标下仍是
            # 直线，而不是弧。`id.lengths = rep.int(6, n)` 也说明每个六边形是
            # 独立的多边形。
            px, py = panel.project_xy(np.asarray(poly_x), np.asarray(poly_y))
            ids = [(position // 6) + 1 for position in range(len(poly_x))]
            polygons.append(
                polygon_grob(
                    px.tolist(),
                    py.tolist(),
                    id=ids,
                    default_units="native",
                    gp=gpar(
                        col=colour,
                        fill=fill,
                        lwd=float(lwd) * POINT_PER_MM,
                        lty=lty,
                        lineend=lineend,
                        linejoin=linejoin,
                        linemitre=linemitre,
                    ),
                )
            )
        if not polygons:
            return null_grob(name="geom_hex")
        if len(polygons) == 1:
            return polygons[0]
        return g_tree(*polygons, name="geom_hex")


def _repeat(value: Any, count: int) -> list[Any]:
    return [value] * count


# ---------------------------------------------------------------------------
# bin2d / bin_2d（GeomTile）
# ---------------------------------------------------------------------------


class Bin2dRenderer(GeomRenderer):
    """`geom_bin_2d`：`stat_bin_2d` 的输出（`x/y/width/height`）画矩形。"""

    name = "bin2d"
    non_missing_aes = ("xmin", "xmax", "ymin", "ymax")

    def setup_data(self, data: ColumnTable, params: Any) -> ColumnTable:
        if data.nrows == 0:
            return data
        width = _width_column(data, params, 1.0)
        height = (
            table_numeric(data, "height", default=1.0)
            if "height" in data
            else np.full(data.nrows, float(params.get("height", 1.0) or 1.0))
        )
        x = table_numeric(data, "x")
        y = table_numeric(data, "y")
        columns = [(name, data.column(name)) for name in data.names]
        columns = _put(columns, "xmin", Column("float", x - width / 2.0))
        columns = _put(columns, "xmax", Column("float", x + width / 2.0))
        columns = _put(columns, "ymin", Column("float", y - height / 2.0))
        columns = _put(columns, "ymax", Column("float", y + height / 2.0))
        columns = [(name, column) for name, column in columns if name not in ("width", "height")]
        return ColumnTable(columns, nrows=data.nrows)

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        data = build.data
        if data.nrows == 0:
            return null_grob(name="geom_bin_2d")
        xmin = npc_values(panel, data, "xmin", "x")
        xmax = npc_values(panel, data, "xmax", "x")
        ymin = npc_values(panel, data, "ymin", "y")
        ymax = npc_values(panel, data, "ymax", "y")
        fills = _values(data, "fill", GREY20)
        colours = _values(data, "colour", NA)
        alpha = table_numeric(data, "alpha", default=math.nan)
        linewidth = table_numeric(data, "linewidth", default=0.2)
        linetype = _values(data, "linetype", 1)
        lineend = str(build.params.get("lineend", "butt"))
        linejoin = str(build.params.get("linejoin", "mitre"))
        if not getattr(panel, "is_linear", True):
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
                name="geom_bin_2d",
            )
        return rect_grob(
            x=((xmin + xmax) / 2.0).tolist(),
            y=((ymin + ymax) / 2.0).tolist(),
            width=(xmax - xmin).tolist(),
            height=(ymax - ymin).tolist(),
            just="centre",
            default_units="native",
            name="geom_bin_2d",
            gp={
                "col": colours,
                "fill": [alpha_colour(fill, a) for fill, a in zip(fills, alpha, strict=True)],
                "lwd": (linewidth * POINT_PER_MM).tolist(),
                "lty": lty_value(linetype[0]) if linetype else 1,
                "lineend": lineend,
                "linejoin": linejoin,
            },
        )


# ---------------------------------------------------------------------------
# contour / density_2d（线）
# ---------------------------------------------------------------------------


class ContourRenderer(PathRenderer):
    """`geom_contour`：`stat_contour` 的 `group` 每组一条折线。"""

    name = "contour"
    non_missing_aes = ("linewidth", "colour", "linetype")


class Density2dRenderer(ContourRenderer):
    """`geom_density_2d`：与 contour 同一绘制路径（默认 `accent` 色）。"""

    name = "density_2d"


# ---------------------------------------------------------------------------
# contour_filled / density_2d_filled（填充带）
# ---------------------------------------------------------------------------


class ContourFilledRenderer(GeomRenderer):
    """`geom_contour_filled`：每个 band 一条带洞路径（`subgroup` + evenodd）。"""

    name = "contour_filled"

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        data = build.data
        if data.nrows == 0:
            return null_grob(name=f"geom_{self.name}")
        rule = str(build.params.get("rule", "evenodd") or "evenodd")
        if rule not in ("evenodd", "winding"):
            raise GeomError(f"rule 只能是 'evenodd' 或 'winding'，收到 {rule!r}")
        fills = _values(data, "fill", GREY20)
        colours = _values(data, "colour", NA)
        alpha = table_numeric(data, "alpha", default=math.nan)
        linewidth = table_numeric(data, "linewidth", default=0.5)
        linetype = _values(data, "linetype", 1)
        lineend = str(build.params.get("lineend", "butt"))
        linejoin = str(build.params.get("linejoin", "round"))
        linemitre = float(build.params.get("linemitre", 10.0))
        x_all = table_numeric(data, "x")
        y_all = table_numeric(data, "y")
        subgroup = (
            [str(item) for item in _values(data, "subgroup", 0)] if "subgroup" in data else None
        )

        grobs: list[Any] = []
        for _key, rows in _group_rows(data):
            if rows.size < 3:
                continue
            xs = x_all[rows]
            ys = y_all[rows]
            if subgroup is not None:
                sub_keys = [subgroup[index] for index in rows.tolist()]
            else:
                sub_keys = [0] * rows.size
            ids: list[int] = []
            codes: dict[Any, int] = {}
            for key in sub_keys:
                if key not in codes:
                    codes[key] = len(codes) + 1
                ids.append(codes[key])
            px, py, munched = munch_xy(panel, xs, ys, ids, closed=True)
            first = int(rows[0])
            grobs.append(
                path_grob(
                    px.tolist(),
                    py.tolist(),
                    id=munched,
                    rule=rule,
                    default_units="native",
                    name=f"geom_{self.name}",
                    gp={
                        "fill": alpha_colour(fills[first], alpha[first]),
                        "col": alpha_colour(colours[first], None),
                        "lwd": float(linewidth[first]) * POINT_PER_MM,
                        "lty": lty_value(linetype[first]),
                        "lineend": lineend,
                        "linejoin": linejoin,
                        "linemitre": linemitre,
                    },
                )
            )
        if not grobs:
            return null_grob(name=f"geom_{self.name}")
        if len(grobs) == 1:
            return grobs[0]
        return g_tree(*grobs, name=f"geom_{self.name}")


class Density2dFilledRenderer(ContourFilledRenderer):
    """`geom_density_2d_filled`：与 `geom_contour_filled` 同一路径。"""

    name = "density_2d_filled"


# ---------------------------------------------------------------------------
# 点 / 线族的薄封装
# ---------------------------------------------------------------------------


class JitterRenderer(PointRenderer):
    """`geom_jitter`：绘制同 `geom_point`，抖动在 position 阶段。"""

    name = "jitter"


class CountRenderer(PointRenderer):
    """`geom_count`：绘制同 `geom_point`，`size` 来自 `stat_sum` 的 `n`。"""

    name = "count"


class QqRenderer(PointRenderer):
    """`geom_qq`：绘制同 `geom_point`，`x/y` 来自 `stat_qq`。"""

    name = "qq"


class QqLineRenderer(PathRenderer):
    """`geom_qq_line`：绘制同 `geom_path`，`x/y` 来自 `stat_qq_line`。"""

    name = "qq_line"


class QuantileRenderer(PathRenderer):
    """`geom_quantile`：绘制同 `geom_path`（`stat_quantile` 给多组分位线）。"""

    name = "quantile"


class FunctionRenderer(PathRenderer):
    """`geom_function`：绘制同 `geom_path`；多个绘制组时发警告。"""

    name = "function"

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        if build.data.nrows and len(_group_rows(build.data)) > 1:
            warnings.warn(
                f"Multiple drawing groups in geom_{self.name}. Did you use the correct group, "
                "colour, or fill aesthetics?",
                BuildWarning,
                stacklevel=2,
            )
        return super().draw(geom, build, panel, coord, theme, metrics)

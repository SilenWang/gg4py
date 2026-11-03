"""线段族（M2-S2）：`geom_segment` / `geom_curve` / `geom_spoke` /
`geom_abline` / `geom_hline` / `geom_vline` 的绘制。

照 4.0.3：

- `GeomSegment$draw_panel()`：线性坐标下一条 `segmentsGrob`（`gp` 带
  `col = alpha(colour, alpha)`、`fill = alpha(arrow.fill, alpha)`、`lwd`、`lty`、
  `lineend`、`linejoin`），`arrow =` 透传给设备；非线性坐标下拆成
  `起始点 + 终止点` 两段交给 `GeomPath`（逐边细分）。
- `GeomCurve$draw_panel()`：`curveGrob(..., curvature, angle, ncp, square = FALSE,
  squareShape = 1, inflect = FALSE, open = TRUE)`；非线性坐标只是警告。
- `GeomSpoke$setup_data()`：`xend = x + cos(angle) * radius`、
  `yend = y + sin(angle) * radius`（角在数据空间，弧度）。
- `GeomAbline$draw_panel()`：用面板的**反变换范围**求直线与面板边框的交点；
  `coord$clip == "on"` 且线性时先把范围各扩一个跨度（R 的「多画一点再裁」）。
- `GeomHline` / `GeomVline`：横线 / 竖线取反变换范围的端点。

箭头是 IR 0.3 的节点标记属性（`arrow` / `arrow_length` / `arrow_angle` /
`arrow_type`），箭翼几何由设备按端点切向求（`docs/notes/ir.md` §4）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from ggcore.arrow import Arrow, as_arrow
from ggcore.data import Column, ColumnTable
from ggcore.geom.base import (
    POINT_PER_MM,
    GeomRenderer,
    alpha_colour,
    munch_xy,
    npc_values,
    put_column,
    table_numeric,
    table_values,
)
from ggcore.grobs import curve_grob, g_tree, null_grob, polyline_grob, segments_grob
from ggcore.units import unit

__all__ = [
    "AblineRenderer",
    "CurveRenderer",
    "HlineRenderer",
    "SegmentRenderer",
    "SpokeRenderer",
    "VlineRenderer",
]


# ---------------------------------------------------------------------------
# 共享工具
# ---------------------------------------------------------------------------


def _endpoints(data: Any, panel: Any) -> dict[str, np.ndarray]:
    """`x/y/xend/yend` → 屏幕 npc；`xend` / `yend` 缺列时退回 `x` / `y`。"""
    x = npc_values(panel, data, "x", "x")
    y = npc_values(panel, data, "y", "y")
    x1 = npc_values(panel, data, "xend", "x") if "xend" in data else x
    y1 = npc_values(panel, data, "yend", "y") if "yend" in data else y
    return {"x": x, "y": y, "xend": x1, "yend": y1}


def _complete(columns: dict[str, np.ndarray]) -> np.ndarray:
    keep = np.ones(next(iter(columns.values())).size, dtype=bool)
    for values in columns.values():
        keep &= np.isfinite(values)
    return keep


def _unique_rows(data: Any, names: tuple[str, ...]) -> np.ndarray:
    """`unique0(data)`：按给定的美学列去重（保留首次出现的行）。

    `geom_abline(slope = 1, intercept = 0.1)` 是**常量参数**，但数据表仍是 2 行；
    R 在 `draw_panel()` 里调 `unique0(data)`，所以只画一条线。不去重会画两遍——
    两条抗锯齿的边叠在一起，边缘像素比 R 深（SIL-737 的 abline 用例 2.12%）。
    """
    keys: list[np.ndarray] = []
    for name in names:
        if name in data:
            keys.append(np.asarray(data.column(name).values))
    if not keys:
        return np.arange(data.nrows)
    seen: dict[Any, int] = {}
    order: list[int] = []
    length = data.nrows
    columns = [np.asarray(key).tolist() for key in keys]
    for index in range(length):
        key = tuple(
            value[index].item() if isinstance(value[index], np.generic) else value[index]
            for value in columns
        )
        if key in seen:
            continue
        seen[key] = index
        order.append(index)
    return np.asarray(order, dtype=np.int64)


def _arrow_of(params: Any) -> Arrow | None:
    return as_arrow(params.get("arrow"))


def _line_gpar(data: Any, params: Any, rows: Any) -> dict[str, Any]:
    """逐行的线段 gpar（`col` / `fill` 都吃 alpha；`fill` 给闭合箭头用）。"""
    index = np.atleast_1d(rows)
    colours = table_values(data, "colour", "black")
    alpha = table_numeric(data, "alpha", default=math.nan)
    linewidth = table_numeric(data, "linewidth", default=0.5)
    linetype = table_values(data, "linetype", 1)
    painted = [alpha_colour(colours[i], alpha[i]) for i in index.tolist()]
    first = int(index[0])
    # IR 的 gpar 是**每个节点一份** `lty`（象 line / path 一样取首值）；R 在
    # 一条线内部换 linetype 时会拆成多个 grob，这里不拆（见 docs/notes/geom.md）。
    lty = linetype[first] if isinstance(linetype[first], str) else int(linetype[first])
    return {
        "col": painted,
        "fill": painted,
        "lwd": (linewidth[index] * POINT_PER_MM).tolist(),
        "lty": lty,
        "lineend": str(params.get("lineend", "butt")),
        "linejoin": str(params.get("linejoin", "round")),
    }


def _single(gp: dict[str, Any], index: int) -> dict[str, Any]:
    """一组逐行 gpar 里的第 `index` 个元素（标量版，供单个 grob 用）。"""
    return {
        name: (values[index] if isinstance(values, list) else values) for name, values in gp.items()
    }


def _take_rows(data: Any, rows: np.ndarray) -> Any:
    from ggcore.geom.base import row_slice

    if rows.size == data.nrows and bool(np.array_equal(rows, np.arange(data.nrows))):
        return data
    return row_slice(data, rows)


def _float_column(values: Any) -> Column:
    return Column("float", np.asarray(values, dtype=np.float64))


def _segments_grob(
    name: str, table: ColumnTable, panel: Any, gp: dict[str, Any], arrow: Arrow | None = None
) -> Any:
    """端点表（x/y/xend/yend，数据空间）→ 一个 `segmentsGrob`。"""
    px = npc_values(panel, table, "x", "x")
    py = npc_values(panel, table, "y", "y")
    pex = npc_values(panel, table, "xend", "x")
    pey = npc_values(panel, table, "yend", "y")
    return segments_grob(
        unit(px.tolist(), "native"),
        unit(py.tolist(), "native"),
        unit(pex.tolist(), "native"),
        unit(pey.tolist(), "native"),
        default_units="native",
        name=f"geom_{name}",
        gp=gp,
        arrow=arrow,
    )


# ---------------------------------------------------------------------------
# geom_segment / geom_spoke
# ---------------------------------------------------------------------------


class SegmentRenderer(GeomRenderer):
    """`geom_segment`：一条 `segmentsGrob`（非线性坐标拆成 path 的逐边细分）。"""

    name = "segment"
    non_missing_aes = ("linetype", "linewidth")

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        data = build.data
        if data.nrows == 0:
            return null_grob(name="geom_segment")
        params = build.params
        arrow = _arrow_of(params)
        columns = _endpoints(data, panel)
        keep = _complete(columns)
        if not bool(keep.any()):
            return null_grob(name="geom_segment")
        rows = np.flatnonzero(keep)
        gp = _line_gpar(data, params, rows)
        if getattr(panel, "is_linear", True):
            table = ColumnTable(
                [
                    ("x", _float_column(columns["x"][keep])),
                    ("y", _float_column(columns["y"][keep])),
                    ("xend", _float_column(columns["xend"][keep])),
                    ("yend", _float_column(columns["yend"][keep])),
                ],
                nrows=int(keep.sum()),
            )
            return _segments_grob("segment", table, panel, gp, arrow)
        # 非线性坐标：R 把两端点拼成 path 让 coord_munch() 逐边细分。这里逐行
        # 一条折线，箭头的切向仍是端点连线方向。
        grobs: list[Any] = []
        for index in range(rows.size):
            px, py, ids = munch_xy(
                panel,
                [columns["x"][keep][index], columns["xend"][keep][index]],
                [columns["y"][keep][index], columns["yend"][keep][index]],
                [0, 0],
            )
            grobs.append(
                polyline_grob(
                    unit(px.tolist(), "native"),
                    unit(py.tolist(), "native"),
                    id=ids,
                    default_units="native",
                    name="geom_segment",
                    gp=_single(gp, index),
                    arrow=arrow,
                )
            )
        if len(grobs) == 1:
            return grobs[0]
        return g_tree(*grobs, name="geom_segment")


class SpokeRenderer(SegmentRenderer):
    """`geom_spoke`：`xend = x + cos(angle) * radius`（角度是数据空间的弧度）。"""

    name = "spoke"

    def setup_data(self, data: ColumnTable, params: Any) -> ColumnTable:
        angle = table_numeric(data, "angle", default=float("nan"))
        radius = table_numeric(data, "radius", default=float("nan"))
        if "angle" not in data:
            angle = np.full(data.nrows, float(params.get("angle", 0.0)))
        if "radius" not in data:
            radius = np.full(data.nrows, float(params.get("radius", 0.0)))
        x = table_numeric(data, "x", default=float("nan"))
        y = table_numeric(data, "y", default=float("nan"))
        columns = [(name, data.column(name)) for name in data.names]
        put_column(columns, "xend", _float_column(x + np.cos(angle) * radius))
        put_column(columns, "yend", _float_column(y + np.sin(angle) * radius))
        return ColumnTable(columns, nrows=data.nrows)


# ---------------------------------------------------------------------------
# geom_curve
# ---------------------------------------------------------------------------


class CurveRenderer(GeomRenderer):
    """`geom_curve`：`curveGrob`（`square = FALSE`、`squareShape = 1`、`open = TRUE`）。"""

    name = "curve"
    non_missing_aes = ("linetype", "linewidth")

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        data = build.data
        if data.nrows == 0:
            return null_grob(name="geom_curve")
        params = build.params
        columns = _endpoints(data, panel)
        keep = _complete(columns)
        if not bool(keep.any()):
            return null_grob(name="geom_curve")
        rows = np.flatnonzero(keep)
        arrow = _arrow_of(params)
        gp = _line_gpar(data, params, rows)
        grobs: list[Any] = []
        for index in range(rows.size):
            grobs.append(
                curve_grob(
                    unit(float(columns["x"][keep][index]), "native"),
                    unit(float(columns["y"][keep][index]), "native"),
                    unit(float(columns["xend"][keep][index]), "native"),
                    unit(float(columns["yend"][keep][index]), "native"),
                    curvature=float(params.get("curvature", 0.5)),
                    angle=float(params.get("angle", 90.0)),
                    ncp=int(params.get("ncp", 5)),
                    shape=1.0,
                    square=False,
                    inflect=False,
                    open=True,
                    default_units="native",
                    name="geom_curve",
                    gp=_single(gp, index),
                    arrow=arrow,
                )
            )
        if len(grobs) == 1:
            return grobs[0]
        return g_tree(*grobs, name="geom_curve")


# ---------------------------------------------------------------------------
# geom_abline / geom_hline / geom_vline
# ---------------------------------------------------------------------------


def _range(panel: Any, *, clip_expand: bool) -> tuple[float, float, float, float]:
    """`backtransform_range()`；`clip == "on"` 且线性时各轴扩一个跨度。"""
    ranges = panel.backtransform_range()
    low_x, high_x = ranges["x"]
    low_y, high_y = ranges["y"]
    if clip_expand and getattr(panel, "clip", "on") == "on" and getattr(panel, "is_linear", True):
        span_x = high_x - low_x
        span_y = high_y - low_y
        low_x, high_x = low_x - span_x, high_x + span_x
        low_y, high_y = low_y - span_y, high_y + span_y
    return low_x, high_x, low_y, high_y


class AblineRenderer(GeomRenderer):
    """`geom_abline`：`y = slope * x + intercept` 与面板边框的交线段。"""

    name = "abline"

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        data = build.data
        if data.nrows == 0:
            return null_grob(name="geom_abline")
        low_x, high_x, low_y, high_y = _range(panel, clip_expand=True)
        rows = _unique_rows(data, ("slope", "intercept", "colour", "linewidth", "linetype"))
        data = _take_rows(data, rows)
        slopes = table_numeric(data, "slope", default=float("nan"))
        intercepts = table_numeric(data, "intercept", default=float("nan"))
        xs: list[float] = []
        ys: list[float] = []
        xe: list[float] = []
        ye: list[float] = []
        kept: list[int] = []
        for index in range(data.nrows):
            slope = float(slopes[index])
            intercept = float(intercepts[index])
            if not (math.isfinite(slope) and math.isfinite(intercept)):
                continue
            # R 的做法：先求直线与上下边框的交点，再夹进左右边框（竖线走同一支）。
            start_x = (low_y - intercept) / slope if slope != 0 else low_x
            end_x = (high_y - intercept) / slope if slope != 0 else high_x
            start_x = max(low_x, min(start_x, high_x))
            end_x = min(high_x, max(end_x, low_x))
            xs.append(start_x)
            ys.append(start_x * slope + intercept)
            xe.append(end_x)
            ye.append(end_x * slope + intercept)
            kept.append(index)
        if not kept:
            return null_grob(name="geom_abline")
        table = ColumnTable(
            [
                ("x", _float_column(xs)),
                ("y", _float_column(ys)),
                ("xend", _float_column(xe)),
                ("yend", _float_column(ye)),
            ],
            nrows=len(kept),
        )
        return _segments_grob(
            "abline", table, panel, _line_gpar(data, build.params, np.asarray(kept))
        )


class HlineRenderer(GeomRenderer):
    """`geom_hline`：在面板反变换范围的整个宽度上画横线。"""

    name = "hline"

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        data = build.data
        if data.nrows == 0:
            return null_grob(name="geom_hline")
        low, high, _, _ = _range(panel, clip_expand=False)
        rows = _unique_rows(data, ("yintercept", "colour", "linewidth", "linetype"))
        data = _take_rows(data, rows)
        values = table_numeric(data, "yintercept", default=float("nan"))
        keep = np.isfinite(values)
        if not bool(keep.any()):
            return null_grob(name="geom_hline")
        count = int(keep.sum())
        table = ColumnTable(
            [
                ("x", _float_column(np.full(count, low))),
                ("y", _float_column(values[keep])),
                ("xend", _float_column(np.full(count, high))),
                ("yend", _float_column(values[keep])),
            ],
            nrows=count,
        )
        return _segments_grob(
            "hline", table, panel, _line_gpar(data, build.params, np.flatnonzero(keep))
        )


class VlineRenderer(GeomRenderer):
    """`geom_vline`：在面板反变换范围的整个高度上画竖线。"""

    name = "vline"

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        data = build.data
        if data.nrows == 0:
            return null_grob(name="geom_vline")
        _, _, low, high = _range(panel, clip_expand=False)
        rows = _unique_rows(data, ("xintercept", "colour", "linewidth", "linetype"))
        data = _take_rows(data, rows)
        values = table_numeric(data, "xintercept", default=float("nan"))
        keep = np.isfinite(values)
        if not bool(keep.any()):
            return null_grob(name="geom_vline")
        count = int(keep.sum())
        table = ColumnTable(
            [
                ("x", _float_column(values[keep])),
                ("y", _float_column(np.full(count, low))),
                ("xend", _float_column(values[keep])),
                ("yend", _float_column(np.full(count, high))),
            ],
            nrows=count,
        )
        return _segments_grob(
            "vline", table, panel, _line_gpar(data, build.params, np.flatnonzero(keep))
        )

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
    row_slice,
    table_column,
    table_numeric,
)
from ggcore.grobs import g_tree, null_grob, polyline_grob, segments_grob
from ggcore.munch import munch_steps
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


def _lty(value: Any) -> Any:
    """`gpar.lty`：数值（含 numpy 浮点）折成 int，样式名原样。"""
    if isinstance(value, str):
        return value
    return int(value)


def _munch_path(
    panel: Any,
    xs: np.ndarray,
    ys: np.ndarray,
    groups: np.ndarray,
    *,
    segment_length: float = 0.01,
) -> tuple[np.ndarray, np.ndarray, list[int], np.ndarray]:
    """`coord_munch()` 的 path 版本：`(px, py, run_id, source_row)`。

    分组按 `group` 的**取值**（上游 `GeomPath$draw_panel()` 先
    `data[order(data$group), ]`），不是按连续段——`group` 交错出现的路径
    （`geom-path-groups`）也要各连各的。

    非线性坐标（极坐标 / 径向 / 非 identity 的 `coord_trans`）下每条边按
    `segment_length` 细分；每个细分点的样式取**该边的起点行**（上游
    `munch_data()` 的 `aes_df <- data[id, ...]`），`source_row` 就是那个行号。
    线性坐标不细分，`source_row` 是原行号。

    `run_id` 在组切换与缺失值处递增，直接喂给 `polyline_grob(id=)`。
    """
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    keys = groups.tolist()
    unique: list[Any] = []
    for key in keys:
        if key not in unique:
            unique.append(key)
    linear = bool(getattr(panel, "is_linear", True))
    x_span = 0.0 if linear else float(panel.x_range[1]) - float(panel.x_range[0])
    y_span = 0.0 if linear else float(panel.y_range[1]) - float(panel.y_range[0])
    out_x: list[float] = []
    out_y: list[float] = []
    out_run: list[int] = []
    out_src: list[int] = []
    run = 0
    for key in unique:
        rows = [index for index, value in enumerate(keys) if value == key]
        run += 1
        previous: int | None = None
        for row in rows:
            x1 = float(xs[row])
            y1 = float(ys[row])
            if previous is None:
                out_x.append(x1)
                out_y.append(y1)
                out_run.append(run)
                out_src.append(row)
                previous = row
                continue
            x0 = float(xs[previous])
            y0 = float(ys[previous])
            if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
                # 缺失值留成断点（同一个 run 里的 `id` 断开，grid 的 NA 断线语义），
                # 不在这里新开 run——否则一条线会被拆成多个 polyline grob。
                out_x.append(x1)
                out_y.append(y1)
                out_run.append(run)
                out_src.append(row)
                previous = row
                continue
            if linear:
                out_x.append(x1)
                out_y.append(y1)
                out_run.append(run)
                out_src.append(previous)
            else:
                distance = math.hypot((x1 - x0) / x_span, (y1 - y0) / y_span)
                steps = munch_steps(distance, segment_length)
                for step in range(1, steps + 1):
                    ratio = step / steps
                    out_x.append(x0 + (x1 - x0) * ratio)
                    out_y.append(y0 + (y1 - y0) * ratio)
                    out_run.append(run)
                    out_src.append(previous)
            previous = row
        run += 1
    px, py = panel.project_xy(np.asarray(out_x), np.asarray(out_y))
    return np.asarray(px), np.asarray(py), out_run, np.asarray(out_src, dtype=int)


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
        xs_data = table_numeric(data, "x")
        ys_data = table_numeric(data, "y")
        groups = _group_key(data)
        colours = _values(data, "colour", "black")
        linewidth = table_numeric(data, "linewidth", default=0.5)
        linetype = _values(data, "linetype", 1)
        alpha = table_numeric(data, "alpha", default=math.nan)
        lineend = str(build.params.get("lineend", "butt"))
        linejoin = str(build.params.get("linejoin", "round"))
        linemitre = float(build.params.get("linemitre", 10.0))

        # `coord_munch()`：非线性坐标下每条边走细分，细分点的样式取该边起点行。
        px, py, run_ids, source = _munch_path(panel, xs_data, ys_data, groups)
        run_array = np.asarray(run_ids, dtype=int)

        grobs: list[Any] = []
        for run in np.unique(run_array):
            rows = np.flatnonzero(run_array == run)
            if rows.size < 2:
                continue
            xs, ys, ids = _break_at_na(px[rows], py[rows])
            if xs.size < 2:
                continue
            # `_break_at_na` 丢掉 NA 点后，样式来源行要跟着重排。
            finite = np.isfinite(px[rows]) & np.isfinite(py[rows])
            style_rows = source[rows][finite]
            if style_rows.size == 0:
                continue
            # 样式去重：`style_rows` 是逐点的来源行，不是样式集合（一条线上的
            # 10 个点仍可能是同一种样式，早先按行数判断会误走逐段分支）。
            styles = list(
                dict.fromkeys(
                    (
                        alpha_colour(colours[int(row)], alpha[int(row)]),
                        float(linewidth[int(row)]),
                        _lty(linetype[int(row)]),
                    )
                    for row in np.unique(style_rows)
                )
            )
            if len(styles) == 1:
                # 整条线样式一致：一条折线（R 的 `polylineGrob` 分支）。
                colour, width, type_ = styles[0]
                grobs.append(
                    polyline_grob(
                        unit(xs.tolist(), "native"),
                        unit(ys.tolist(), "native"),
                        id=ids,
                        default_units="native",
                        gp=gpar(
                            col=colour,
                            lwd=width * POINT_PER_MM,
                            lty=type_,
                            lineend=lineend,
                            linejoin=linejoin,
                            linemitre=linemitre,
                        ),
                    )
                )
                continue
            # 样式沿线变化：逐段画（R 的 `segmentsGrob` 分支，取段起点行）。
            # R 在 linetype 也变化时直接 abort；这里按 (colour, lwd, lty) 分桶画，
            # 视觉结果与逐段 `segmentsGrob()` 相同。
            # 每个点的 `source` 是**该点所在边**的起点行；段 i（点 i → i+1）的
            # 样式取终点记录的起点行，即 `style_rows[1:]`。用 `[:-1]` 会把上一段
            # 的样式带到下一段（线宽随 x 变化的折线整条都被第一段的宽度画粗）。
            seg_source = style_rows[1:]
            x0 = xs[:-1]
            y0 = ys[:-1]
            x1 = xs[1:]
            y1 = ys[1:]
            # `gpar()` 只收标量样式，所以按 (colour, lwd, lty) 分组，每组一个
            # `segmentsGrob`（R 用一个矢量化的 `segmentsGrob` 表达同一件事）。
            buckets: dict[tuple[Any, float, Any], list[int]] = {}
            for index, row in enumerate(seg_source):
                style = (
                    alpha_colour(colours[int(row)], alpha[int(row)]),
                    float(linewidth[int(row)]) * POINT_PER_MM,
                    _lty(linetype[int(row)]),
                )
                buckets.setdefault(style, []).append(index)
            for (colour, width, type_), indices in buckets.items():
                pick = np.asarray(indices, dtype=int)
                grobs.append(
                    segments_grob(
                        unit(x0[pick].tolist(), "native"),
                        unit(y0[pick].tolist(), "native"),
                        unit(x1[pick].tolist(), "native"),
                        unit(y1[pick].tolist(), "native"),
                        default_units="native",
                        gp=gpar(
                            col=colour,
                            lwd=width,
                            lty=type_,
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
                keys.append(_order_key(frame, "group"))
            if "x" in frame:
                keys.append(table_numeric(frame, "x", default=0.0))
            if keys:
                order = np.lexsort(tuple(reversed(keys)))
                frame = row_slice(frame, order)
        return flip_data(frame, flipped)


def _order_key(frame: Any, name: str) -> np.ndarray:
    """排序键：数值列原样；字符串 / categorical 列按升序查表成整数。

    `stat_quantile()` 的输出里 `group` 是字符（`paste(group, quantile, sep = "-")`，
    上游同样如此），`order(PANEL, group, x)` 在 R 里按字符排序；这里按
    「升序去重的下标」复现同一顺序，避免把字符列硬转 float。
    """
    column = table_column(frame, name)
    if column is None:
        return np.zeros(frame.nrows, dtype=np.float64)
    if column.kind in ("str", "categorical"):
        values = frame.column(name).values.tolist()
        ranks = {value: index for index, value in enumerate(sorted(set(values)))}
        return np.array([float(ranks[value]) for value in values], dtype=np.float64)
    return table_numeric(frame, name, default=0.0)


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
    """分组键：`group` 列（0 起比较），没有就整表一组。

    `stat_quantile()` 的输出里 `group` 是字符（上游 `paste(group, quantile, sep =
    "-")`），这里按升序查表成整数，与 `_order_key()` 同一个口径。
    """
    if "group" in data:
        values = np.asarray(data.column("group").values)
        if values.dtype.kind in ("U", "S", "O"):
            ranks = {value: index for index, value in enumerate(sorted(set(values.tolist())))}
            coded = np.array([float(ranks[value]) for value in values.tolist()], dtype=np.float64)
            mask = np.asarray(data.column("group").na_mask, dtype=bool)
            return np.where(mask, -1.0, coded)
        numeric = values.astype(np.float64)
        mask = np.asarray(data.column("group").na_mask, dtype=bool)
        return np.where(mask, -1.0, numeric)
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

"""`geom_text` / `geom_label` 的绘制（M2-7 长尾 B）。

照 4.0.3 的 `GeomText$draw_panel()` / `GeomLabel$draw_panel()`：

```r
data <- coord$transform(data, panel_params)
data$vjust <- compute_just(data$vjust, data$y, data$x, data$angle)
data$hjust <- compute_just(data$hjust, data$x, data$y, data$angle)
textGrob(lab, data$x, data$y, default.units = "native",
         hjust = data$hjust, vjust = data$vjust, rot = data$angle,
         gp = gg_par(col = alpha(colour, alpha), fontsize = size * size.unit,
                     fontfamily = family, fontface = fontface,
                     lineheight = lineheight),
         check.overlap = check_overlap)
```

两处与 IR 的差异都按**分组**处理，不改 IR：

- `textGrob` 的 `rot` / `hjust` / `vjust` 在 IR 里是单值，所以逐行不同的
  `(hjust, vjust, angle)` 组合各画一个 `textGrob`（与 `geom_point` 的逐点
  size 同一路数：视觉等价，节点更多）。
- `check_overlap` 在 R 里是**绘制期**按数据行序丢重叠标签；这里用面板尺寸 +
  真实文本度量算 bbox（旋转后取轴对齐外包框），逐行判断后从数据里删行。

`geom_label` 的 `labelGrob()` 几何逐项照 4.0.3：

```r
padding[1] <- max(padding[1], descent)
padding[3] <- max(padding[3] - descent, 0)
text  <- titleGrob(label, hjust, vjust, x, y + (1 - vjust) * descent,
                   margin = padding, margin_x = TRUE, margin_y = TRUE, gp)
height <- heightDetails(text)
box   <- roundrectGrob(x, y + (0.5 - vjust) * height,
                       width = widthDetails(text), height = height,
                       just = c(hjust, 0.5), r = r, gp = rect.gp)
```

IR 没有圆角矩形节点：背景用 `rectGrob` 的同形矩形表达，`label.r`（默认
0.15 lines ≈ 2pt）的圆角在 72dpi 下不足 1.5px，记进 `docs/notes/geom.md`
的已知差异。文字的宽度 / 高度来自 `build.metrics`（M2-S1 的字体对齐结果），
不在 geom 里另测。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from ggcore.data import Column, ColumnTable
from ggcore.geom.base import (
    POINT_PER_MM,
    GeomRenderer,
    alpha_colour,
    lty_value,
    npc_values,
    table_numeric,
    table_strings,
)
from ggcore.grobs import g_tree, null_grob, rect_grob, text_grob
from ggcore.units import unit
from ggcore.viewport import NA, gpar

__all__ = ["FONT_FACES", "LabelRenderer", "TextRenderer", "compute_just"]

#: `fontface` 美学 → gpar 的 `font` 整数（R `validGP()` 的表）。
FONT_FACES: dict[str, int] = {
    "plain": 1,
    "bold": 2,
    "italic": 3,
    "bold.italic": 4,
    "bolditalic": 4,
    "symbol": 5,
}
_FACES = {1: "", 2: "bold", 3: "italic", 4: "bold-italic", 5: "symbol"}

#: `size.unit` → 乘数（`resolve_text_unit()`）。
_TEXT_UNITS = {"mm": POINT_PER_MM, "cm": POINT_PER_MM * 10.0, "in": 72.27, "pc": 12.0, "pt": 1.0}


# ---------------------------------------------------------------------------
# 列读取
# ---------------------------------------------------------------------------


def _strings(data: ColumnTable, name: str) -> list[str]:
    out: list[str] = []
    for value in table_strings(data, name):
        if value is None:
            out.append("")
        elif isinstance(value, str):
            out.append(value)
        elif isinstance(value, (bool, np.bool_)):
            out.append("TRUE" if bool(value) else "FALSE")
        elif isinstance(value, (int, np.integer)):
            out.append(str(int(value)))
        elif isinstance(value, (float, np.floating)):
            number = float(value)
            out.append(str(int(number)) if number.is_integer() else repr(number))
        else:
            out.append(str(value))
    return out


def _values(data: ColumnTable, name: str, default: Any) -> list[Any]:
    if name not in data:
        return [default] * data.nrows
    column = data.column(name)
    values = column.values.tolist()
    mask = np.asarray(column.na_mask, dtype=bool).tolist()
    return [NA if missing else value for value, missing in zip(values, mask, strict=True)]


def _font_faces(data: ColumnTable) -> list[int]:
    out: list[int] = []
    for value in _values(data, "fontface", 1):
        if value is None or value is NA:
            out.append(1)
        elif isinstance(value, str):
            try:
                out.append(FONT_FACES[value])
            except KeyError:
                raise ValueError(
                    f"fontface 不认识 {value!r}（可用：{', '.join(FONT_FACES)}）"
                ) from None
        else:
            out.append(int(value))
    return out


def _families(data: ColumnTable) -> list[str]:
    return ["" if item is None or item is NA else str(item) for item in _values(data, "family", "")]


# ---------------------------------------------------------------------------
# 对齐（`compute_just()`）
# ---------------------------------------------------------------------------


def _just_dir(value: float, tol: float = 0.001) -> int:
    if value < 0.5 - tol:
        return 1
    if value > 0.5 + tol:
        return 3
    return 2


def _compute_just(value: Any, a: float, b: float, angle: float) -> float:
    """`compute_just(just, a, b, angle)` 的标量版（`inward` / `outward` 也在内）。"""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float, np.integer, np.floating)):
        number = float(value)
        return 0.5 if math.isnan(number) else number
    if value is None or value is NA:
        return 0.5
    text = str(value)
    names = {
        "left": 0.0,
        "center": 0.5,
        "centre": 0.5,
        "right": 1.0,
        "bottom": 0.0,
        "middle": 0.5,
        "top": 1.0,
    }
    if "inward" not in text and "outward" not in text:
        if text not in names:
            raise ValueError(f"hjust / vjust 不认识 {text!r}")
        return names[text]
    normalized = float(angle) % 360.0
    if normalized > 180.0:
        normalized -= 360.0
    rotated_forward = 45.0 < normalized < 135.0
    rotated_backwards = -135.0 < normalized < -45.0
    ab = b if (rotated_forward or rotated_backwards) else a
    swap = rotated_backwards or abs(normalized) > 135.0
    direction = _just_dir(float(ab))
    inward = (text == "inward" and not swap) or (text == "outward" and swap)
    outward = (text == "outward" and not swap) or (text == "inward" and swap)
    if inward:
        return (0.0, 0.5, 1.0)[direction - 1]
    if outward:
        return (1.0, 0.5, 0.0)[direction - 1]
    return 0.5


def compute_just(values: Any, a: Any, b: Any, angle: Any) -> np.ndarray:
    """`compute_just()` 的向量版（逐行；`a` / `b` 是数据坐标）。"""
    a_values = np.asarray(a, dtype=np.float64).ravel()
    b_values = np.asarray(b, dtype=np.float64).ravel()
    angles = np.asarray(angle, dtype=np.float64).ravel()
    if isinstance(values, np.ndarray) and values.ndim:
        items = values.tolist()
    elif isinstance(values, (list, tuple)):
        items = list(values)
    else:
        items = [values] * a_values.size
    if len(items) != a_values.size:
        items = (items * (a_values.size // max(len(items), 1) + 1))[: a_values.size]
    out = np.empty(a_values.size, dtype=np.float64)
    for index, value in enumerate(items):
        out[index] = _compute_just(
            value, float(a_values[index]), float(b_values[index]), float(angles[index])
        )
    return out


def _raw_just(data: ColumnTable, name: str) -> list[Any]:
    return [0.5 if value is None or value is NA else value for value in _values(data, name, 0.5)]


# ---------------------------------------------------------------------------
# nudge（`position_nudge` 的 nudge_x / nudge_y）
# ---------------------------------------------------------------------------


def _nudged(build: Any) -> ColumnTable:
    """把 `nudge_x` / `nudge_y` 折进 x / y 数据坐标（R 的 position_nudge 语义）。"""
    data = build.data
    params = dict(build.params or {})
    shifts = {
        "x": _shift_values(data, "nudge_x", params.get("nudge_x")),
        "y": _shift_values(data, "nudge_y", params.get("nudge_y")),
    }
    if shifts["x"] is None and shifts["y"] is None:
        return data
    columns: list[tuple[str, Column]] = []
    for name in data.names:
        column = data.column(name)
        shift = shifts.get(name)
        if shift is not None:
            column = _shifted(column, shift)
        columns.append((name, column))
    return ColumnTable(columns, nrows=data.nrows)


def _shift_values(data: ColumnTable, name: str, default: Any) -> np.ndarray | None:
    if name in data:
        return np.nan_to_num(table_numeric(data, name, default=0.0), nan=0.0)
    if default is None:
        return None
    return np.full(data.nrows, float(default))


def _shifted(column: Column, shift: np.ndarray) -> Column:
    values = np.asarray(column.values, dtype=np.float64) + shift
    mask = None if column.na_mask is None else np.asarray(column.na_mask, dtype=bool).copy()
    if mask is not None:
        values[mask] = np.nan
    return Column("float", values, column.levels, mask)


# ---------------------------------------------------------------------------
# 文本度量
# ---------------------------------------------------------------------------


def _text_pt(size_mm: np.ndarray, params: Any) -> np.ndarray:
    unit_name = str(params.get("size.unit", "mm") or "mm")
    if unit_name not in _TEXT_UNITS:
        raise ValueError(f"size.unit 只能是 {', '.join(_TEXT_UNITS)}，收到 {unit_name!r}")
    return size_mm * _TEXT_UNITS[unit_name]


def _font_key(family: str, face: int) -> str:
    suffix = _FACES.get(int(face), "")
    return f"{family}:{suffix}" if suffix else family


def _measure(
    metrics: Any, label: str, fontsize: float, face: int, family: str
) -> tuple[float, float]:
    """标签的 (宽, 高)（英寸）；度量实现不做字体区分时退回 0.6 em / 0.955 em。"""
    key = _font_key(family, face)
    try:
        width = float(metrics.strwidth(label, fontsize=fontsize, cex=1.0, font=key))
    except TypeError:  # pragma: no cover - 兼容只收位置参数的实现
        width = float(metrics.strwidth(label, fontsize, 1.0, key))
    try:
        height = float(metrics.strheight(label, fontsize=fontsize, cex=1.0, font=key))
    except TypeError:  # pragma: no cover
        height = float(metrics.strheight(label, fontsize, 1.0, key))
    return width, height


def _descent_in(metrics: Any, fontsize: float, face: int, family: str) -> float:
    """字体的 descent（英寸）：优先问度量实现，没有就按 0.22 em 估。"""
    key = _font_key(family, face)
    method = getattr(metrics, "descent", None)
    if callable(method):
        try:
            return float(method(fontsize=fontsize, cex=1.0, font=key))
        except TypeError:  # pragma: no cover
            return float(method(fontsize, 1.0, key))
    return 0.22 * fontsize / 72.0


def _panel_size(panel: Any, axis: str = "y") -> float:
    """面板在某一轴上的尺寸（英寸）；缺省按 1in 处理（只有离屏绘制才发生）。"""
    name = "panel_width_in" if axis == "x" else "panel_height_in"
    value = getattr(panel, name, None)
    return float(value) if value else 1.0


def _inches_to_npc(value: float, panel: Any, axis: str) -> float:
    return float(value) / _panel_size(panel, axis)


# ---------------------------------------------------------------------------
# check_overlap
# ---------------------------------------------------------------------------


def _bboxes(
    xs: np.ndarray,
    ys: np.ndarray,
    widths_in: np.ndarray,
    heights_in: np.ndarray,
    hjust: np.ndarray,
    vjust: np.ndarray,
    angle: np.ndarray,
    panel_w: float,
    panel_h: float,
) -> list[tuple[float, float, float, float]]:
    """每个标签旋转后的轴对齐外包框（英寸，y 向上）。"""
    boxes: list[tuple[float, float, float, float]] = []
    for index in range(xs.size):
        width = float(widths_in[index])
        height = float(heights_in[index])
        left = float(xs[index]) * panel_w - float(hjust[index]) * width
        bottom = float(ys[index]) * panel_h - float(vjust[index]) * height
        rad = math.radians(float(angle[index]))
        cos = abs(math.cos(rad))
        sin = abs(math.sin(rad))
        cx = left + width / 2.0
        cy = bottom + height / 2.0
        half_w = (width * cos + height * sin) / 2.0
        half_h = (width * sin + height * cos) / 2.0
        boxes.append((cx - half_w, cy - half_h, cx + half_w, cy + half_h))
    return boxes


def _intersects(
    left: tuple[float, float, float, float], right: tuple[float, float, float, float]
) -> bool:
    return not (
        left[2] <= right[0] or right[2] <= left[0] or left[3] <= right[1] or right[3] <= left[1]
    )


def _overlap_keep(boxes: list[tuple[float, float, float, float]]) -> np.ndarray:
    """按行序保留不与已保留框重叠的标签（grid 的 `check.overlap` 语义）。"""
    keep = np.ones(len(boxes), dtype=bool)
    kept: list[tuple[float, float, float, float]] = []
    for index, box in enumerate(boxes):
        if any(_intersects(box, other) for other in kept):
            keep[index] = False
        else:
            kept.append(box)
    return keep


# ---------------------------------------------------------------------------
# geom_text
# ---------------------------------------------------------------------------


class TextRenderer(GeomRenderer):
    """`geom_text`：逐行文字，`(hjust, vjust, angle)` 相同的行共用一个 text grob。"""

    name = "text"
    non_missing_aes = ("angle",)

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        data = _nudged(build)
        if data.nrows == 0:
            return null_grob(name="geom_text")
        x = npc_values(panel, data, "x", "x")
        y = npc_values(panel, data, "y", "y")
        labels = _strings(data, "label")
        x_data = table_numeric(data, "x", default=math.nan)
        y_data = table_numeric(data, "y", default=math.nan)
        angle = table_numeric(data, "angle", default=0.0)
        hjust = compute_just(_raw_just(data, "hjust"), x_data, y_data, angle)
        vjust = compute_just(_raw_just(data, "vjust"), y_data, x_data, angle)
        size_pt = _text_pt(table_numeric(data, "size", default=3.87), build.params)
        colours = _values(data, "colour", "black")
        alpha = table_numeric(data, "alpha", default=math.nan)
        families = _families(data)
        faces = _font_faces(data)
        lineheights = table_numeric(data, "lineheight", default=1.2)

        keep = np.isfinite(x) & np.isfinite(y)
        if bool(build.params.get("check_overlap", False)) and bool(keep.any()):
            widths = np.asarray(
                [
                    _measure(metrics, label, float(size_pt[i]), faces[i], families[i])[0]
                    for i, label in enumerate(labels)
                ],
                dtype=np.float64,
            )
            heights = np.asarray(
                [
                    _measure(metrics, label, float(size_pt[i]), faces[i], families[i])[1]
                    for i, label in enumerate(labels)
                ],
                dtype=np.float64,
            )
            keep &= _overlap_keep(
                _bboxes(
                    x,
                    y,
                    widths,
                    heights,
                    hjust,
                    vjust,
                    angle,
                    _panel_size(panel, "x"),
                    _panel_size(panel, "y"),
                )
            )
        if not bool(keep.all()):
            index = np.flatnonzero(keep)
            x, y = x[index], y[index]
            labels = [labels[i] for i in index.tolist()]
            hjust, vjust, angle = hjust[index], vjust[index], angle[index]
            size_pt, alpha, lineheights = size_pt[index], alpha[index], lineheights[index]
            colours = [colours[i] for i in index.tolist()]
            families = [families[i] for i in index.tolist()]
            faces = [faces[i] for i in index.tolist()]

        keys = [
            (float(h), float(v), float(a))
            for h, v, a in zip(hjust.tolist(), vjust.tolist(), angle.tolist(), strict=True)
        ]
        groups: dict[tuple[float, float, float], list[int]] = {}
        for index, key in enumerate(keys):
            groups.setdefault(key, []).append(index)
        grobs: list[Any] = []
        for (hj, vj, rot), rows in groups.items():
            grobs.append(
                text_grob(
                    [labels[i] for i in rows],
                    unit(x[rows].tolist(), "native"),
                    unit(y[rows].tolist(), "native"),
                    hjust=hj,
                    vjust=vj,
                    rot=rot,
                    default_units="native",
                    gp={
                        "col": [alpha_colour(colours[i], alpha[i]) for i in rows],
                        "fontsize": size_pt[rows].tolist(),
                        "fontfamily": [families[i] for i in rows],
                        "font": [faces[i] for i in rows],
                        "lineheight": lineheights[rows].tolist(),
                    },
                    name="geom_text",
                )
            )
        if not grobs:
            return null_grob(name="geom_text")
        if len(grobs) == 1:
            return grobs[0]
        return g_tree(*grobs, name="geom_text")


# ---------------------------------------------------------------------------
# geom_label
# ---------------------------------------------------------------------------


def _line_value(raw: Any, default: float) -> float:
    """`unit(*, "lines")` / 数字 → 以 line 为单位的数值（R 缺省就是 lines）。"""
    if raw is None:
        return default
    if isinstance(raw, (int, float, np.integer, np.floating)):
        return float(raw)
    values = getattr(raw, "values", None)
    if values is None:
        return default
    items = [float(item) for item in np.asarray(values).ravel().tolist()]
    if not items:
        return default
    kind = getattr(raw, "kind", "lines")
    number = items[0]
    if kind == "lines":
        return number
    if kind == "points":
        return number / 12.0
    if kind == "cm":
        return number / 0.4233
    if kind == "mm":
        return number / 4.233
    if kind == "inches":
        return number / 0.1667
    return default


class LabelRenderer(GeomRenderer):
    """`geom_label`：矩形背景 + 文字（`labelGrob()` 的几何）。"""

    name = "label"

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        data = _nudged(build)
        if data.nrows == 0:
            return null_grob(name="geom_label")
        x = npc_values(panel, data, "x", "x")
        y = npc_values(panel, data, "y", "y")
        labels = _strings(data, "label")
        x_data = table_numeric(data, "x", default=math.nan)
        y_data = table_numeric(data, "y", default=math.nan)
        angle = table_numeric(data, "angle", default=0.0)
        hjust = compute_just(_raw_just(data, "hjust"), x_data, y_data, angle)
        vjust = compute_just(_raw_just(data, "vjust"), y_data, x_data, angle)
        size_pt = _text_pt(table_numeric(data, "size", default=3.87), build.params)
        colours = _values(data, "colour", "black")
        fills = _values(data, "fill", "white")
        alpha = table_numeric(data, "alpha", default=math.nan)
        linewidth = table_numeric(data, "linewidth", default=0.25)
        linetypes = _values(data, "linetype", 1)
        families = _families(data)
        faces = _font_faces(data)
        lineheights = table_numeric(data, "lineheight", default=1.2)
        params = build.params or {}
        text_colour = params.get("text.colour", params.get("text.color"))
        border_colour = params.get("border.colour", params.get("border.color"))
        padding_lines = _line_value(params.get("label.padding"), 0.25)
        radius = _line_value(params.get("label.r"), 0.15) * 0.0

        grobs: list[Any] = []
        for index in range(data.nrows):
            if not (math.isfinite(float(x[index])) and math.isfinite(float(y[index]))):
                continue
            fontsize = float(size_pt[index])
            lineheight = float(lineheights[index])
            label = labels[index]
            width_in, height_in = _measure(metrics, label, fontsize, faces[index], families[index])
            descent_in = _descent_in(metrics, fontsize, faces[index], families[index])
            pad = padding_lines * lineheight * fontsize / 72.0
            pad_top = max(pad, descent_in)
            pad_bottom = max(pad - descent_in, 0.0)
            rad = math.radians(float(angle[index]))
            x_descent = abs(math.sin(rad)) * descent_in
            y_descent = abs(math.cos(rad)) * descent_in
            box_w = pad * 2.0 + width_in + x_descent
            box_h = pad_top + pad_bottom + height_in + y_descent
            h, v = float(hjust[index]), float(vjust[index])
            anchor_x = float(x[index])
            anchor_y = float(y[index])
            text_y = anchor_y + (1.0 - v) * _inches_to_npc(descent_in, panel, "y")
            box_y = anchor_y + (0.5 - v) * _inches_to_npc(box_h, panel, "y")
            fill = fills[index]
            border = border_colour if border_colour is not None else colours[index]
            grobs.append(
                g_tree(
                    rect_grob(
                        unit(anchor_x, "native"),
                        unit(box_y, "native"),
                        width=unit(box_w, "inches"),
                        height=unit(box_h, "inches"),
                        just=(h, 0.5),
                        default_units="native",
                        gp=gpar(
                            fill=alpha_colour(fill, alpha[index]),
                            col=alpha_colour(border, None),
                            lwd=float(linewidth[index]) * POINT_PER_MM,
                            lty=lty_value(linetypes[index]),
                        ),
                        name="label-box",
                    ),
                    text_grob(
                        label,
                        unit(anchor_x, "native"),
                        unit(text_y, "native"),
                        hjust=h,
                        vjust=v,
                        rot=float(angle[index]),
                        default_units="native",
                        gp=gpar(
                            col=alpha_colour(
                                text_colour if text_colour is not None else colours[index],
                                alpha[index],
                            ),
                            fontsize=fontsize,
                            fontfamily=families[index],
                            font=faces[index],
                            lineheight=lineheight,
                        ),
                        name="label-text",
                    ),
                    name="geom_label",
                )
            )
        del radius  # 圆角矩形没有 IR 节点，背景是方角矩形（见模块文档）
        if not grobs:
            return null_grob(name="geom_label")
        if len(grobs) == 1:
            return grobs[0]
        return g_tree(*grobs, name="geom_label")

"""Legend key glyphs (`draw_key_*` in ggplot2 4.0.3).

`geom_*(key_glyph=)` 换掉的只是**图例里的那一枚键**；面板里的几何不动。
名与上游同名：

    ggplot(...) + geom_line(key_glyph="timeseries")
    ggplot(...) + geom_point(key_glyph=draw_key_rect)

自定义键可以返回一个 :class:`KeyGlyph` 带 `width_cm` / `height_cm`，对应上游
`attr(grob, "width")` / `attr(grob, "height")`；不带尺寸时按
`(size + linewidth) / 10` cm 撑开（上游 `set_key_size()`）。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ggcore.geom.base import POINT_PER_MM, STROKE_PER_MM, alpha_colour
from ggcore.grobs import (
    Grob,
    g_tree,
    lines_grob,
    points_grob,
    rect_grob,
    segments_grob,
    text_grob,
    zero_grob,
)
from ggcore.units import unit
from ggcore.viewport import NA, gpar

__all__ = [
    "KEY_GLYPHS",
    "KeyGlyph",
    "draw_key",
    "draw_key_abline",
    "draw_key_blank",
    "draw_key_boxplot",
    "draw_key_crossbar",
    "draw_key_dotplot",
    "draw_key_label",
    "draw_key_linerange",
    "draw_key_path",
    "draw_key_point",
    "draw_key_pointrange",
    "draw_key_polygon",
    "draw_key_rect",
    "draw_key_smooth",
    "draw_key_text",
    "draw_key_timeseries",
    "draw_key_vline",
    "draw_key_vpath",
    "key_glyph_for",
]


@dataclass(frozen=True, slots=True)
class KeyGlyph:
    """一个图例键：grob + 可选的 `width` / `height`（cm，对应上游的 grob 属性）。"""

    grob: Grob
    width_cm: float | None = None
    height_cm: float | None = None


def _value(data: Mapping[str, Any], name: str, default: Any = None) -> Any:
    value = data.get(name)
    if value is None or value is NA:
        return default
    try:
        if isinstance(value, float) and math.isnan(value):
            return default
    except TypeError:  # pragma: no cover - 防御
        pass
    return value


def _number(data: Mapping[str, Any], name: str, default: float) -> float:
    value = _value(data, name, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _paint(data: Mapping[str, Any], *names: str, default: str = "black") -> Any:
    for name in names:
        value = _value(data, name)
        if value is not None:
            return alpha_colour(value, _value(data, "alpha"))
    return alpha_colour(default, _value(data, "alpha"))


def draw_key_point(data: Mapping[str, Any], params: Mapping[str, Any], size_mm: float) -> Grob:
    del params, size_mm
    shape = int(_number(data, "shape", 19))
    stroke = _number(data, "stroke", 0.5)
    size_pt = _number(data, "size", 1.5) * POINT_PER_MM + stroke * STROKE_PER_MM / 2.0
    return points_grob(
        0.5,
        0.5,
        pch=shape,
        size=unit(size_pt, "bigpts"),
        size_units="bigpts",
        gp=gpar(
            col=_paint(data, "colour", default="black"),
            fill=_paint(data, "fill", default="black"),
            lwd=stroke * STROKE_PER_MM / 2.0,
        ),
        name="key-point",
    )


def draw_key_rect(data: Mapping[str, Any], params: Mapping[str, Any], size_mm: float) -> Grob:
    del params, size_mm
    fill = _value(data, "fill")
    colour = _value(data, "colour") if fill is None or fill is NA else fill
    return rect_grob(
        0.5,
        0.5,
        1.0,
        1.0,
        gp=gpar(
            col=NA,
            fill=alpha_colour(colour or "grey20", _value(data, "alpha")),
            lty=_value(data, "linetype", 1),
        ),
        name="key-rect",
    )


def draw_key_polygon(
    data: Mapping[str, Any], params: Mapping[str, Any], size_mm: float
) -> KeyGlyph:
    del size_mm
    lwd = _number(data, "linewidth", 0.0) * POINT_PER_MM
    grob = rect_grob(
        0.5,
        0.5,
        unit(1.0, "npc") - unit(lwd, "mm"),
        unit(1.0, "npc") - unit(lwd, "mm"),
        gp=gpar(
            col=_value(data, "colour", NA),
            fill=alpha_colour(_value(data, "fill", "grey20"), _value(data, "alpha")),
            lty=_value(data, "linetype", 1),
            lwd=lwd,
            lineend=params.get("lineend", "butt"),
            linejoin=params.get("linejoin", "mitre"),
        ),
        name="key-polygon",
    )
    # 上游的魔数 5：mm → cm 除以 10，两个方向各画两次再乘 2。
    raw = _number(data, "linewidth", 0.0)
    return KeyGlyph(grob, width_cm=raw / 5.0, height_cm=raw / 5.0)


def draw_key_blank(data: Mapping[str, Any], params: Mapping[str, Any], size_mm: float) -> Grob:
    del data, params, size_mm
    return zero_grob(name="key-blank")


def draw_key_path(data: Mapping[str, Any], params: Mapping[str, Any], size_mm: float) -> Grob:
    del size_mm
    linetype = _value(data, "linetype", 1)
    return segments_grob(
        0.1,
        0.5,
        0.9,
        0.5,
        gp=gpar(
            col=_paint(data, "colour", "fill", default="black"),
            lwd=_number(data, "linewidth", 0.5) * POINT_PER_MM,
            lty=linetype,
            lineend=params.get("lineend", "butt"),
        ),
        name="key-path",
    )


def draw_key_vpath(data: Mapping[str, Any], params: Mapping[str, Any], size_mm: float) -> Grob:
    del size_mm
    return segments_grob(
        0.5,
        0.1,
        0.5,
        0.9,
        gp=gpar(
            col=_paint(data, "colour", "fill", default="black"),
            lwd=_number(data, "linewidth", 0.5) * POINT_PER_MM,
            lty=_value(data, "linetype", 1),
            lineend=params.get("lineend", "butt"),
        ),
        name="key-vpath",
    )


def draw_key_abline(data: Mapping[str, Any], params: Mapping[str, Any], size_mm: float) -> Grob:
    del size_mm
    return segments_grob(
        0.0,
        0.0,
        1.0,
        1.0,
        gp=gpar(
            col=_paint(data, "colour", "fill", default="black"),
            lwd=_number(data, "linewidth", 0.5) * POINT_PER_MM,
            lty=_value(data, "linetype", 1),
            lineend=params.get("lineend", "butt"),
        ),
        name="key-abline",
    )


def draw_key_vline(data: Mapping[str, Any], params: Mapping[str, Any], size_mm: float) -> Grob:
    del size_mm
    return segments_grob(
        0.5,
        0.0,
        0.5,
        1.0,
        gp=gpar(
            col=_paint(data, "colour", "fill", default="black"),
            lwd=_number(data, "linewidth", 0.5) * POINT_PER_MM,
            lty=_value(data, "linetype", 1),
            lineend=params.get("lineend", "butt"),
        ),
        name="key-vline",
    )


def draw_key_dotplot(data: Mapping[str, Any], params: Mapping[str, Any], size_mm: float) -> Grob:
    del params, size_mm
    return points_grob(
        0.5,
        0.5,
        pch=21,
        size=unit(0.5, "npc"),
        gp=gpar(
            col=_paint(data, "colour", default="black"),
            fill=_paint(data, "fill", default="black"),
            lty=_value(data, "linetype", 1),
        ),
        name="key-dotplot",
    )


def draw_key_linerange(data: Mapping[str, Any], params: Mapping[str, Any], size_mm: float) -> Grob:
    if params.get("flipped_aes"):
        return draw_key_path(data, params, size_mm)
    return draw_key_vpath(data, params, size_mm)


def draw_key_pointrange(
    data: Mapping[str, Any], params: Mapping[str, Any], size_mm: float
) -> KeyGlyph:
    line = draw_key_linerange(data, params, size_mm)
    point_data = dict(data)
    point_data["size"] = _number(data, "size", 1.5) * 4.0
    point = draw_key_point(point_data, params, size_mm)
    width = line.width_cm if isinstance(line, KeyGlyph) else None
    height = line.height_cm if isinstance(line, KeyGlyph) else None
    return KeyGlyph(g_tree(line, point, name="key-pointrange"), width, height)


def draw_key_smooth(data: Mapping[str, Any], params: Mapping[str, Any], size_mm: float) -> KeyGlyph:
    path = draw_key_path(data, params, size_mm)
    children = [path]
    if params.get("se", True) is not False:
        fill = alpha_colour(_value(data, "fill", "grey60"), _value(data, "alpha"))
        children.insert(0, rect_grob(0.5, 0.5, 1.0, 1.0, gp=gpar(col=NA, fill=fill)))
    return KeyGlyph(g_tree(*children, name="key-smooth"))


def draw_key_text(data: Mapping[str, Any], params: Mapping[str, Any], size_mm: float) -> Grob:
    del params, size_mm
    return text_grob(
        _value(data, "label", "a"),
        0.5,
        0.5,
        gp=gpar(
            col=_paint(data, "colour", "fill", default="black"),
            fontsize=_number(data, "size", 3.88) * 72.27 / 25.4,
            fontfamily=_value(data, "family", ""),
            font=_value(data, "fontface", 1),
        ),
        name="key-text",
    )


def draw_key_label(data: Mapping[str, Any], params: Mapping[str, Any], size_mm: float) -> Grob:
    del size_mm
    lwd = _number(data, "linewidth", 0.25) * POINT_PER_MM
    text = draw_key_text(data, params, 0.0)
    box = rect_grob(
        0.5,
        0.5,
        1.0,
        1.0,
        gp=gpar(
            col=NA if lwd == 0 else _value(data, "colour", "black"),
            fill=alpha_colour(_value(data, "fill", "white"), _value(data, "alpha")),
            lwd=lwd,
            lty=_value(data, "linetype", 1),
        ),
    )
    return g_tree(box, text, name="key-label")


def draw_key_boxplot(data: Mapping[str, Any], params: Mapping[str, Any], size_mm: float) -> Grob:
    del size_mm
    gp = gpar(
        col=_value(data, "colour", "grey20"),
        fill=alpha_colour(_value(data, "fill", "white"), _value(data, "alpha")),
        lwd=_number(data, "linewidth", 0.5) * POINT_PER_MM,
        lty=_value(data, "linetype", 1),
    )
    if params.get("flipped_aes"):
        children = [
            segments_grob(0.1, 0.5, 0.25, 0.5, gp=gp),
            segments_grob(0.75, 0.5, 0.9, 0.5, gp=gp),
            rect_grob(0.5, 0.5, 0.5, 0.75, gp=gp),
            segments_grob(0.5, 0.125, 0.5, 0.875, gp=gp),
        ]
    else:
        children = [
            segments_grob(0.5, 0.1, 0.5, 0.25, gp=gp),
            segments_grob(0.5, 0.75, 0.5, 0.9, gp=gp),
            rect_grob(0.5, 0.5, 0.75, 0.5, gp=gp),
            segments_grob(0.125, 0.5, 0.875, 0.5, gp=gp),
        ]
    return g_tree(*children, name="key-boxplot")


def draw_key_crossbar(data: Mapping[str, Any], params: Mapping[str, Any], size_mm: float) -> Grob:
    del size_mm
    gp = gpar(
        col=_value(data, "colour", "grey20"),
        fill=alpha_colour(_value(data, "fill", "white"), _value(data, "alpha")),
        lwd=_number(data, "linewidth", 0.5) * POINT_PER_MM,
        lty=_value(data, "linetype", 1),
    )
    if params.get("flipped_aes"):
        children = [
            rect_grob(0.5, 0.5, 0.5, 0.75, gp=gp),
            segments_grob(0.5, 0.125, 0.5, 0.875, gp=gp),
        ]
    else:
        children = [
            rect_grob(0.5, 0.5, 0.75, 0.5, gp=gp),
            segments_grob(0.125, 0.5, 0.875, 0.5, gp=gp),
        ]
    return g_tree(*children, name="key-crossbar")


def draw_key_timeseries(data: Mapping[str, Any], params: Mapping[str, Any], size_mm: float) -> Grob:
    del params, size_mm
    return lines_grob(
        [0.0, 0.4, 0.6, 1.0],
        [0.1, 0.6, 0.4, 0.9],
        gp=gpar(
            col=_paint(data, "colour", "fill", default="black"),
            lwd=_number(data, "linewidth", 0.5) * POINT_PER_MM,
            lty=_value(data, "linetype", 1),
            lineend="butt",
            linejoin="round",
        ),
        name="key-timeseries",
    )


KEY_GLYPHS: Mapping[str, Callable[[Mapping[str, Any], Mapping[str, Any], float], Any]] = {
    "point": draw_key_point,
    "rect": draw_key_rect,
    "polygon": draw_key_polygon,
    "blank": draw_key_blank,
    "path": draw_key_path,
    "vpath": draw_key_vpath,
    "abline": draw_key_abline,
    "vline": draw_key_vline,
    "dotplot": draw_key_dotplot,
    "linerange": draw_key_linerange,
    "pointrange": draw_key_pointrange,
    "smooth": draw_key_smooth,
    "text": draw_key_text,
    "label": draw_key_label,
    "boxplot": draw_key_boxplot,
    "crossbar": draw_key_crossbar,
    "timeseries": draw_key_timeseries,
}

#: 每个 geom 的缺省键（上游各 `Geom*$draw_key`）。不在表里的 geom 回落到
#: `Geom.draw()`（`_GEOM_KEYS` 模板），保持扩展 geom 的行为不变。
DEFAULT_KEY_GLYPHS: Mapping[str, str] = {
    "point": "point",
    "jitter": "point",
    "count": "point",
    "qq": "point",
    "line": "path",
    "path": "path",
    "step": "path",
    "function": "path",
    "contour": "path",
    "density_2d": "path",
    "density2d": "path",
    "qq_line": "path",
    "quantile": "path",
    "spoke": "path",
    "curve": "path",
    "segment": "path",
    "errorbar": "path",
    "errorbarh": "path",
    "hline": "path",
    "vline": "vline",
    "abline": "abline",
    "smooth": "smooth",
    "bar": "rect",
    "col": "rect",
    "histogram": "rect",
    "rect": "polygon",
    "tile": "polygon",
    "raster": "polygon",
    "polygon": "polygon",
    "area": "polygon",
    "ribbon": "polygon",
    "violin": "polygon",
    "hex": "polygon",
    "bin2d": "polygon",
    "bin_2d": "polygon",
    "contour_filled": "polygon",
    "density_2d_filled": "polygon",
    "density2d_filled": "polygon",
    "density": "polygon",
    "dotplot": "dotplot",
    "boxplot": "boxplot",
    "crossbar": "crossbar",
    "linerange": "linerange",
    "pointrange": "pointrange",
    "text": "text",
    "label": "label",
    "blank": "blank",
}


def draw_key(
    glyph: Any,
    data: Mapping[str, Any],
    params: Mapping[str, Any],
    size_mm: float,
) -> Grob | KeyGlyph:
    """按名字或可调用对象画一枚键（`key_glyph=` 的两种写法）。"""
    if callable(glyph):
        return glyph(dict(data), dict(params), size_mm)
    name = str(glyph)
    try:
        function = KEY_GLYPHS[name]
    except KeyError:
        raise ValueError(
            f"不认识的 key_glyph {name!r}（可用：{', '.join(sorted(KEY_GLYPHS))}）"
        ) from None
    return function(data, params, size_mm)


def key_glyph_for(layer: Any) -> Any:
    """图层参数里的 `key_glyph`（接受 `key.glyph` 别名）；没有返回 None。"""
    params = getattr(layer, "params", None) or {}
    for name in ("key_glyph", "key.glyph"):
        if name in params:
            return params[name]
    return None


def default_key_glyph(geom_name: str) -> str | None:
    """`Geom$draw_key` 的缺省实现（按 geom 名）；未知 geom 返回 None。"""
    return DEFAULT_KEY_GLYPHS.get(geom_name)

"""主题元素树、继承与解析（M1-10）。

对齐 ggplot2 4.0.3 的 `R/theme.R` / `R/theme-elements.R` /
`R/theme-defaults.R`：

- 元素构造器（`element_text` / `element_line` / `element_rect` /
  `element_point` / `element_polygon` / `element_geom` / `element_blank`）；
- `rel(x)` 相对尺寸、`margin()` / `margin_auto()`；
- 元素树（`ELEMENT_TREE`，含每个元素的父元素）与 `inherit.blank` 语义；
- `theme()` 局部覆盖：`None` 删除（回落到父元素），`element_blank()` 画空白；
- `merge_theme()` / `resolve_theme()`：解析阶段把每个元素折成具体值
  （字号 pt、颜色 `#RRGGBB`、线宽 mm、单位 `Unit`、边距 `Margin`）；
- 完整主题 `theme_grey()` / `theme_bw()` / `theme_minimal()` / `theme_void()`
  （`bw` 是 grey 的白底变体）。

设计口径（详见 `docs/notes/theme.md`）：

1. `rel()` **不在合并时求值**。合并只填 `None`（未设置）字段；解析时沿元素树
   从父到子逐层求值，所以 `rel(0.5)` 的父元素是 `rel(0.8)` 时只乘一次。
2. `None` 与 `element_blank()` 是两件事：前者从主题里删掉该元素、解析时回落到
   父元素；后者是「明确画空白」，解析结果是 :class:`ElementBlank`。
3. 颜色在解析时才规范化。输入可以是 R 颜色名（`grey20`、`black`）或 `#RRGGBB`；
   输出统一成 `#RRGGBB`（带 alpha 时 `#RRGGBBAA`），`NA` 折成 `None`。
4. 字号是 pt，线宽是 mm（与 ggplot2 的 `linewidth` 单位一致）。
   `element_geom.fontsize` 在 ggcore 里保持 pt（上游内部换成 mm 存放，
   仅用于绘制，见账本的「刻意差异」）。
"""

from __future__ import annotations

import numbers
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from typing import Any

import numpy as np

from ggcore.aes import frozen_mapping
from ggcore.components import Theme
from ggcore.grobs import GrobError, parse_colour
from ggcore.units import Metrics, Unit, unit

__all__ = [
    "ELEMENT_TREE",
    "NA",
    "Element",
    "ElementBlank",
    "ElementDef",
    "ElementGeom",
    "ElementLine",
    "ElementPoint",
    "ElementPolygon",
    "ElementRect",
    "ElementText",
    "Margin",
    "Rel",
    "ResolvedTheme",
    "ThemeError",
    "element_blank",
    "element_geom",
    "element_line",
    "element_point",
    "element_polygon",
    "element_rect",
    "element_text",
    "element_tree",
    "margin",
    "margin_auto",
    "merge_theme",
    "rel",
    "resolve_theme",
    "theme",
    "theme_bw",
    "theme_classic",
    "theme_dark",
    "theme_get",
    "theme_gray",
    "theme_grey",
    "theme_light",
    "theme_linedraw",
    "theme_minimal",
    "theme_replace",
    "theme_set",
    "theme_sub_axis",
    "theme_sub_axis_bottom",
    "theme_sub_axis_left",
    "theme_sub_axis_right",
    "theme_sub_axis_top",
    "theme_sub_axis_x",
    "theme_sub_axis_y",
    "theme_sub_legend",
    "theme_sub_panel",
    "theme_sub_plot",
    "theme_sub_strip",
    "theme_test",
    "theme_update",
    "theme_void",
]


class ThemeError(ValueError):
    """主题元素名、类型或解析失败。"""


class _NotAvailable:
    """显式的 `NA`：与 `None`（未设置、继承）区分。

    `element_rect(colour=NA)` 是「明确不画边框」，`element_rect()` 是「没设置，
    从父元素继承」。两者在解析前必须分开。
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "NA"


NA = _NotAvailable()


class Element:
    """所有主题元素的基类（只做类型标记）。"""

    inherit_blank: bool = False


@dataclass(frozen=True, slots=True)
class ElementBlank(Element):
    """`element_blank()`：画空白，不占空间，也不从父元素继承任何东西。"""

    inherit_blank: bool = False


@dataclass(frozen=True, slots=True)
class ElementText(Element):
    family: str | None = None
    face: str | None = None
    italic: bool | None = None
    fontweight: str | float | None = None
    fontwidth: str | float | None = None
    size: float | Rel | None = None
    colour: str | _NotAvailable | None = None
    hjust: float | None = None
    vjust: float | None = None
    angle: float | None = None
    lineheight: float | None = None
    margin: Margin | None = None
    debug: bool | None = None
    inherit_blank: bool = False


@dataclass(frozen=True, slots=True)
class ElementLine(Element):
    colour: str | _NotAvailable | None = None
    linewidth: float | Rel | None = None
    linetype: int | str | None = None
    lineend: str | None = None
    linejoin: str | None = None
    arrow: bool | None = None
    arrow_fill: str | _NotAvailable | None = None
    inherit_blank: bool = False


@dataclass(frozen=True, slots=True)
class ElementRect(Element):
    fill: str | _NotAvailable | None = None
    colour: str | _NotAvailable | None = None
    linewidth: float | Rel | None = None
    linetype: int | str | None = None
    linejoin: str | None = None
    inherit_blank: bool = False


@dataclass(frozen=True, slots=True)
class ElementPolygon(Element):
    fill: str | _NotAvailable | None = None
    colour: str | _NotAvailable | None = None
    linewidth: float | Rel | None = None
    linetype: int | str | None = None
    linejoin: str | None = None
    inherit_blank: bool = False


@dataclass(frozen=True, slots=True)
class ElementPoint(Element):
    colour: str | _NotAvailable | None = None
    shape: int | str | None = None
    size: float | Rel | None = None
    fill: str | _NotAvailable | None = None
    stroke: float | Rel | None = None
    inherit_blank: bool = False


@dataclass(frozen=True, slots=True)
class ElementGeom(Element):
    ink: str | _NotAvailable | None = None
    paper: str | _NotAvailable | None = None
    accent: str | _NotAvailable | None = None
    linewidth: float | Rel | None = None
    borderwidth: float | Rel | None = None
    linetype: int | str | None = None
    bordertype: int | str | None = None
    family: str | None = None
    fontsize: float | Rel | None = None
    pointsize: float | Rel | None = None
    pointshape: int | str | None = None
    inherit_blank: bool = False


@dataclass(frozen=True, slots=True)
class Rel:
    """`rel(x)`：相对父元素的倍数。只在解析时求值。"""

    mult: float

    def __post_init__(self) -> None:
        _check_number("rel()", self.mult)


@dataclass(frozen=True, slots=True)
class Margin:
    """一个元素的四边边距；`None` 表示 `margin_auto()` 的自动值。"""

    t: Unit | None = None
    r: Unit | None = None
    b: Unit | None = None
    l: Unit | None = None

    def as_tuple(self) -> tuple[Unit | None, Unit | None, Unit | None, Unit | None]:
        return (self.t, self.r, self.b, self.l)


def rel(mult: float) -> Rel:
    """`rel(x)`：字号/线宽相对父元素。"""
    return Rel(mult)


def element_blank() -> ElementBlank:
    return ElementBlank()


def _check_number(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ThemeError(f"{name} 必须是数值，得到 {type(value).__name__}")


def _check_colour(name: str, value: Any) -> None:
    if value is None or value is NA:
        return
    if not isinstance(value, str):
        raise ThemeError(f"{name} 必须是颜色名或 #RRGGBB，得到 {type(value).__name__}")


def _check_size(name: str, value: Any) -> None:
    if value is None or isinstance(value, Rel):
        return
    _check_number(name, value)


def _check_bool(name: str, value: Any) -> None:
    if value is not None and not isinstance(value, bool):
        raise ThemeError(f"{name} 必须是 True/False，得到 {type(value).__name__}")


def _check_str(name: str, value: Any) -> None:
    if value is not None and not isinstance(value, str):
        raise ThemeError(f"{name} 必须是字符串，得到 {type(value).__name__}")


#: R 的 `linetype` 名字（grid 的 `lty` 取值）。0–6 是数字写法；
#: 8 位十六进制串（`"#FF00FF00"`）是 R 4.x 的「自定义虚线模式」。
_LINETYPE_NAMES = frozenset(
    {"blank", "solid", "dashed", "dotted", "dotdash", "longdash", "twodash"}
)


def _check_linetype(name: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, numbers.Integral) and not isinstance(value, bool):
        if 0 <= int(value) <= 6:
            return
        raise ThemeError(f"{name} 必须是 0–6 或线型名，得到 {value!r}")
    if isinstance(value, str):
        if value in _LINETYPE_NAMES:
            return
        if len(value) == 9 and value.startswith("#") and _is_hex(value[1:]):
            return
        raise ThemeError(f"{name} 必须是线型名（{', '.join(sorted(_LINETYPE_NAMES))}）或 #RRGGBBAA")
    raise ThemeError(f"{name} 必须是整数或线型名，得到 {type(value).__name__}")


def _is_hex(value: str) -> bool:
    return all(char in "0123456789abcdefABCDEF" for char in value)


def _check_shape(name: str, value: Any) -> None:
    """`shape` / `pointshape`：R 的 `pch`，0–25 的整数或单个字符。"""
    if value is None:
        return
    if isinstance(value, numbers.Integral) and not isinstance(value, bool):
        if 0 <= int(value) <= 25:
            return
        raise ThemeError(f"{name} 必须是 0–25 的 pch，得到 {value!r}")
    if isinstance(value, str) and len(value) == 1:
        return
    raise ThemeError(f"{name} 必须是 0–25 的整数或单个字符，得到 {value!r}")


def _check_font_axis(name: str, value: Any) -> None:
    """`fontweight` / `fontwidth`：只校验类型，取值留给字体栈。

    R 侧这两项交给 systemfonts（weight 是 1–1000 的数值或 "normal" / "bold"
    这类名字，width 是 "ultra-condensed" … 这类名字），ggcore 不解释取值，
    但不能是布尔或别的对象——否则会把错误拖到渲染期。
    """
    if value is None or isinstance(value, str):
        return
    if isinstance(value, numbers.Real) and not isinstance(value, bool):
        return
    raise ThemeError(f"{name} 必须是字符串或数值，得到 {type(value).__name__}")


def element_text(
    family: str | None = None,
    face: str | None = None,
    italic: bool | None = None,
    fontweight: str | float | None = None,
    fontwidth: str | float | None = None,
    size: float | Rel | None = None,
    colour: str | _NotAvailable | None = None,
    hjust: float | None = None,
    vjust: float | None = None,
    angle: float | None = None,
    lineheight: float | None = None,
    margin: Margin | None = None,
    *,
    debug: bool | None = None,
    inherit_blank: bool = False,
    color: str | _NotAvailable | None = None,
) -> ElementText:
    """文本元素。`family` / `face` / `size` / `colour` … 未给的从父元素继承。"""
    if color is not None:
        colour = color
    _check_str("family", family)
    if face is not None and face not in ("plain", "italic", "bold", "bold.italic"):
        raise ThemeError(f"face 必须是 plain/italic/bold/bold.italic，得到 {face!r}")
    _check_bool("italic", italic)
    _check_font_axis("fontweight", fontweight)
    _check_font_axis("fontwidth", fontwidth)
    _check_size("size", size)
    _check_colour("colour", colour)
    _check_bool("debug", debug)
    for name, value in (
        ("hjust", hjust),
        ("vjust", vjust),
        ("angle", angle),
        ("lineheight", lineheight),
    ):
        if value is not None:
            _check_number(name, value)
    if margin is not None and not isinstance(margin, Margin):
        raise ThemeError("margin 必须用 margin() / margin_auto() 构造")
    return ElementText(
        family=family,
        face=face,
        italic=italic,
        fontweight=fontweight,
        fontwidth=fontwidth,
        size=size,
        colour=colour,
        hjust=hjust,
        vjust=vjust,
        angle=angle,
        lineheight=lineheight,
        margin=margin,
        debug=debug,
        inherit_blank=inherit_blank,
    )


def element_line(
    colour: str | _NotAvailable | None = None,
    linewidth: float | Rel | None = None,
    linetype: int | str | None = None,
    lineend: str | None = None,
    linejoin: str | None = None,
    *,
    arrow: bool | None = None,
    arrow_fill: str | _NotAvailable | None = None,
    inherit_blank: bool = False,
    color: str | _NotAvailable | None = None,
) -> ElementLine:
    """线条元素。`linewidth` 单位是 mm（与 ggplot2 一致）。"""
    if color is not None:
        colour = color
    if arrow is None:
        arrow = False
    if arrow_fill is None:
        arrow_fill = colour
    _check_colour("colour", colour)
    _check_colour("arrow_fill", arrow_fill)
    _check_size("linewidth", linewidth)
    _check_linetype("linetype", linetype)
    _check_bool("arrow", arrow)
    if lineend is not None and lineend not in ("round", "butt", "square"):
        raise ThemeError(f"lineend 必须是 round/butt/square，得到 {lineend!r}")
    if linejoin is not None and linejoin not in ("round", "mitre", "bevel"):
        raise ThemeError(f"linejoin 必须是 round/mitre/bevel，得到 {linejoin!r}")
    return ElementLine(
        colour=colour,
        linewidth=linewidth,
        linetype=linetype,
        lineend=lineend,
        linejoin=linejoin,
        arrow=arrow,
        arrow_fill=arrow_fill,
        inherit_blank=inherit_blank,
    )


def element_rect(
    fill: str | _NotAvailable | None = None,
    colour: str | _NotAvailable | None = None,
    linewidth: float | Rel | None = None,
    linetype: int | str | None = None,
    linejoin: str | None = None,
    *,
    inherit_blank: bool = False,
    color: str | _NotAvailable | None = None,
) -> ElementRect:
    if color is not None:
        colour = color
    _check_colour("fill", fill)
    _check_colour("colour", colour)
    _check_size("linewidth", linewidth)
    _check_linetype("linetype", linetype)
    if linejoin is not None and linejoin not in ("round", "mitre", "bevel"):
        raise ThemeError(f"linejoin 必须是 round/mitre/bevel，得到 {linejoin!r}")
    return ElementRect(
        fill=fill,
        colour=colour,
        linewidth=linewidth,
        linetype=linetype,
        linejoin=linejoin,
        inherit_blank=inherit_blank,
    )


def element_polygon(
    fill: str | _NotAvailable | None = None,
    colour: str | _NotAvailable | None = None,
    linewidth: float | Rel | None = None,
    linetype: int | str | None = None,
    linejoin: str | None = None,
    *,
    inherit_blank: bool = False,
    color: str | _NotAvailable | None = None,
) -> ElementPolygon:
    if color is not None:
        colour = color
    _check_colour("fill", fill)
    _check_colour("colour", colour)
    _check_size("linewidth", linewidth)
    _check_linetype("linetype", linetype)
    if linejoin is not None and linejoin not in ("round", "mitre", "bevel"):
        raise ThemeError(f"linejoin 必须是 round/mitre/bevel，得到 {linejoin!r}")
    return ElementPolygon(
        fill=fill,
        colour=colour,
        linewidth=linewidth,
        linetype=linetype,
        linejoin=linejoin,
        inherit_blank=inherit_blank,
    )


def element_point(
    colour: str | _NotAvailable | None = None,
    shape: int | str | None = None,
    size: float | Rel | None = None,
    fill: str | _NotAvailable | None = None,
    stroke: float | Rel | None = None,
    *,
    inherit_blank: bool = False,
    color: str | _NotAvailable | None = None,
) -> ElementPoint:
    if color is not None:
        colour = color
    _check_colour("colour", colour)
    _check_colour("fill", fill)
    _check_shape("shape", shape)
    _check_size("size", size)
    _check_size("stroke", stroke)
    return ElementPoint(
        colour=colour,
        shape=shape,
        size=size,
        fill=fill,
        stroke=stroke,
        inherit_blank=inherit_blank,
    )


def element_geom(
    ink: str | _NotAvailable | None = None,
    paper: str | _NotAvailable | None = None,
    accent: str | _NotAvailable | None = None,
    linewidth: float | Rel | None = None,
    borderwidth: float | Rel | None = None,
    linetype: int | str | None = None,
    bordertype: int | str | None = None,
    family: str | None = None,
    fontsize: float | Rel | None = None,
    pointsize: float | Rel | None = None,
    pointshape: int | str | None = None,
    *,
    inherit_blank: bool = False,
) -> ElementGeom:
    """图层默认样式（4.0.3 的 `element_geom`）；`fontsize` 在 ggcore 里是 pt。"""
    for name, value in (("ink", ink), ("paper", paper), ("accent", accent)):
        _check_colour(name, value)
    _check_size("linewidth", linewidth)
    _check_size("borderwidth", borderwidth)
    _check_linetype("linetype", linetype)
    _check_linetype("bordertype", bordertype)
    _check_str("family", family)
    _check_size("fontsize", fontsize)
    _check_size("pointsize", pointsize)
    _check_shape("pointshape", pointshape)
    return ElementGeom(
        ink=ink,
        paper=paper,
        accent=accent,
        linewidth=linewidth,
        borderwidth=borderwidth,
        linetype=linetype,
        bordertype=bordertype,
        family=family,
        fontsize=fontsize,
        pointsize=pointsize,
        pointshape=pointshape,
        inherit_blank=inherit_blank,
    )


def _margin_side(value: Any, kind: str) -> Unit | None:
    if value is None:
        return None
    if isinstance(value, Unit):
        return value
    if isinstance(value, np.ndarray) and value.size == 1:
        value = float(value.reshape(-1)[0])
    if isinstance(value, float) and np.isnan(value):
        return None
    if isinstance(value, numbers.Real) and not isinstance(value, bool):
        return unit(float(value), kind)
    raise ThemeError(f"margin 的边必须是数值或 Unit，得到 {type(value).__name__}")


def margin(
    t: float | Unit = 0,
    r: float | Unit = 0,
    b: float | Unit = 0,
    l: float | Unit = 0,
    unit: str = "pt",
) -> Margin:
    """`margin(t, r, b, l, unit="pt")`：四边边距。"""
    return Margin(
        t=_margin_side(t, unit),
        r=_margin_side(r, unit),
        b=_margin_side(b, unit),
        l=_margin_side(l, unit),
    )


_UNSET: Any = object()


def margin_auto(
    t: float | Unit | None = 0,
    r: float | Unit | None = _UNSET,
    b: float | Unit | None = _UNSET,
    l: float | Unit | None = _UNSET,
    unit: str = "pt",
) -> Margin:
    """`margin_auto(t, r=t, b=t, l=r)`：没给的边（或 `NA`）交给布局阶段决定。"""
    if r is _UNSET:
        r = t
    if b is _UNSET:
        b = t
    if l is _UNSET:
        l = r
    return Margin(
        t=_margin_side(t, unit),
        r=_margin_side(r, unit),
        b=_margin_side(b, unit),
        l=_margin_side(l, unit),
    )


# ---------------------------------------------------------------------------
# 元素树（ggplot2 4.0.3 的 .element_tree；palette.* 暂不支持）
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ElementDef:
    """一个元素的节点：类型 + 父元素（第一个父元素优先）。"""

    kind: str
    parents: tuple[str, ...] = ()


_ELEMENT_KINDS: Mapping[str, type[Element]] = {
    "text": ElementText,
    "line": ElementLine,
    "rect": ElementRect,
    "polygon": ElementPolygon,
    "point": ElementPoint,
    "geom": ElementGeom,
}

_KIND_LABELS: Mapping[str, tuple[str, ...]] = {
    "unit": ("Unit", "rel"),
    "margin": ("Margin", "Unit"),
    "scalar": ("str", "bool", "数值"),
}

ELEMENT_TREE: Mapping[str, ElementDef] = frozen_mapping(
    {
        "line": ElementDef("line"),
        "rect": ElementDef("rect"),
        "text": ElementDef("text"),
        "point": ElementDef("point"),
        "polygon": ElementDef("polygon"),
        "geom": ElementDef("geom"),
        "title": ElementDef("text", ("text",)),
        "spacing": ElementDef("unit"),
        "margins": ElementDef("margin"),
        "axis.line": ElementDef("line", ("line",)),
        "axis.text": ElementDef("text", ("text",)),
        "axis.title": ElementDef("text", ("title",)),
        "axis.ticks": ElementDef("line", ("line",)),
        "legend.key.size": ElementDef("unit", ("spacing",)),
        "panel.grid": ElementDef("line", ("line",)),
        "panel.grid.major": ElementDef("line", ("panel.grid",)),
        "panel.grid.minor": ElementDef("line", ("panel.grid",)),
        "strip.text": ElementDef("text", ("text",)),
        "axis.line.x": ElementDef("line", ("axis.line",)),
        "axis.line.x.top": ElementDef("line", ("axis.line.x",)),
        "axis.line.x.bottom": ElementDef("line", ("axis.line.x",)),
        "axis.line.y": ElementDef("line", ("axis.line",)),
        "axis.line.y.left": ElementDef("line", ("axis.line.y",)),
        "axis.line.y.right": ElementDef("line", ("axis.line.y",)),
        "axis.line.theta": ElementDef("line", ("axis.line.x",)),
        "axis.line.r": ElementDef("line", ("axis.line.y",)),
        "axis.text.x": ElementDef("text", ("axis.text",)),
        "axis.text.x.top": ElementDef("text", ("axis.text.x",)),
        "axis.text.x.bottom": ElementDef("text", ("axis.text.x",)),
        "axis.text.y": ElementDef("text", ("axis.text",)),
        "axis.text.y.left": ElementDef("text", ("axis.text.y",)),
        "axis.text.y.right": ElementDef("text", ("axis.text.y",)),
        "axis.text.theta": ElementDef("text", ("axis.text.x",)),
        "axis.text.r": ElementDef("text", ("axis.text.y",)),
        "axis.ticks.length": ElementDef("unit", ("spacing",)),
        "axis.ticks.length.x": ElementDef("unit", ("axis.ticks.length",)),
        "axis.ticks.length.x.top": ElementDef("unit", ("axis.ticks.length.x",)),
        "axis.ticks.length.x.bottom": ElementDef("unit", ("axis.ticks.length.x",)),
        "axis.ticks.length.y": ElementDef("unit", ("axis.ticks.length",)),
        "axis.ticks.length.y.left": ElementDef("unit", ("axis.ticks.length.y",)),
        "axis.ticks.length.y.right": ElementDef("unit", ("axis.ticks.length.y",)),
        "axis.ticks.length.theta": ElementDef("unit", ("axis.ticks.length.x",)),
        "axis.ticks.length.r": ElementDef("unit", ("axis.ticks.length.y",)),
        "axis.ticks.x": ElementDef("line", ("axis.ticks",)),
        "axis.ticks.x.top": ElementDef("line", ("axis.ticks.x",)),
        "axis.ticks.x.bottom": ElementDef("line", ("axis.ticks.x",)),
        "axis.ticks.y": ElementDef("line", ("axis.ticks",)),
        "axis.ticks.y.left": ElementDef("line", ("axis.ticks.y",)),
        "axis.ticks.y.right": ElementDef("line", ("axis.ticks.y",)),
        "axis.ticks.theta": ElementDef("line", ("axis.ticks.x",)),
        "axis.ticks.r": ElementDef("line", ("axis.ticks.y",)),
        "axis.title.x": ElementDef("text", ("axis.title",)),
        "axis.title.x.top": ElementDef("text", ("axis.title.x",)),
        "axis.title.x.bottom": ElementDef("text", ("axis.title.x",)),
        "axis.title.y": ElementDef("text", ("axis.title",)),
        "axis.title.y.left": ElementDef("text", ("axis.title.y",)),
        "axis.title.y.right": ElementDef("text", ("axis.title.y",)),
        "axis.minor.ticks.x.top": ElementDef("line", ("axis.ticks.x.top",)),
        "axis.minor.ticks.x.bottom": ElementDef("line", ("axis.ticks.x.bottom",)),
        "axis.minor.ticks.y.left": ElementDef("line", ("axis.ticks.y.left",)),
        "axis.minor.ticks.y.right": ElementDef("line", ("axis.ticks.y.right",)),
        "axis.minor.ticks.theta": ElementDef("line", ("axis.ticks.theta",)),
        "axis.minor.ticks.r": ElementDef("line", ("axis.ticks.r",)),
        "axis.minor.ticks.length": ElementDef("unit"),
        "axis.minor.ticks.length.x": ElementDef("unit", ("axis.minor.ticks.length",)),
        "axis.minor.ticks.length.x.top": ElementDef(
            "unit", ("axis.minor.ticks.length.x", "axis.ticks.length.x.top")
        ),
        "axis.minor.ticks.length.x.bottom": ElementDef(
            "unit", ("axis.minor.ticks.length.x", "axis.ticks.length.x.bottom")
        ),
        "axis.minor.ticks.length.y": ElementDef("unit", ("axis.minor.ticks.length",)),
        "axis.minor.ticks.length.y.left": ElementDef(
            "unit", ("axis.minor.ticks.length.y", "axis.ticks.length.y.left")
        ),
        "axis.minor.ticks.length.y.right": ElementDef(
            "unit", ("axis.minor.ticks.length.y", "axis.ticks.length.y.right")
        ),
        "axis.minor.ticks.length.theta": ElementDef(
            "unit", ("axis.minor.ticks.length.x", "axis.ticks.length.theta")
        ),
        "axis.minor.ticks.length.r": ElementDef(
            "unit", ("axis.minor.ticks.length.y", "axis.ticks.length.r")
        ),
        "legend.background": ElementDef("rect", ("rect",)),
        "legend.margin": ElementDef("margin", ("margins",)),
        "legend.spacing": ElementDef("unit", ("spacing",)),
        "legend.spacing.x": ElementDef("unit", ("legend.spacing",)),
        "legend.spacing.y": ElementDef("unit", ("legend.spacing",)),
        "legend.key": ElementDef("rect", ("panel.background",)),
        "legend.key.height": ElementDef("unit", ("legend.key.size",)),
        "legend.key.width": ElementDef("unit", ("legend.key.size",)),
        "legend.key.spacing": ElementDef("unit", ("spacing",)),
        "legend.key.spacing.x": ElementDef("unit", ("legend.key.spacing",)),
        "legend.key.spacing.y": ElementDef("unit", ("legend.key.spacing",)),
        "legend.key.justification": ElementDef("scalar"),
        "legend.frame": ElementDef("rect", ("rect",)),
        "legend.axis.line": ElementDef("line", ("line",)),
        "legend.ticks": ElementDef("line", ("legend.axis.line",)),
        "legend.ticks.length": ElementDef("unit", ("legend.key.size",)),
        "legend.text": ElementDef("text", ("text",)),
        "legend.text.position": ElementDef("scalar"),
        "legend.title": ElementDef("text", ("title",)),
        "legend.title.position": ElementDef("scalar"),
        "legend.byrow": ElementDef("scalar"),
        "legend.position": ElementDef("scalar"),
        "legend.position.inside": ElementDef("scalar"),
        "legend.direction": ElementDef("scalar"),
        "legend.justification": ElementDef("scalar"),
        "legend.justification.top": ElementDef("scalar", ("legend.justification",)),
        "legend.justification.bottom": ElementDef("scalar", ("legend.justification",)),
        "legend.justification.left": ElementDef("scalar", ("legend.justification",)),
        "legend.justification.right": ElementDef("scalar", ("legend.justification",)),
        "legend.justification.inside": ElementDef("scalar", ("legend.justification",)),
        "legend.location": ElementDef("scalar"),
        "legend.box": ElementDef("scalar"),
        "legend.box.just": ElementDef("scalar"),
        "legend.box.margin": ElementDef("margin", ("margins",)),
        "legend.box.background": ElementDef("rect", ("rect",)),
        "legend.box.spacing": ElementDef("unit", ("spacing",)),
        "panel.background": ElementDef("rect", ("rect",)),
        "panel.border": ElementDef("rect", ("rect",)),
        "panel.spacing": ElementDef("unit", ("spacing",)),
        "panel.spacing.x": ElementDef("unit", ("panel.spacing",)),
        "panel.spacing.y": ElementDef("unit", ("panel.spacing",)),
        "panel.grid.major.x": ElementDef("line", ("panel.grid.major",)),
        "panel.grid.major.y": ElementDef("line", ("panel.grid.major",)),
        "panel.grid.minor.x": ElementDef("line", ("panel.grid.minor",)),
        "panel.grid.minor.y": ElementDef("line", ("panel.grid.minor",)),
        "panel.ontop": ElementDef("scalar"),
        "panel.widths": ElementDef("unit"),
        "panel.heights": ElementDef("unit"),
        "strip.background": ElementDef("rect", ("rect",)),
        "strip.background.x": ElementDef("rect", ("strip.background",)),
        "strip.background.y": ElementDef("rect", ("strip.background",)),
        "strip.clip": ElementDef("scalar"),
        "strip.text.x": ElementDef("text", ("strip.text",)),
        "strip.text.x.top": ElementDef("text", ("strip.text.x",)),
        "strip.text.x.bottom": ElementDef("text", ("strip.text.x",)),
        "strip.text.y": ElementDef("text", ("strip.text",)),
        "strip.text.y.left": ElementDef("text", ("strip.text.y",)),
        "strip.text.y.right": ElementDef("text", ("strip.text.y",)),
        "strip.placement": ElementDef("scalar"),
        "strip.placement.x": ElementDef("scalar", ("strip.placement",)),
        "strip.placement.y": ElementDef("scalar", ("strip.placement",)),
        "strip.switch.pad.grid": ElementDef("unit", ("spacing",)),
        "strip.switch.pad.wrap": ElementDef("unit", ("spacing",)),
        "plot.background": ElementDef("rect", ("rect",)),
        "plot.title": ElementDef("text", ("title",)),
        "plot.title.position": ElementDef("scalar"),
        "plot.subtitle": ElementDef("text", ("text",)),
        "plot.caption": ElementDef("text", ("text",)),
        "plot.caption.position": ElementDef("scalar"),
        "plot.tag": ElementDef("text", ("text",)),
        "plot.tag.position": ElementDef("scalar"),
        "plot.tag.location": ElementDef("scalar"),
        "plot.margin": ElementDef("margin", ("margins",)),
        "aspect.ratio": ElementDef("scalar"),
    }
)


def element_tree() -> Mapping[str, ElementDef]:
    """当前生效的元素树（名字 → 类型 + 父元素）。"""
    return ELEMENT_TREE


def _check_element(name: str, value: Any) -> None:
    node = ELEMENT_TREE[name]
    if value is None or isinstance(value, ElementBlank):
        return
    if node.kind in _ELEMENT_KINDS:
        expected = _ELEMENT_KINDS[node.kind]
        if not isinstance(value, expected):
            raise ThemeError(
                f"主题元素 {name!r} 必须是 {expected.__name__}，得到 {type(value).__name__}"
            )
        return
    if isinstance(value, Element):
        raise ThemeError(
            f"主题元素 {name!r} 不是元素对象（期望 {'/'.join(_KIND_LABELS[node.kind])}）"
        )
    if node.kind == "unit" and not isinstance(value, (Unit, Rel)):
        raise ThemeError(f"主题元素 {name!r} 必须是 Unit 或 rel()，得到 {type(value).__name__}")
    if node.kind == "margin" and not isinstance(value, (Margin, Unit)):
        raise ThemeError(f"主题元素 {name!r} 必须是 margin() 或 Unit，得到 {type(value).__name__}")


# ---------------------------------------------------------------------------
# theme() / merge_theme()
# ---------------------------------------------------------------------------


def theme(complete: bool = False, **elements: Any) -> Theme:
    """局部主题：只覆盖给到的元素。

    - `theme(**{"panel.grid": element_blank()})` → 画空白；
    - `theme(**{"panel.grid": None})` → 删除该元素，解析时回落到父元素；
    - 未知元素名直接报错（ggplot2 对拼写错误同样报错）。
    """
    unknown = [name for name in elements if name not in ELEMENT_TREE]
    if unknown:
        available = ", ".join(sorted(ELEMENT_TREE))
        raise ThemeError(
            f"未知主题元素 {', '.join(repr(name) for name in unknown)}；"
            f"可用元素（{len(ELEMENT_TREE)}）：{available}"
        )
    for name, value in elements.items():
        _check_element(name, value)
    if complete:
        elements = {name: _inherit_blank(value) for name, value in elements.items()}
    return Theme(name="", elements=elements, complete=complete)


def _inherit_blank(value: Any) -> Any:
    """完整主题里的非 blank 元素 `inherit.blank=TRUE`（theme(complete=TRUE)）。"""
    if isinstance(value, Element) and not isinstance(value, ElementBlank):
        return replace(value, inherit_blank=True)
    return value


def merge_theme(base: Theme | None, override: Theme | None) -> Theme:
    """`base + override`：完整主题整份替换，局部主题逐个元素递归合并。"""
    if override is None:
        return base if base is not None else Theme()
    if base is None or override.complete:
        return override
    merged = dict(base.elements)
    for name, new in override.elements.items():
        merged[name] = _merge_element(name, new, base.elements.get(name))
    return Theme(
        name=base.name,
        elements=merged,
        complete=base.complete,
        base_size=base.base_size,
    )


def _merge_element(name: str, new: Any, old: Any) -> Any:
    """把 `old` 合并进 `new`（只填 None，不求 rel）。"""
    if new is None or isinstance(new, ElementBlank):
        return new
    if old is None or isinstance(old, ElementBlank):
        return new
    if isinstance(new, Margin) and isinstance(old, Margin):
        return Margin(
            t=new.t if new.t is not None else old.t,
            r=new.r if new.r is not None else old.r,
            b=new.b if new.b is not None else old.b,
            l=new.l if new.l is not None else old.l,
        )
    if isinstance(new, Element) and isinstance(old, Element):
        if type(new) is not type(old):
            raise ThemeError(
                f"主题元素 {name!r} 只能合并同类元素：{type(new).__name__} vs {type(old).__name__}"
            )
        updates: dict[str, Any] = {}
        for element_field in fields(new):
            if element_field.name == "inherit_blank":
                continue
            value = getattr(new, element_field.name)
            if value is None:
                updates[element_field.name] = getattr(old, element_field.name)
            elif element_field.name == "margin" and isinstance(value, Margin):
                updates[element_field.name] = _merge_element(
                    name, value, getattr(old, element_field.name)
                )
        return replace(new, **updates)
    return new


# ---------------------------------------------------------------------------
# 解析：元素树继承 + rel / 单位 / 颜色落成具体值
# ---------------------------------------------------------------------------


def _combine_margin(child: Margin, parent: Any) -> Margin:
    if not isinstance(parent, Margin):
        return child
    return Margin(
        t=child.t if child.t is not None else parent.t,
        r=child.r if child.r is not None else parent.r,
        b=child.b if child.b is not None else parent.b,
        l=child.l if child.l is not None else parent.l,
    )


def _apply_rel(value: Rel, base: Any) -> Any:
    if isinstance(base, Rel):
        return Rel(value.mult * base.mult)
    if isinstance(base, Unit):
        return base * value.mult
    if isinstance(base, numbers.Real) and not isinstance(base, bool):
        return value.mult * float(base)
    return value


def _combine(child: Any, parent: Any) -> Any:
    """`combine_elements(e1=child, e2=parent)` 的 Python 版。"""
    if parent is None:
        return child
    if isinstance(child, ElementBlank):
        return child
    if isinstance(parent, ElementBlank):
        if child is None:
            return parent
        if isinstance(child, Element) and child.inherit_blank:
            return parent
        return child
    if child is None:
        return parent
    if isinstance(child, Rel):
        return _apply_rel(child, parent)
    if isinstance(child, Margin):
        return _combine_margin(child, parent)
    if not isinstance(child, Element):
        return child
    if not isinstance(parent, Element):
        return child
    updates: dict[str, Any] = {}
    for element_field in fields(child):
        if element_field.name == "inherit_blank":
            continue
        value = getattr(child, element_field.name)
        other = getattr(parent, element_field.name)
        if value is None:
            updates[element_field.name] = other
        elif element_field.name in ("size", "linewidth") and isinstance(value, Rel):
            updates[element_field.name] = _apply_rel(value, other)
        elif element_field.name == "margin" and isinstance(value, Margin):
            updates[element_field.name] = _combine_margin(value, other)
    return replace(child, **updates)


def _canonical_colour(value: Any) -> str | None:
    if value is None or value is NA:
        return None
    try:
        red, green, blue, alpha = parse_colour(value)
    except GrobError as error:
        raise ThemeError(str(error)) from None
    if alpha == 255:
        return f"#{red:02X}{green:02X}{blue:02X}"
    return f"#{red:02X}{green:02X}{blue:02X}{alpha:02X}"


_COLOUR_FIELDS = frozenset({"colour", "fill", "arrow_fill", "ink", "paper", "accent"})


def _resolve_value(value: Any) -> Any:
    """把解析后的元素里剩下的颜色折成规范值。"""
    if isinstance(value, Element):
        updates = {
            element_field.name: _canonical_colour(getattr(value, element_field.name))
            for element_field in fields(value)
            if element_field.name in _COLOUR_FIELDS
        }
        return replace(value, **updates) if updates else value
    return value


def _root_name(name: str) -> str:
    while ELEMENT_TREE[name].parents:
        name = ELEMENT_TREE[name].parents[0]
    return name


def _resolve_root_rels(value: Any, root_values: Mapping[str, Any], name: str) -> Any:
    """把根元素上剩下的 `rel()` 折成具体值。

    ggplot2 的 `calc_element()` 对根元素（`text` / `line` / …）的 `rel()` 保持
    原样，等渲染时再消费；`resolve_theme()` 的契约是「每个元素都是可断言的具体
    值」，所以这里按主题的 `base_size` 折成 pt/mm。父元素链上的 `rel()` 已在
    :func:`_combine` 里求值，这里只处理根元素这一层。
    """
    if not isinstance(value, Element):
        return value
    root = root_values.get(_root_name(name))
    if not isinstance(root, Element):
        return value
    updates: dict[str, Any] = {}
    for field_name in ("size", "linewidth"):
        current = getattr(value, field_name, None)
        base = getattr(root, field_name, None)
        if isinstance(current, Rel) and isinstance(base, numbers.Real):
            updates[field_name] = current.mult * float(base)
    return replace(value, **updates) if updates else value


_ROOT_NAMES = ("text", "line", "rect", "point", "polygon", "geom")

_base_theme_cache: Theme | None = None


def _base_theme() -> Theme:
    """`ggplot_global$theme_default` 的对应物：包内置的 `theme_grey()`。

    它只用来补齐根元素缺失的字段（见 :func:`_fill_root_defaults`），与
    `theme_get()`（用户可改的全局默认）不是一回事。
    """
    global _base_theme_cache
    if _base_theme_cache is None:
        _base_theme_cache = theme_grey()
    return _base_theme_cache


def _fill_root_defaults(name: str, value: Any) -> Any:
    """没有父元素的根元素：用内置 `theme_grey()` 的同名元素补齐 `None` 字段。

    对应 `calc_element()` 里 `pnames` 为 NULL 那一支：它把剩下的 null 属性
    与 `ggplot_global$theme_default[[element]]` 合并（`theme_test()` 的 `geom`
    没写 `bordertype`，解析值因此是 1，正是这一步）。删掉的根（值为 `None`）
    与 `element_blank()` 不走这里——R 侧同样直接返回。
    """
    if not isinstance(value, Element):
        return value
    default = _base_theme().elements.get(name)
    if not isinstance(default, Element) or type(default) is not type(value):
        return value
    updates: dict[str, Any] = {}
    for element_field in fields(value):
        if element_field.name == "inherit_blank":
            continue
        if getattr(value, element_field.name) is None:
            updates[element_field.name] = getattr(default, element_field.name)
    return replace(value, **updates) if updates else value


def _resolve_one(
    theme: Theme,
    name: str,
    cache: dict[tuple[str, bool], Any],
    root_values: Mapping[str, Any],
    skip_blank: bool = False,
) -> Any:
    """`calc_element()` 的 Python 版：沿元素树自下而上合并。

    `skip_blank` 对应 `calc_element(skip_blank=)`：子元素 `inherit.blank=FALSE`
    时，blank 父元素被跳过、继续向更上层找默认值（`theme_classic()` 的
    `axis.line.x` 就是这样从 `line` 拿到颜色与线宽的）。缓存键带上这个标记，
    同一个元素在两种模式下各算一次。
    """
    key = (name, skip_blank)
    if key in cache:
        return cache[key]
    node = ELEMENT_TREE[name]
    value = theme.elements.get(name)
    if isinstance(value, ElementBlank):
        if not skip_blank:
            cache[key] = value
            return value
        value = None
    child_skip = skip_blank or (
        value is not None and not (isinstance(value, Element) and value.inherit_blank)
    )
    if not node.parents:
        value = _fill_root_defaults(name, value)
    for parent_name in node.parents:
        value = _combine(
            value,
            _resolve_one(theme, parent_name, cache, root_values, child_skip),
        )
    value = _resolve_root_rels(value, root_values, name)
    resolved = _resolve_value(value)
    cache[key] = resolved
    return resolved


@dataclass(frozen=True, slots=True)
class ResolvedTheme:
    """解析后的主题：每个元素都是可断言的具体值（颜色已规范化）。

    `Rel` 只在这几处保留，其余都折成 pt/mm：

    - `point.stroke`、`geom.borderwidth` / `geom.fontsize` / `geom.pointsize`
      这几个非 `size` / `linewidth` 的字段与 R 的 `calc_element()` 一致，
      渲染时才相对根元素消费；
    - 没有父元素的 `axis.minor.ticks.length*`（主题值 `rel(0.75)`），
      由 guide 相对主轴刻度消费。

    `metrics` 目前只为后续 `strwidth` / `strheight` 单位与 guide 布局保留；
    本任务的元素值不依赖字体度量。
    """

    elements: Mapping[str, Any]
    metrics: Metrics | None = None
    theme: Theme | None = None

    def __getitem__(self, name: str) -> Any:
        try:
            return self.elements[name]
        except KeyError:
            raise ThemeError(
                f"未知主题元素 {name!r}；可用元素（{len(ELEMENT_TREE)}）："
                f"{', '.join(sorted(ELEMENT_TREE))}"
            ) from None

    def get(self, name: str, default: Any = None) -> Any:
        return self.elements.get(name, default)

    def __contains__(self, name: object) -> bool:
        return name in self.elements

    def size_pt(self, name: str) -> float:
        """某文本元素的最终字号（pt），例如 `size_pt("axis.text")`。"""
        element = self[name]
        if not isinstance(element, ElementText):
            raise ThemeError(f"主题元素 {name!r} 不是文本元素，没有字号")
        if element.size is None:
            raise ThemeError(f"主题元素 {name!r} 没有解析出字号")
        return float(element.size)

    def is_blank(self, name: str) -> bool:
        return isinstance(self[name], ElementBlank)


def resolve_theme(theme: Theme, metrics: Metrics | None = None) -> ResolvedTheme:
    """把主题解析成具体值；局部主题以 `theme_get()` 为底。

    `theme_get()` 的初值是 `theme_grey()`，`theme_set()` 之后是新的全局默认
    （对应上游 `calc_element(element, plot_theme(plot))` 里 `theme_get()` 的
    位置）。
    """
    if not isinstance(theme, Theme):
        raise TypeError(f"resolve_theme() 需要 Theme，得到 {type(theme).__name__}")
    base = theme if theme.complete else merge_theme(theme_get(), theme)
    # 根元素 `rel()` 的折算基准始终取 `theme_grey(base_size)`：与上游把根
    # `rel` 留到渲染期「相对 base_size」的口径一致，不受某个主题把根元素写成
    # rel 的影响（否则 1.5 × 0.8 会被折两次）。
    root_values = theme_grey(base_size=base.base_size).elements
    cache: dict[str, Any] = {}
    resolved = {name: _resolve_one(base, name, cache, root_values) for name in ELEMENT_TREE}
    return ResolvedTheme(elements=frozen_mapping(resolved), metrics=metrics, theme=base)


# ---------------------------------------------------------------------------
# 完整主题（数值照 R/theme-defaults.R，4.0.3）
# ---------------------------------------------------------------------------


def _mix_colour(first: str, second: str, amount: float = 0.5) -> str:
    """`scales::col_mix(a, b, amount)`（space="rgb"）：`amount` 是 b 的权重。"""
    red_a, green_a, blue_a, alpha_a = parse_colour(first)
    red_b, green_b, blue_b, alpha_b = parse_colour(second)
    channels = [
        round(a * (1.0 - amount) + b * amount)
        for a, b in (
            (red_a, red_b),
            (green_a, green_b),
            (blue_a, blue_b),
            (alpha_a, alpha_b),
        )
    ]
    out = f"#{channels[0]:02X}{channels[1]:02X}{channels[2]:02X}"
    return out if channels[3] == 255 else f"{out}{channels[3]:02X}"


def _with_alpha(colour: str, alpha: float) -> str:
    red, green, blue, _ = parse_colour(colour)
    value = round(alpha * 255)
    return f"#{red:02X}{green:02X}{blue:02X}{value:02X}"


def _complete(name: str, elements: Mapping[str, Any], base_size: float = 11.0) -> Theme:
    return Theme(
        name=name,
        elements={key: _inherit_blank(value) for key, value in elements.items()},
        complete=True,
        base_size=base_size,
    )


def _replace(
    base: Theme,
    name: str,
    updates: Mapping[str, Any],
    *,
    complete: bool = True,
) -> Theme:
    """`base %+replace% theme(...)`：整份替换同名元素，不合并字段。

    `complete` 对应上游 `theme(..., complete = TRUE)`：四个内置主题族
    （`theme_bw()` 起）都是 `theme_grey() %+replace% theme(..., complete=TRUE)`，
    换进来的元素因此带 `inherit.blank=TRUE`。`theme_replace()` 走的是不带
    `complete` 的 `theme(...)`，换进来的元素保持构造值 `inherit.blank=FALSE`
    （R/theme-current.R: `replace_theme <- function(...) set_theme(get_theme()
    %+replace% theme(...))`）——此时 base 的旧元素原样保留它们自己的标记。
    """
    elements = dict(base.elements)
    if complete:
        elements.update({key: _inherit_blank(value) for key, value in updates.items()})
    else:
        elements.update(updates)
    return Theme(name=name, elements=elements, complete=True, base_size=base.base_size)


def theme_grey(
    base_size: float = 11,
    base_family: str = "",
    header_family: str | None = None,
    base_line_size: float | None = None,
    base_rect_size: float | None = None,
    ink: str = "black",
    paper: str = "white",
    accent: str = "#3366FF",
) -> Theme:
    """ggplot2 的默认主题（`R/theme-defaults.R: theme_grey`）。"""
    if base_line_size is None:
        base_line_size = base_size / 22
    if base_rect_size is None:
        base_rect_size = base_size / 22
    half_line = base_size / 2
    text_mid = _mix_colour(ink, paper, 0.302)
    tick_grey = _mix_colour(ink, paper, 0.2)
    panel_grey = _mix_colour(ink, paper, 0.92)
    strip_grey = _mix_colour(ink, paper, 0.85)
    strip_text_grey = _mix_colour(ink, paper, 0.1)
    elements: dict[str, Any] = {
        # 只被继承、不直接使用的基元素
        "line": element_line(
            colour=ink,
            linewidth=base_line_size,
            linetype=1,
            lineend="butt",
            linejoin="round",
        ),
        "rect": element_rect(
            fill=paper,
            colour=ink,
            linewidth=base_rect_size,
            linetype=1,
            linejoin="round",
        ),
        "text": element_text(
            family=base_family,
            face="plain",
            colour=ink,
            size=base_size,
            lineheight=0.9,
            hjust=0.5,
            vjust=0.5,
            angle=0,
            margin=margin(),
            debug=False,
        ),
        "title": element_text(family=header_family),
        "spacing": unit(half_line, "pt"),
        "margins": margin_auto(half_line),
        "point": element_point(
            colour=ink,
            shape=19,
            fill=paper,
            size=(base_size / 11) * 1.5,
            stroke=base_line_size,
        ),
        "polygon": element_polygon(
            fill=paper,
            colour=ink,
            linewidth=base_rect_size,
            linetype=1,
            linejoin="round",
        ),
        "geom": element_geom(
            ink=ink,
            paper=paper,
            accent=accent,
            linewidth=base_line_size,
            borderwidth=base_line_size,
            linetype=1,
            bordertype=1,
            family=base_family,
            fontsize=base_size,
            pointsize=(base_size / 11) * 1.5,
            pointshape=19,
        ),
        "axis.line": element_blank(),
        "axis.text": element_text(size=rel(0.8), colour=text_mid),
        "axis.text.x": element_text(margin=margin(t=0.8 * half_line / 2), vjust=1),
        "axis.text.x.top": element_text(margin=margin(b=0.8 * half_line / 2), vjust=0),
        "axis.text.y": element_text(margin=margin(r=0.8 * half_line / 2), hjust=1),
        "axis.text.y.right": element_text(margin=margin(l=0.8 * half_line / 2), hjust=0),
        "axis.text.r": element_text(
            margin=margin(l=0.8 * half_line / 2, r=0.8 * half_line / 2),
            hjust=0.5,
        ),
        "axis.ticks": element_line(colour=tick_grey),
        "axis.ticks.length": rel(0.5),
        "axis.minor.ticks.length": rel(0.75),
        "axis.title.x": element_text(margin=margin(t=half_line / 2), vjust=1),
        "axis.title.x.top": element_text(margin=margin(b=half_line / 2), vjust=0),
        "axis.title.y": element_text(angle=90, margin=margin(r=half_line / 2), vjust=1),
        "axis.title.y.right": element_text(angle=-90, margin=margin(l=half_line / 2), vjust=1),
        "legend.background": element_rect(colour=NA),
        "legend.spacing": rel(2),
        "legend.key.size": unit(1.2, "lines"),
        "legend.text": element_text(size=rel(0.8)),
        "legend.title": element_text(hjust=0),
        "legend.ticks.length": rel(0.2),
        "legend.position": "right",
        "legend.justification": "center",
        "legend.box.margin": margin_auto(0),
        "legend.box.background": element_blank(),
        "legend.box.spacing": rel(2),
        "panel.background": element_rect(fill=panel_grey, colour=NA),
        "panel.border": element_blank(),
        "panel.grid": element_line(colour=paper),
        "panel.grid.minor": element_line(linewidth=rel(0.5)),
        "panel.ontop": False,
        "strip.background": element_rect(fill=strip_grey, colour=NA),
        "strip.clip": "on",
        "strip.text": element_text(
            colour=strip_text_grey,
            size=rel(0.8),
            margin=margin_auto(0.8 * half_line),
        ),
        "strip.text.y": element_text(angle=-90),
        "strip.text.y.left": element_text(angle=90),
        "strip.placement": "inside",
        "strip.switch.pad.grid": unit(half_line / 2, "pt"),
        "strip.switch.pad.wrap": unit(half_line / 2, "pt"),
        "plot.background": element_rect(colour=paper),
        "plot.title": element_text(
            size=rel(1.2),
            hjust=0,
            vjust=1,
            margin=margin(b=half_line),
        ),
        "plot.title.position": "panel",
        "plot.subtitle": element_text(hjust=0, vjust=1, margin=margin(b=half_line)),
        "plot.caption": element_text(
            size=rel(0.8),
            hjust=1,
            vjust=1,
            margin=margin(t=half_line),
        ),
        "plot.caption.position": "panel",
        "plot.tag": element_text(size=rel(1.2), hjust=0.5, vjust=0.5),
        "plot.tag.position": "topleft",
    }
    return _complete("grey", elements, base_size=base_size)


def theme_bw(
    base_size: float = 11,
    base_family: str = "",
    header_family: str | None = None,
    base_line_size: float | None = None,
    base_rect_size: float | None = None,
    ink: str = "black",
    paper: str = "white",
    accent: str = "#3366FF",
) -> Theme:
    """`theme_bw()`：theme_grey 的白底变体（theme_minimal 的底）。"""
    base = theme_grey(
        base_size=base_size,
        base_family=base_family,
        header_family=header_family,
        base_line_size=base_line_size,
        base_rect_size=base_rect_size,
        ink=ink,
        paper=paper,
        accent=accent,
    )
    return _replace(
        base,
        "bw",
        {
            "panel.background": element_rect(fill=paper, colour=NA),
            "panel.border": element_rect(colour=_mix_colour(ink, paper, 0.2)),
            "panel.grid": element_line(colour=_mix_colour(ink, paper, 0.92)),
            "panel.grid.minor": element_line(linewidth=rel(0.5)),
            "strip.background": element_rect(
                fill=_mix_colour(ink, paper, 0.851),
                colour=_mix_colour(ink, paper, 0.2),
            ),
        },
    )


def theme_minimal(
    base_size: float = 11,
    base_family: str = "",
    header_family: str | None = None,
    base_line_size: float | None = None,
    base_rect_size: float | None = None,
    ink: str = "black",
    paper: str = "white",
    accent: str = "#3366FF",
) -> Theme:
    """`theme_minimal()`：白底、无边框、无刻度线。"""
    base = theme_bw(
        base_size=base_size,
        base_family=base_family,
        header_family=header_family,
        base_line_size=base_line_size,
        base_rect_size=base_rect_size,
        ink=ink,
        paper=paper,
        accent=accent,
    )
    pad = 0.45 * base_size
    return _replace(
        base,
        "minimal",
        {
            "axis.ticks": element_blank(),
            "axis.text.x.bottom": element_text(margin=margin(t=pad)),
            "axis.text.x.top": element_text(margin=margin(b=pad)),
            "axis.text.y.left": element_text(margin=margin(r=pad)),
            "axis.text.y.right": element_text(margin=margin(l=pad)),
            "legend.background": element_blank(),
            "legend.key": element_blank(),
            "panel.background": element_blank(),
            "panel.border": element_blank(),
            "strip.background": element_blank(),
            "plot.background": element_rect(fill=paper, colour=NA),
        },
    )


def theme_void(
    base_size: float = 11,
    base_family: str = "",
    header_family: str | None = None,
    base_line_size: float | None = None,
    base_rect_size: float | None = None,
    ink: str = "black",
    paper: str | None = None,
    accent: str = "#3366FF",
) -> Theme:
    """`theme_void()`：完全不画背景/网格/坐标轴，只留标题类文字。"""
    if base_line_size is None:
        base_line_size = base_size / 22
    if base_rect_size is None:
        base_rect_size = base_size / 22
    if paper is None:
        paper = _with_alpha(ink, 0)
    half_line = base_size / 2
    elements: dict[str, Any] = {
        "line": element_blank(),
        "rect": element_rect(
            fill=paper,
            colour=NA,
            linewidth=0,
            linetype=1,
            linejoin="round",
            inherit_blank=False,
        ),
        "polygon": element_blank(),
        "point": element_blank(),
        "text": element_text(
            family=base_family,
            face="plain",
            colour=ink,
            size=base_size,
            lineheight=0.9,
            hjust=0.5,
            vjust=0.5,
            angle=0,
            margin=margin(),
            debug=False,
        ),
        "title": element_text(family=header_family),
        "spacing": unit(half_line, "pt"),
        "margins": margin_auto(half_line),
        "geom": element_geom(
            ink=ink,
            paper=paper,
            accent=accent,
            linewidth=base_line_size,
            borderwidth=base_line_size,
            linetype=1,
            bordertype=1,
            family=base_family,
            fontsize=base_size,
            pointsize=(base_size / 11) * 1.5,
            pointshape=19,
        ),
        "axis.text": element_blank(),
        "axis.title": element_blank(),
        "axis.ticks.length": rel(0),
        "legend.key.size": unit(1.2, "lines"),
        "legend.position": "right",
        "legend.text": element_text(size=rel(0.8)),
        "legend.title": element_text(hjust=0),
        "legend.key.spacing": rel(1),
        "legend.margin": margin_auto(0),
        "legend.box.margin": margin_auto(0),
        "legend.box.spacing": unit(0.2, "cm"),
        "legend.ticks.length": rel(0.2),
        "legend.background": element_blank(),
        "legend.frame": element_blank(),
        "legend.box.background": element_blank(),
        "strip.clip": "on",
        # R 4.0.3 的 theme_void()：strip 文字 margin = 0、angle = 0（不是 theme_grey
        # 的 -90°）。facet-grid-ab 的右 strip 列宽因此是 stringWidth("u")≈4.89pt，
        # 而不是行高——SIL-715 #8 的对拍口径。
        "strip.text": element_text(size=rel(0.8), margin=margin_auto(0), angle=0),
        "strip.text.x": element_text(angle=0),
        "strip.text.y": element_text(angle=0),
        "strip.switch.pad.grid": rel(0.5),
        "strip.switch.pad.wrap": rel(0.5),
        "strip.background": element_blank(),
        "panel.ontop": False,
        "panel.background": element_blank(),
        "panel.border": element_blank(),
        "plot.margin": margin_auto(0),
        "plot.title": element_text(
            size=rel(1.2),
            hjust=0,
            vjust=1,
            margin=margin(t=half_line),
        ),
        "plot.title.position": "panel",
        "plot.subtitle": element_text(hjust=0, vjust=1, margin=margin(t=half_line)),
        "plot.caption": element_text(
            size=rel(0.8),
            hjust=1,
            vjust=1,
            margin=margin(t=half_line),
        ),
        "plot.caption.position": "panel",
        "plot.tag": element_text(size=rel(1.2), hjust=0.5, vjust=0.5),
        "plot.tag.position": "topleft",
        "plot.background": element_rect(),
    }
    return _complete("void", elements, base_size=base_size)


# ---------------------------------------------------------------------------
# 其余完整主题（4.0.3 的 theme-defaults.R；全部是 `%+replace%` 的派生）
# ---------------------------------------------------------------------------


def theme_linedraw(
    base_size: float = 11,
    base_family: str = "",
    header_family: str | None = None,
    base_line_size: float | None = None,
    base_rect_size: float | None = None,
    ink: str = "black",
    paper: str = "white",
    accent: str = "#3366FF",
) -> Theme:
    """`theme_linedraw()`：`theme_bw()` 的纯黑线条变体（网格线是实黑）。"""
    base = theme_bw(
        base_size=base_size,
        base_family=base_family,
        header_family=header_family,
        base_line_size=base_line_size,
        base_rect_size=base_rect_size,
        ink=ink,
        paper=paper,
        accent=accent,
    )
    half_line = base_size / 2
    return _replace(
        base,
        "linedraw",
        {
            "axis.text": element_text(colour=ink, size=rel(0.8)),
            "axis.ticks": element_line(colour=ink, linewidth=rel(0.5)),
            "panel.border": element_rect(colour=ink, linewidth=rel(1)),
            "panel.grid": element_line(colour=ink),
            "panel.grid.major": element_line(linewidth=rel(0.1)),
            "panel.grid.minor": element_line(linewidth=rel(0.05)),
            "strip.background": element_rect(fill=ink),
            "strip.text": element_text(
                colour=paper,
                size=rel(0.8),
                margin=margin_auto(0.8 * half_line),
            ),
        },
    )


def theme_light(
    base_size: float = 11,
    base_family: str = "",
    header_family: str | None = None,
    base_line_size: float | None = None,
    base_rect_size: float | None = None,
    ink: str = "black",
    paper: str = "white",
    accent: str = "#3366FF",
) -> Theme:
    """`theme_light()`：白底 + 浅灰网格/边框。"""
    base = theme_grey(
        base_size=base_size,
        base_family=base_family,
        header_family=header_family,
        base_line_size=base_line_size,
        base_rect_size=base_rect_size,
        ink=ink,
        paper=paper,
        accent=accent,
    )
    half_line = base_size / 2
    return _replace(
        base,
        "light",
        {
            "panel.background": element_rect(fill=paper, colour=NA),
            "panel.border": element_rect(colour=_mix_colour(ink, paper, 0.702), linewidth=rel(1)),
            "panel.grid": element_line(colour=_mix_colour(ink, paper, 0.871)),
            "panel.grid.major": element_line(linewidth=rel(0.5)),
            "panel.grid.minor": element_line(linewidth=rel(0.25)),
            "axis.ticks": element_line(colour=_mix_colour(ink, paper, 0.702), linewidth=rel(0.5)),
            "strip.background": element_rect(fill=_mix_colour(ink, paper, 0.702), colour=NA),
            "strip.text": element_text(
                colour=paper,
                size=rel(0.8),
                margin=margin_auto(0.8 * half_line),
            ),
        },
    )


def theme_dark(
    base_size: float = 11,
    base_family: str = "",
    header_family: str | None = None,
    base_line_size: float | None = None,
    base_rect_size: float | None = None,
    ink: str = "black",
    paper: str = "white",
    accent: str = "#3366FF",
) -> Theme:
    """`theme_dark()`：灰面板 + 深灰网格（深色背景上的点图）。"""
    base = theme_grey(
        base_size=base_size,
        base_family=base_family,
        header_family=header_family,
        base_line_size=base_line_size,
        base_rect_size=base_rect_size,
        ink=ink,
        paper=paper,
        accent=accent,
    )
    half_line = base_size / 2
    return _replace(
        base,
        "dark",
        {
            "panel.background": element_rect(fill=_mix_colour(ink, paper, 0.499), colour=NA),
            "panel.grid": element_line(colour=_mix_colour(ink, paper, 0.42)),
            "panel.grid.major": element_line(linewidth=rel(0.5)),
            "panel.grid.minor": element_line(linewidth=rel(0.25)),
            "axis.ticks": element_line(colour=_mix_colour(ink, paper, 0.2), linewidth=rel(0.5)),
            "strip.background": element_rect(fill=_mix_colour(ink, paper, 0.15), colour=NA),
            "strip.text": element_text(
                colour=_mix_colour(ink, paper, 0.899),
                size=rel(0.8),
                margin=margin_auto(0.8 * half_line),
            ),
        },
    )


def theme_classic(
    base_size: float = 11,
    base_family: str = "",
    header_family: str | None = None,
    base_line_size: float | None = None,
    base_rect_size: float | None = None,
    ink: str = "black",
    paper: str = "white",
    accent: str = "#3366FF",
) -> Theme:
    """`theme_classic()`：只有轴线、没有网格与边框的经典风格。"""
    base = theme_bw(
        base_size=base_size,
        base_family=base_family,
        header_family=header_family,
        base_line_size=base_line_size,
        base_rect_size=base_rect_size,
        ink=ink,
        paper=paper,
        accent=accent,
    )
    return _replace(
        base,
        "classic",
        {
            "panel.border": element_blank(),
            "panel.grid": element_blank(),
            "axis.text": element_text(size=rel(0.8)),
            "axis.line": element_line(lineend="square"),
            "axis.ticks": element_line(),
            "strip.background": element_rect(linewidth=rel(2)),
        },
    )


def theme_test(
    base_size: float = 11,
    base_family: str = "",
    header_family: str | None = None,
    base_line_size: float | None = None,
    base_rect_size: float | None = None,
    ink: str = "black",
    paper: str = "white",
    accent: str = "#3366FF",
) -> Theme:
    """`theme_test()`：白底 + 面板边框、无网格（上游是独立定义，不派生）。"""
    if base_line_size is None:
        base_line_size = base_size / 22
    if base_rect_size is None:
        base_rect_size = base_size / 22
    half_line = base_size / 2
    elements: dict[str, Any] = {
        "line": element_line(
            colour=ink,
            linewidth=base_line_size,
            linetype=1,
            lineend="butt",
            linejoin="round",
        ),
        "rect": element_rect(
            fill=paper,
            colour=ink,
            linewidth=base_rect_size,
            linetype=1,
            linejoin="round",
        ),
        "text": element_text(
            family=base_family,
            face="plain",
            colour=ink,
            size=base_size,
            lineheight=0.9,
            hjust=0.5,
            vjust=0.5,
            angle=0,
            margin=margin(),
            debug=False,
        ),
        "point": element_point(
            colour=ink,
            shape=19,
            fill=paper,
            size=(base_size / 11) * 1.5,
            stroke=base_line_size,
        ),
        "polygon": element_polygon(
            fill=paper,
            colour=ink,
            linewidth=base_rect_size,
            linetype=1,
            linejoin="round",
        ),
        "title": element_text(family=header_family),
        "spacing": unit(half_line, "pt"),
        "margins": margin_auto(half_line),
        "geom": element_geom(
            ink=ink,
            paper=paper,
            accent=accent,
            linewidth=base_line_size,
            borderwidth=base_line_size,
            family=base_family,
            fontsize=base_size,
            linetype=1,
            pointsize=(base_size / 11) * 1.5,
            pointshape=19,
        ),
        "axis.line": element_blank(),
        "axis.text": element_text(size=rel(0.8), colour=_mix_colour(ink, paper, 0.302)),
        "axis.text.x": element_text(margin=margin(t=0.8 * half_line / 2), vjust=1),
        "axis.text.x.top": element_text(margin=margin(b=0.8 * half_line / 2), vjust=0),
        "axis.text.y": element_text(margin=margin(r=0.8 * half_line / 2), hjust=1),
        "axis.text.y.right": element_text(margin=margin(l=0.8 * half_line / 2), hjust=0),
        "axis.ticks": element_line(colour=_mix_colour(ink, paper, 0.2)),
        "axis.ticks.length": rel(0.5),
        "axis.minor.ticks.length": rel(0.75),
        "axis.title.x": element_text(margin=margin(t=half_line / 2), vjust=1),
        "axis.title.x.top": element_text(margin=margin(b=half_line / 2), vjust=0),
        "axis.title.y": element_text(angle=90, margin=margin(r=half_line / 2), vjust=1),
        "axis.title.y.right": element_text(angle=-90, margin=margin(l=half_line / 2), vjust=1),
        "legend.background": element_rect(colour=NA),
        "legend.spacing": rel(2),
        "legend.margin": margin_auto(0, unit="cm"),
        "legend.key.size": unit(1.2, "lines"),
        "legend.text": element_text(size=rel(0.8)),
        "legend.title": element_text(hjust=0),
        "legend.ticks.length": rel(0.2),
        "legend.position": "right",
        "legend.justification": "center",
        "legend.box.margin": margin_auto(0, unit="cm"),
        "legend.box.background": element_blank(),
        "legend.box.spacing": rel(2),
        "panel.background": element_rect(fill=paper, colour=NA),
        "panel.border": element_rect(colour=_mix_colour(ink, paper, 0.2)),
        "panel.grid.major": element_blank(),
        "panel.grid.minor": element_blank(),
        "panel.ontop": False,
        "strip.background": element_rect(
            fill=_mix_colour(ink, paper, 0.85), colour=_mix_colour(ink, paper, 0.2)
        ),
        "strip.clip": "on",
        "strip.text": element_text(
            colour=_mix_colour(ink, paper, 0.1),
            size=rel(0.8),
            margin=margin_auto(0.8 * half_line),
        ),
        "strip.text.y": element_text(angle=-90),
        "strip.text.y.left": element_text(angle=90),
        "strip.placement": "inside",
        "strip.switch.pad.grid": rel(0.5),
        "strip.switch.pad.wrap": rel(0.5),
        "plot.background": element_rect(colour=paper),
        "plot.title": element_text(
            size=rel(1.2),
            hjust=0,
            vjust=1,
            margin=margin(b=half_line),
        ),
        "plot.title.position": "panel",
        "plot.subtitle": element_text(hjust=0, vjust=1, margin=margin(b=half_line)),
        "plot.caption": element_text(
            size=rel(0.8),
            hjust=1,
            vjust=1,
            margin=margin(t=half_line),
        ),
        "plot.caption.position": "panel",
        "plot.tag": element_text(size=rel(1.2), hjust=0.5, vjust=0.5),
        "plot.tag.position": "topleft",
    }
    return _complete("test", elements, base_size=base_size)


#: `theme_gray()` 是 `theme_grey()` 的美式拼写别名（上游两者同一个函数体）。
theme_gray = theme_grey


# ---------------------------------------------------------------------------
# 全局默认主题：theme_set / theme_get / theme_update / theme_replace
# ---------------------------------------------------------------------------

_theme_default: Theme | None = None


def theme_get() -> Theme:
    """当前全局默认主题（`ggplot()` 的默认主题、局部主题的合并底）。

    初值是 `theme_grey()`；`theme_set()` 之后整份换掉。
    """
    global _theme_default
    if _theme_default is None:
        _theme_default = theme_grey()
    return _theme_default


def theme_set(new: Any = _UNSET) -> Theme:
    """设置全局默认主题，返回旧值（对应 R 的不可见返回值）。

    上游 4.0.3 是 `set_theme(new = NULL)`，函数体第一行 `new <- new %||%
    ggplot_global$theme_default`：**无参（或传 `None`）时重置为内置默认
    `theme_grey()`**，不是「读当前值」（读当前值用 `theme_get()`）。

    - 无参 / `None` → 重置为 `theme_grey()`，返回旧主题；
    - 传入的主题必须是完整主题（`complete=True`），否则报 `ThemeError`
      （对应上游的 "must be called with a complete theme"）。
    """
    global _theme_default
    old = theme_get()
    if new is _UNSET or new is None:
        _theme_default = theme_grey()
        return old
    if not isinstance(new, Theme):
        raise TypeError(f"theme_set() 需要 Theme，得到 {type(new).__name__}")
    if not new.complete:
        raise ThemeError("theme_set() 只能接受完整主题（例如 theme_grey() / theme_bw()）")
    _theme_default = new
    return old


def theme_update(**elements: Any) -> Theme:
    """在当前默认主题上按元素合并（`%+%` 语义），返回旧值。"""
    old = theme_get()
    theme_set(merge_theme(old, theme(**elements)))
    return old


def theme_replace(**elements: Any) -> Theme:
    """在当前默认主题上按元素整份替换（`%+replace%` 语义），返回旧值。

    上游是 `set_theme(get_theme() %+replace% theme(...))`：`theme(...)` 不带
    `complete`，换进来的元素保留 `inherit.blank=FALSE`，只有 base 里的旧元素
    继续带 `inherit.blank=TRUE`。
    """
    old = theme_get()
    theme_set(_replace(old, old.name, elements, complete=False))
    return old


# ---------------------------------------------------------------------------
# 4.0 的 theme_sub_*（按前缀 + 后缀拼元素名，等价于带前缀的 theme()）
# ---------------------------------------------------------------------------


def _subtheme(prefix: str, suffix: str, values: Mapping[str, Any]) -> Theme:
    """把 `title=…` 这类简写拼成 `axis.title.x` 再交给 `theme()`。

    `_UNSET` 表示「没给这个参数」，`None` 表示「删除这个元素」（与 R 里
    `axis.text = NULL` 一致）。未知元素名仍由 `theme()` 报错。
    """
    elements: dict[str, Any] = {}
    for name, value in values.items():
        if value is _UNSET:
            continue
        elements[f"{prefix}{name.replace('_', '.')}{suffix}"] = value
    return theme(**elements)


def theme_sub_axis(
    title: Any = _UNSET,
    text: Any = _UNSET,
    ticks: Any = _UNSET,
    ticks_length: Any = _UNSET,
    line: Any = _UNSET,
    minor_ticks_length: Any = _UNSET,
) -> Theme:
    """`theme_sub_axis()`：`axis.title` / `axis.text` / … 的简写。"""
    return _subtheme(
        "axis.",
        "",
        {
            "title": title,
            "text": text,
            "ticks": ticks,
            "ticks_length": ticks_length,
            "line": line,
            "minor_ticks_length": minor_ticks_length,
        },
    )


def _axis_subtheme(suffix: str, minor_ticks: Any, values: Mapping[str, Any]) -> Theme:
    payload = dict(values)
    payload["minor_ticks"] = minor_ticks
    return _subtheme("axis.", suffix, payload)


def theme_sub_axis_x(
    title: Any = _UNSET,
    text: Any = _UNSET,
    ticks: Any = _UNSET,
    ticks_length: Any = _UNSET,
    line: Any = _UNSET,
    minor_ticks_length: Any = _UNSET,
) -> Theme:
    """`theme_sub_axis_x()`：x 轴的六个元素（`axis.*.x`）。"""
    return _subtheme(
        "axis.",
        ".x",
        {
            "title": title,
            "text": text,
            "ticks": ticks,
            "ticks_length": ticks_length,
            "line": line,
            "minor_ticks_length": minor_ticks_length,
        },
    )


def theme_sub_axis_y(
    title: Any = _UNSET,
    text: Any = _UNSET,
    ticks: Any = _UNSET,
    ticks_length: Any = _UNSET,
    line: Any = _UNSET,
    minor_ticks_length: Any = _UNSET,
) -> Theme:
    """`theme_sub_axis_y()`：y 轴的六个元素（`axis.*.y`）。"""
    return _subtheme(
        "axis.",
        ".y",
        {
            "title": title,
            "text": text,
            "ticks": ticks,
            "ticks_length": ticks_length,
            "line": line,
            "minor_ticks_length": minor_ticks_length,
        },
    )


def theme_sub_axis_top(
    title: Any = _UNSET,
    text: Any = _UNSET,
    ticks: Any = _UNSET,
    ticks_length: Any = _UNSET,
    line: Any = _UNSET,
    minor_ticks: Any = _UNSET,
    minor_ticks_length: Any = _UNSET,
) -> Theme:
    """`theme_sub_axis_top()`：顶部 x 轴（`axis.*.x.top`）。"""
    return _axis_subtheme(
        ".x.top",
        minor_ticks,
        {
            "title": title,
            "text": text,
            "ticks": ticks,
            "ticks_length": ticks_length,
            "line": line,
            "minor_ticks_length": minor_ticks_length,
        },
    )


def theme_sub_axis_bottom(
    title: Any = _UNSET,
    text: Any = _UNSET,
    ticks: Any = _UNSET,
    ticks_length: Any = _UNSET,
    line: Any = _UNSET,
    minor_ticks: Any = _UNSET,
    minor_ticks_length: Any = _UNSET,
) -> Theme:
    """`theme_sub_axis_bottom()`：底部 x 轴（`axis.*.x.bottom`）。"""
    return _axis_subtheme(
        ".x.bottom",
        minor_ticks,
        {
            "title": title,
            "text": text,
            "ticks": ticks,
            "ticks_length": ticks_length,
            "line": line,
            "minor_ticks_length": minor_ticks_length,
        },
    )


def theme_sub_axis_left(
    title: Any = _UNSET,
    text: Any = _UNSET,
    ticks: Any = _UNSET,
    ticks_length: Any = _UNSET,
    line: Any = _UNSET,
    minor_ticks: Any = _UNSET,
    minor_ticks_length: Any = _UNSET,
) -> Theme:
    """`theme_sub_axis_left()`：左侧 y 轴（`axis.*.y.left`）。"""
    return _axis_subtheme(
        ".y.left",
        minor_ticks,
        {
            "title": title,
            "text": text,
            "ticks": ticks,
            "ticks_length": ticks_length,
            "line": line,
            "minor_ticks_length": minor_ticks_length,
        },
    )


def theme_sub_axis_right(
    title: Any = _UNSET,
    text: Any = _UNSET,
    ticks: Any = _UNSET,
    ticks_length: Any = _UNSET,
    line: Any = _UNSET,
    minor_ticks: Any = _UNSET,
    minor_ticks_length: Any = _UNSET,
) -> Theme:
    """`theme_sub_axis_right()`：右侧 y 轴（`axis.*.y.right`）。"""
    return _axis_subtheme(
        ".y.right",
        minor_ticks,
        {
            "title": title,
            "text": text,
            "ticks": ticks,
            "ticks_length": ticks_length,
            "line": line,
            "minor_ticks_length": minor_ticks_length,
        },
    )


def theme_sub_legend(
    text: Any = _UNSET,
    text_position: Any = _UNSET,
    title: Any = _UNSET,
    title_position: Any = _UNSET,
    background: Any = _UNSET,
    frame: Any = _UNSET,
    ticks: Any = _UNSET,
    ticks_length: Any = _UNSET,
    axis_line: Any = _UNSET,
    spacing: Any = _UNSET,
    spacing_x: Any = _UNSET,
    spacing_y: Any = _UNSET,
    margin: Any = _UNSET,
    key: Any = _UNSET,
    key_size: Any = _UNSET,
    key_height: Any = _UNSET,
    key_width: Any = _UNSET,
    key_spacing: Any = _UNSET,
    key_spacing_x: Any = _UNSET,
    key_spacing_y: Any = _UNSET,
    key_justification: Any = _UNSET,
    byrow: Any = _UNSET,
    position: Any = _UNSET,
    direction: Any = _UNSET,
    location: Any = _UNSET,
    position_inside: Any = _UNSET,
    justification: Any = _UNSET,
    justification_top: Any = _UNSET,
    justification_bottom: Any = _UNSET,
    justification_left: Any = _UNSET,
    justification_right: Any = _UNSET,
    justification_inside: Any = _UNSET,
    box: Any = _UNSET,
    box_just: Any = _UNSET,
    box_margin: Any = _UNSET,
    box_background: Any = _UNSET,
    box_spacing: Any = _UNSET,
) -> Theme:
    """`theme_sub_legend()`：所有 `legend.*` 元素的简写。"""
    return _subtheme(
        "legend.",
        "",
        {
            "text": text,
            "text_position": text_position,
            "title": title,
            "title_position": title_position,
            "background": background,
            "frame": frame,
            "ticks": ticks,
            "ticks_length": ticks_length,
            "axis_line": axis_line,
            "spacing": spacing,
            "spacing_x": spacing_x,
            "spacing_y": spacing_y,
            "margin": margin,
            "key": key,
            "key_size": key_size,
            "key_height": key_height,
            "key_width": key_width,
            "key_spacing": key_spacing,
            "key_spacing_x": key_spacing_x,
            "key_spacing_y": key_spacing_y,
            "key_justification": key_justification,
            "byrow": byrow,
            "position": position,
            "direction": direction,
            "location": location,
            "position_inside": position_inside,
            "justification": justification,
            "justification_top": justification_top,
            "justification_bottom": justification_bottom,
            "justification_left": justification_left,
            "justification_right": justification_right,
            "justification_inside": justification_inside,
            "box": box,
            "box_just": box_just,
            "box_margin": box_margin,
            "box_background": box_background,
            "box_spacing": box_spacing,
        },
    )


def theme_sub_panel(
    background: Any = _UNSET,
    border: Any = _UNSET,
    widths: Any = _UNSET,
    heights: Any = _UNSET,
    spacing: Any = _UNSET,
    spacing_x: Any = _UNSET,
    spacing_y: Any = _UNSET,
    grid: Any = _UNSET,
    grid_major: Any = _UNSET,
    grid_minor: Any = _UNSET,
    grid_major_x: Any = _UNSET,
    grid_major_y: Any = _UNSET,
    grid_minor_x: Any = _UNSET,
    grid_minor_y: Any = _UNSET,
    ontop: Any = _UNSET,
) -> Theme:
    """`theme_sub_panel()`：所有 `panel.*` 元素的简写。"""
    return _subtheme(
        "panel.",
        "",
        {
            "background": background,
            "border": border,
            "widths": widths,
            "heights": heights,
            "spacing": spacing,
            "spacing_x": spacing_x,
            "spacing_y": spacing_y,
            "grid": grid,
            "grid_major": grid_major,
            "grid_minor": grid_minor,
            "grid_major_x": grid_major_x,
            "grid_major_y": grid_major_y,
            "grid_minor_x": grid_minor_x,
            "grid_minor_y": grid_minor_y,
            "ontop": ontop,
        },
    )


def theme_sub_plot(
    background: Any = _UNSET,
    title: Any = _UNSET,
    title_position: Any = _UNSET,
    subtitle: Any = _UNSET,
    caption: Any = _UNSET,
    caption_position: Any = _UNSET,
    tag: Any = _UNSET,
    tag_position: Any = _UNSET,
    tag_location: Any = _UNSET,
    margin: Any = _UNSET,
) -> Theme:
    """`theme_sub_plot()`：所有 `plot.*` 元素的简写。"""
    return _subtheme(
        "plot.",
        "",
        {
            "background": background,
            "title": title,
            "title_position": title_position,
            "subtitle": subtitle,
            "caption": caption,
            "caption_position": caption_position,
            "tag": tag,
            "tag_position": tag_position,
            "tag_location": tag_location,
            "margin": margin,
        },
    )


def theme_sub_strip(
    background: Any = _UNSET,
    background_x: Any = _UNSET,
    background_y: Any = _UNSET,
    clip: Any = _UNSET,
    placement: Any = _UNSET,
    text: Any = _UNSET,
    text_x: Any = _UNSET,
    text_x_bottom: Any = _UNSET,
    text_x_top: Any = _UNSET,
    text_y: Any = _UNSET,
    text_y_left: Any = _UNSET,
    text_y_right: Any = _UNSET,
    switch_pad_grid: Any = _UNSET,
    switch_pad_wrap: Any = _UNSET,
) -> Theme:
    """`theme_sub_strip()`：所有 `strip.*` 元素的简写。"""
    return _subtheme(
        "strip.",
        "",
        {
            "background": background,
            "background_x": background_x,
            "background_y": background_y,
            "clip": clip,
            "placement": placement,
            "text": text,
            "text_x": text_x,
            "text_x_bottom": text_x_bottom,
            "text_x_top": text_x_top,
            "text_y": text_y,
            "text_y_left": text_y_left,
            "text_y_right": text_y_right,
            "switch_pad_grid": switch_pad_grid,
            "switch_pad_wrap": switch_pad_wrap,
        },
    )

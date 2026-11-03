"""主轴（M1-11）：刻度线 + 刻度标签 + 轴标题。

口径照 ggplot2 4.0.3 的 `R/guide-axis.R` + `ggplot_gtable()` 的 axis 行列：

- 断点 / 标签来自**该面板自己的**标度（`scale.breaks()` / `scale.labels()`）；
  连续标度的断点已经在变换后的空间（`scale_x_log10()` 给的是 log10 值），
  离散标度的断点是水平名，位置按 1..n 换算——两条路径最后都落到面板 npc；
- 尺寸（刻度长度、文字行高、文字与刻度的间距、轴标题间距）全部取
  `resolve_theme()` 的解析值，不硬编码 cm / pt；
- 轴文字的行高用 R `stringHeight` + descent 的 0.955em 口径
  （`TEXT_LINE_EM`，与 `ggcore.facet` 的 strip 同一常量），宽度走
  `Metrics.strwidth()`；没有度量时按 0.6em/字符估（`FALLBACK_CHAR_EM`）；
- 只做主轴：`sec_axis()` 明确报错（见 docs/notes/guide.md「未实现」）。

坐标约定：面板矩形是 cm、**y 向上**（与 grid 的 `subRegion()` 一致），所有
轴 grob 都以页面 cm 坐标直接落位，不引入新的视口层级。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from ggcore.grobs import segments_grob, text_grob
from ggcore.gtable import CellBox
from ggcore.theme import (
    ElementBlank,
    ElementLine,
    ElementText,
    Margin,
    ResolvedTheme,
)
from ggcore.units import UnitContext, convert_height, convert_width
from ggcore.viewport import NA, gpar

__all__ = [
    "FALLBACK_CHAR_EM",
    "TEXT_LINE_EM",
    "AxisError",
    "AxisTicks",
    "axis_extent",
    "axis_grobs",
    "axis_ticks",
    "axis_title_extent",
    "axis_title_grob",
    "font_int",
    "margin_sides_cm",
    "paint",
    "text_line_cm",
    "text_width_cm",
    "tick_length_cm",
    "tick_paint",
]

#: R 的 `stringHeight()` + `font_descent()`：R 4.5.3 + svglite 在 8.8 / 11 / 20pt 上
#: 量出来都是 **0.894em**（Arimo 的 cap height 0.691em + descent 0.203em）。旧值
#: 0.955em 是 pdf 设备（Helvetica）量出来的，用它排 4×3 的 svglite 参考图时
#: 轴带高出 1.2pt，面板底边整条错位——`pixi run diff theme-grey-basic` 的
#: 网格线因此偏 1px。见 docs/notes/guide.md「轴」。
TEXT_LINE_EM = 0.8945

#: 布局列宽里「拉丁文字」的度量字面。R 的缺省 sans 是 Helvetica 口径
#: （数字 0.556em，`1.5` @8.8pt 量 12.20pt）；受管字体栈的主字面 Noto Sans CJK SC
#: 把拉丁数字排成 0.50em（同一串 11.20pt），照样排下去 y 轴标签列会窄 1pt、
#: 面板左边界整列偏 1px。这里只**量宽度**（列宽 / 图例标签盒），不换绘制字面：
#: IR 的 `text.width` 仍由绘制端按自己的字面量（`docs/notes/guide.md`
#: 「与 R 的实测差」记着这条差）。
LAYOUT_LATIN_FONT = "Noto Sans"

#: 没有 `Metrics` 时每字符的宽度（em）。只在布局估算里用，渲染宽度由 IR 文本节点
#: 自带的 `text.width` 决定；有度量时一律走 `Metrics.strwidth()`。
FALLBACK_CHAR_EM = 0.6

_CM_PER_INCH = 2.54
_POINTS_PER_INCH = 72.0


class AxisError(ValueError):
    """轴参数无法表达（secondary axis / 旋转标签等尚未实现的东西）。"""


@dataclass(frozen=True, slots=True)
class AxisTicks:
    """一条主轴的刻度：`side` 是 `"bottom"` / `"left"`。"""

    side: str
    positions: tuple[float, ...]
    labels: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.side not in ("bottom", "left"):
            raise AxisError(f"side 只能是 'bottom' / 'left'，收到 {self.side!r}")
        if len(self.positions) != len(self.labels):
            raise AxisError(
                f"刻度位置 {len(self.positions)} 个，标签 {len(self.labels)} 个（必须等长）"
            )

    @property
    def empty(self) -> bool:
        return not self.positions


# ---------------------------------------------------------------------------
# 文字度量（布局口径）
# ---------------------------------------------------------------------------


def text_line_cm(size_pt: float) -> float:
    """一行文字的占高（cm）：`size * 0.955em`（R `stringHeight` 口径）。"""
    return float(size_pt) * TEXT_LINE_EM * _CM_PER_INCH / _POINTS_PER_INCH


def _lines(text: str) -> tuple[str, ...]:
    return tuple(str(text).split("\n"))


def text_width_cm(
    text: str,
    size_pt: float,
    metrics: Any = None,
    family: str = "",
) -> float:
    """一段文字的最大行宽（cm）；多行取最宽的一行（grid `stringWidth` 同）。"""
    lines = _lines(text)
    if not lines:
        return 0.0
    if metrics is not None:
        widths = [
            float(
                metrics.strwidth(
                    line,
                    fontsize=float(size_pt),
                    cex=1.0,
                    font=str(family or LAYOUT_LATIN_FONT),
                )
            )
            for line in lines
        ]
        return max(widths) * _CM_PER_INCH
    longest = max(len(line) for line in lines)
    return FALLBACK_CHAR_EM * float(size_pt) * longest * _CM_PER_INCH / _POINTS_PER_INCH


def margin_sides_cm(
    margin: Margin | None, ctx: UnitContext | None = None
) -> tuple[float, float, float, float]:
    """`Margin` → `(上, 右, 下, 左)`（cm；未设置的边是 0）。"""
    context = ctx or UnitContext()
    if margin is None:
        return (0.0, 0.0, 0.0, 0.0)
    out: list[float] = []
    for value, axis in zip(margin.as_tuple(), ("height", "width", "height", "width"), strict=True):
        if value is None:
            out.append(0.0)
            continue
        convert = convert_height if axis == "height" else convert_width
        out.append(float(np.asarray(convert(value, "cm", ctx=context)).sum()))
    return (out[0], out[1], out[2], out[3])


def paint(value: Any) -> str | None:
    """主题颜色 → 可绘制的颜色；`NA` / `transparent` / 缺失 → None。"""
    if value is None or value is NA or not isinstance(value, str):
        return None
    text = value.strip()
    if text.lower() == "transparent":
        return None
    if text.startswith("#") and len(text) == 9 and text[7:9].lower() == "00":
        return None
    return value


def font_int(face: Any) -> int:
    """`element_text(face=)` → gpar 的 `font`（1/2/3/4）。"""
    return {"bold": 2, "italic": 3, "oblique": 3, "bold.italic": 4, "bolditalic": 4}.get(
        str(face or "plain").lower(), 1
    )


def _mm_to_pt(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value) * _POINTS_PER_INCH / 25.4
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# 断点 → 面板 npc
# ---------------------------------------------------------------------------


def _axis_range(params: Any, side: str) -> tuple[float, float]:
    return params.x_range if side == "bottom" else params.y_range


def axis_ticks(scale: Any, params: Any, side: str) -> AxisTicks:
    """一个面板的刻度位置（npc 0..1）+ 标签文本。

    `scale` 是该面板自己的标度（`PanelScaleSet.scale("x")`）；`params` 是
    :class:`ggcore.coord.PanelParams`。标度缺失 / 断点为空时返回空刻度。
    """
    if side not in ("bottom", "left"):
        raise AxisError(f"side 只能是 'bottom' / 'left'，收到 {side!r}")
    if scale is None:
        return AxisTicks(side, (), ())
    low, high = _axis_range(params, side)
    span = float(high) - float(low)
    if span == 0:
        raise AxisError(f"{side} 轴的面板范围跨度为 0（{low!r} == {high!r}）")
    breaks = tuple(scale.breaks())
    labels = tuple(scale.labels())
    if len(breaks) != len(labels):
        raise AxisError(
            f"标度 {scale.aesthetic!r} 的 breaks（{len(breaks)}）与 labels"
            f"（{len(labels)}）长度不一致"
        )
    positions: list[float] = []
    texts: list[str] = []
    discrete = bool(getattr(scale, "discrete", False))
    levels = tuple(scale.levels) if discrete else ()
    for value, label in zip(breaks, labels, strict=True):
        if value is None or label is None:
            continue
        text = str(label)
        if not text:
            continue
        if discrete:
            try:
                code = levels.index(str(value)) + 1
            except ValueError:
                continue
            position = (float(code) - float(low)) / span
        else:
            number = float(value)
            if not math.isfinite(number):
                continue
            position = (number - float(low)) / span
        if not math.isfinite(position):
            continue
        positions.append(position)
        texts.append(text)
    return AxisTicks(side, tuple(positions), tuple(texts))


# ---------------------------------------------------------------------------
# 尺寸
# ---------------------------------------------------------------------------


def _tick_element(theme: ResolvedTheme, side: str) -> Any:
    return theme.get("axis.ticks.x" if side == "bottom" else "axis.ticks.y")


def _text_element(theme: ResolvedTheme, side: str) -> Any:
    return theme.get("axis.text.x" if side == "bottom" else "axis.text.y")


def _title_element(theme: ResolvedTheme, side: str) -> Any:
    return theme.get("axis.title.x" if side == "bottom" else "axis.title.y")


def tick_paint(theme: ResolvedTheme, side: str) -> tuple[str, float, int] | None:
    """刻度线的 `(colour, lwd, lty)`；`element_blank()` 或 NA 给 None。"""
    element = _tick_element(theme, side)
    if not isinstance(element, ElementLine):
        return None
    colour = paint(element.colour)
    if colour is None:
        return None
    return (colour, _mm_to_pt(element.linewidth), int(element.linetype or 1))


def tick_length_cm(theme: ResolvedTheme, side: str) -> float:
    """`axis.ticks.length` → cm（轴带里**始终**给刻度留这段位置）。

    R 的 `gtable` 在 `axis.ticks = element_blank()`（`theme_minimal()`）时照样
    把 `axis.ticks.length` 算进 axis-b / axis-l：`theme_grey()` 与
    `theme_minimal()` 的 `axis-b` 都是 12.87pt（R 4.5.3 + svglite 实测）。
    刻度本身画不画由 :func:`tick_paint` 决定，与这里的占位无关。
    """
    value = theme.get("axis.ticks.length.x" if side == "bottom" else "axis.ticks.length.y")
    if value is None:
        return 0.0
    context = UnitContext()
    convert = convert_height if side == "bottom" else convert_width
    return float(np.asarray(convert(value, "cm", ctx=context)).sum())


def _text_extent_cm(
    element: ElementText,
    side: str,
    labels: tuple[str, ...],
    metrics: Any,
) -> float:
    size = float(element.size or 0.0)
    family = element.family or ""
    mt, mr, mb, ml = margin_sides_cm(element.margin)
    if side == "bottom":
        return text_line_cm(size) + mt + mb
    if not labels:
        return 0.0
    widest = max(text_width_cm(label, size, metrics, family) for label in labels)
    return widest + ml + mr


def axis_extent(
    theme: ResolvedTheme,
    ticks: AxisTicks,
    *,
    metrics: Any = None,
) -> float:
    """一条主轴从面板边缘向外的总占位（cm）：刻度 + 刻度标签（含 margin）。

    轴文字是 `element_blank()`（`theme_void()`）时整条轴为 0——刻度也跟着消失，
    与 R 的 `axis-l` 列宽一致。
    """
    side = ticks.side
    text = _text_element(theme, side)
    if isinstance(text, ElementBlank) or not isinstance(text, ElementText):
        return 0.0
    tick = tick_length_cm(theme, side)
    if not ticks.labels:
        return tick
    return tick + _text_extent_cm(text, side, ticks.labels, metrics)


def axis_title_extent(
    theme: ResolvedTheme,
    side: str,
    title: str | None,
    *,
    metrics: Any = None,
) -> float:
    """轴标题的外向占位（cm）：标题行高（或旋转后的宽）+ margin。"""
    element = _title_element(theme, side)
    if title is None or not title or isinstance(element, ElementBlank):
        return 0.0
    if not isinstance(element, ElementText):
        return 0.0
    size = float(element.size or 0.0)
    mt, mr, mb, ml = margin_sides_cm(element.margin)
    if side == "bottom":
        return text_line_cm(size) + mt + mb
    # y 轴标题旋转 90°：外向尺寸是行高（不是文字宽度）。
    return text_line_cm(size) + ml + mr


# ---------------------------------------------------------------------------
# 绘制
# ---------------------------------------------------------------------------


def _text_gp(element: ElementText) -> dict[str, Any]:
    return {
        "col": paint(element.colour) or "black",
        "fontsize": float(element.size or 11.0),
        "fontfamily": element.family or "",
        "font": font_int(element.face),
        "lineheight": float(element.lineheight or 1.2),
    }


def _angle(element: ElementText, what: str) -> float:
    angle = float(element.angle or 0.0)
    if angle % 360.0 != 0.0:
        raise AxisError(
            f"{what} 的 angle={angle:g} 尚未实现（M1-11 只画水平标签；"
            "旋转标签需要与 R rotate_just() 对齐的锚点计算，见 docs/notes/guide.md）"
        )
    return angle


def axis_grobs(
    theme: ResolvedTheme,
    ticks: AxisTicks,
    box: CellBox,
    *,
    metrics: Any = None,
    name: str = "axis",
) -> list[Any]:
    """一条主轴的刻度线 + 刻度标签（页面 cm 坐标，y 向上）。"""
    side = ticks.side
    text = _text_element(theme, side)
    if isinstance(text, ElementBlank) or not isinstance(text, ElementText):
        return []
    _angle(text, f"axis.text.{'x' if side == 'bottom' else 'y'}")
    tick = tick_length_cm(theme, side)
    paint_tick = tick_paint(theme, side)
    grobs: list[Any] = []
    if paint_tick is not None and ticks.positions and tick > 0:
        colour, lwd, lty = paint_tick
        if side == "bottom":
            xs = [box.x_cm + position * box.width_cm for position in ticks.positions]
            grobs.append(
                segments_grob(
                    xs,
                    [box.y_cm] * len(xs),
                    xs,
                    [box.y_cm - tick] * len(xs),
                    default_units="cm",
                    gp=gpar(col=colour, lwd=lwd, lty=lty),
                    name=f"{name}.ticks",
                )
            )
        else:
            ys = [box.y_cm + position * box.height_cm for position in ticks.positions]
            grobs.append(
                segments_grob(
                    [box.x_cm] * len(ys),
                    ys,
                    [box.x_cm - tick] * len(ys),
                    ys,
                    default_units="cm",
                    gp=gpar(col=colour, lwd=lwd, lty=lty),
                    name=f"{name}.ticks",
                )
            )

    mt, mr, _mb, _ml = margin_sides_cm(text.margin)
    gp = _text_gp(text)
    if side == "bottom":
        y = box.y_cm - tick - mt
        for index, (position, label) in enumerate(zip(ticks.positions, ticks.labels, strict=True)):
            grobs.append(
                text_grob(
                    label,
                    box.x_cm + position * box.width_cm,
                    y,
                    hjust=float(text.hjust if text.hjust is not None else 0.5),
                    vjust=1.0,
                    default_units="cm",
                    gp=gpar(**gp),
                    name=f"{name}.text.{index}",
                )
            )
    else:
        x = box.x_cm - tick - mr
        for index, (position, label) in enumerate(zip(ticks.positions, ticks.labels, strict=True)):
            grobs.append(
                text_grob(
                    label,
                    x,
                    box.y_cm + position * box.height_cm,
                    hjust=1.0,
                    vjust=float(text.vjust if text.vjust is not None else 0.5),
                    default_units="cm",
                    gp=gpar(**gp),
                    name=f"{name}.text.{index}",
                )
            )
    return grobs


def axis_title_grob(
    theme: ResolvedTheme,
    side: str,
    title: str | None,
    box: CellBox,
    *,
    labels_extent_cm: float = 0.0,
    metrics: Any = None,
    name: str = "axis-title",
) -> Any | None:
    """轴标题（x 轴水平、y 轴旋转 90°），与 R 的 `axis.title.*` 同一锚点口径。"""
    element = _title_element(theme, side)
    if title is None or not title or not isinstance(element, ElementText):
        return None
    mt, mr, _mb, _ml = margin_sides_cm(element.margin)
    gp = _text_gp(element)
    anchor = labels_extent_cm
    if side == "bottom":
        y = box.y_cm - anchor - mt
        return text_grob(
            title,
            box.x_cm + box.width_cm / 2.0,
            y,
            hjust=float(element.hjust if element.hjust is not None else 0.5),
            vjust=1.0,
            default_units="cm",
            gp=gpar(**gp),
            name=name,
        )
    x = box.x_cm - anchor - mr
    return text_grob(
        title,
        x,
        box.y_cm + box.height_cm / 2.0,
        hjust=0.5,
        vjust=0.5,
        rot=90.0,
        default_units="cm",
        gp=gpar(**gp),
        name=name,
    )

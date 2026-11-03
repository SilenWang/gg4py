"""主轴（M1-11）：刻度线 + 刻度标签 + 轴标题。

口径照 ggplot2 4.0.3 的 `R/guide-axis.R` + `ggplot_gtable()` 的 axis 行列：

- 断点 / 标签来自**该面板自己的**标度（`scale.breaks()` / `scale.labels()`）；
  连续标度的断点已经在变换后的空间（`scale_x_log10()` 给的是 log10 值），
  离散标度的断点是水平名，位置按 1..n 换算——两条路径最后都落到面板 npc；
- 尺寸（刻度长度、文字行高、文字与刻度的间距、轴标题间距）全部取
  `resolve_theme()` 的解析值，不硬编码 cm / pt；
- 轴文字 / 轴标题的行高是 **字号 × `lineheight`**（缺省 0.9，`axis_line_cm()`），
  与 `ggplotGrob()` 的 `axis-b` / `xlab-b` 行高一致；宽度走
  `Metrics.strwidth()`，没有度量时按 0.6em/字符估（`FALLBACK_CHAR_EM`）；
  位置专属元素（`axis.text.y.left` / `axis.ticks.x.bottom` …）按 R 的
  `theme_suffix` 取，不读父元素；
- 网格线（`panel.grid.*`）复用这里的 `break_positions()` /
  `minor_break_positions()`，与刻度同一套断点、但**不看标签**；
- 只做主轴：`sec_axis()` 明确报错（见 docs/notes/guide.md「未实现」）。

坐标约定：面板矩形是 cm、**y 向上**（与 grid 的 `subRegion()` 一致），所有
轴 grob 都以页面 cm 坐标直接落位，不引入新的视口层级。
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping
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
    "axis_line_cm",
    "axis_ticks",
    "axis_title_extent",
    "axis_title_grob",
    "break_positions",
    "font_int",
    "margin_sides_cm",
    "minor_break_positions",
    "paint",
    "text_line_cm",
    "text_width_cm",
    "tick_length_cm",
    "tick_paint",
]

#: R 的 `stringHeight()` + `font_descent()` ≈ 0.955em（见 docs/notes/guide.md）。
#: 8.8pt 的 axis.text 在 R 里量出 8.4pt 的行高，这里是同一口径。
TEXT_LINE_EM = 0.955

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
    """一行文字的占高（cm）：`size * 0.955em`（向导 / 标题的估算口径）。"""
    return float(size_pt) * TEXT_LINE_EM * _CM_PER_INCH / _POINTS_PER_INCH


#: `element_text(lineheight = )` 的缺省值（R `theme-elements.R` 的 `text` 根元素）。
TEXT_LINEHEIGHT = 0.9


def axis_line_cm(element: ElementText) -> float:
    """轴文字 / 轴标题的行高（cm）：`fontsize × lineheight`。

    R 的轴 grob 是 `element_grob(element_text, ...)`：grob 高度 = 字号 ×
    `lineheight`（缺省 0.9，`axis.text` / `axis.title` 继承 `text` 根元素），
    不是 `stringHeight()` 的 cap height。实测 8.8pt → 7.92pt、11pt → 9.89pt
    （`ggplotGrob()` 的 `axis-b` / `xlab-b` 行高，见
    `tests/fixtures/` 与 `docs/notes/guide.md`）。
    """
    size = float(element.size or 0.0)
    lineheight = TEXT_LINEHEIGHT if element.lineheight is None else float(element.lineheight)
    return size * lineheight * _CM_PER_INCH / _POINTS_PER_INCH


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
                    font=str(family or "sans"),
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


def _panel_span(params: Any, side: str) -> tuple[float, float]:
    low, high = _axis_range(params, side)
    span = float(high) - float(low)
    if span == 0:
        raise AxisError(f"{side} 轴的面板范围跨度为 0（{low!r} == {high!r}）")
    return float(low), span


def _map_break(scale: Any, params: Any, side: str, value: Any) -> float | None:
    """单个断点 → 面板 npc；`None`（越界）与映射不了的值给 None。"""
    if side not in ("bottom", "left"):
        raise AxisError(f"side 只能是 'bottom' / 'left'，收到 {side!r}")
    if scale is None or value is None:
        return None
    low, span = _panel_span(params, side)
    if bool(getattr(scale, "discrete", False)):
        levels = tuple(scale.levels)
        try:
            code = levels.index(str(value)) + 1
        except ValueError:
            return None
        position = (float(code) - low) / span
    else:
        number = float(value)
        if not math.isfinite(number):
            return None
        position = (number - low) / span
    return float(position) if math.isfinite(position) else None


def _mapped_breaks(scale: Any, params: Any, side: str) -> list[tuple[float, Any]]:
    """断点 → `(npc 位置, 断点值)`；`None`（越界）与映射不了的值直接丢掉。

    与 R 的 `ViewScale$mapped_breaks()` 同一口径：连续标度的断点已经在变换后的
    空间里，离散标度按水平序号 1..n 换成面板 npc。
    """
    if scale is None:
        return []
    out: list[tuple[float, Any]] = []
    for value in tuple(scale.breaks()):
        position = _map_break(scale, params, side, value)
        if position is not None:
            out.append((position, value))
    return out


def break_positions(scale: Any, params: Any, side: str) -> tuple[float, ...]:
    """主断点在面板里的位置（npc 0..1），**不看标签**——`panel.grid.major` 用。"""
    return tuple(position for position, _value in _mapped_breaks(scale, params, side))


def minor_break_positions(scale: Any, params: Any, side: str, *, n: int = 2) -> tuple[float, ...]:
    """次断点在面板里的位置（npc 0..1），口径照 `scales::regular_minor_breaks()`。

    - 只在连续标度上有：上游离散标度的 `minor_breaks` 是 `NULL`，不画次网格；
    - 主断点不足 2 个 → 没有次网格；
    - 主断点没盖住面板两端时，先把序列向两端各延一个间距（`bd`），再取每个
      区间的 `1/n` 分点（`n = 2` 即中点）；
    - 最后丢掉越界的位置与和主断点重合的位置（`guide_grid()` 的 `setdiff()`）。

    断点在变换后的空间里，面板映射是仿射的，所以在 npc 里算与在断点空间里算
    等价（对数标度的「中点在 log 空间」也随之成立）。
    """
    if scale is None or bool(getattr(scale, "discrete", False)):
        return ()
    majors = sorted(break_positions(scale, params, side))
    if len(majors) < 2:
        return ()
    step = majors[1] - majors[0]
    if not math.isfinite(step) or step <= 0:
        return ()
    breaks = list(majors)
    if 0.0 < breaks[0]:
        breaks.insert(0, breaks[0] - step)
    if 1.0 > breaks[-1]:
        breaks.append(breaks[-1] + step)
    positions: list[float] = []
    for left, right in itertools.pairwise(breaks):
        positions.extend(left + index * (right - left) / n for index in range(n))
    positions.append(breaks[-1])
    out: list[float] = []
    for position in positions:
        if not 0.0 <= position <= 1.0:
            continue
        if any(abs(position - major) <= 1e-12 for major in majors):
            continue
        if any(abs(position - kept) <= 1e-12 for kept in out):
            continue
        out.append(float(position))
    return tuple(out)


def axis_ticks(scale: Any, params: Any, side: str) -> AxisTicks:
    """一个面板的刻度位置（npc 0..1）+ 标签文本。

    `scale` 是该面板自己的标度（`PanelScaleSet.scale("x")`）；`params` 是
    :class:`ggcore.coord.PanelParams`。标度缺失 / 断点为空时返回空刻度。
    空标签的断点不画刻度文字，也不在这里出现（网格线走 :func:`break_positions`，
    不受标签影响）。
    """
    if side not in ("bottom", "left"):
        raise AxisError(f"side 只能是 'bottom' / 'left'，收到 {side!r}")
    if scale is None:
        return AxisTicks(side, (), ())
    breaks = tuple(scale.breaks())
    labels = tuple(scale.labels())
    if len(breaks) != len(labels):
        raise AxisError(
            f"标度 {scale.aesthetic!r} 的 breaks（{len(breaks)}）与 labels"
            f"（{len(labels)}）长度不一致"
        )
    positions: list[float] = []
    texts: list[str] = []
    for value, label in zip(breaks, labels, strict=True):
        if label is None:
            continue
        text = str(label)
        if not text:
            continue
        position = _map_break(scale, params, side, value)
        if position is None:
            continue
        positions.append(position)
        texts.append(text)
    return AxisTicks(side, tuple(positions), tuple(texts))


# ---------------------------------------------------------------------------
# 尺寸
# ---------------------------------------------------------------------------


#: 主轴所在的位置 → 主题元素名里的后缀（R 的 `theme_suffix`）。
#: 我们只画左下两条轴，所以固定是 `x.bottom` / `y.left`；R 的 guide 同样读
#: 位置专属元素（`axis.text.y.left` 而不是 `axis.text.y`），两者的区别在
#: `theme_minimal()` 这类只覆盖 `.left` / `.bottom` 的主题上会直接体现出来。
_AXIS_SUFFIX: Mapping[str, str] = {"bottom": "x.bottom", "left": "y.left"}


def _tick_element(theme: ResolvedTheme, side: str) -> Any:
    return theme.get(f"axis.ticks.{_AXIS_SUFFIX[side]}")


def _text_element(theme: ResolvedTheme, side: str) -> Any:
    return theme.get(f"axis.text.{_AXIS_SUFFIX[side]}")


def _title_element(theme: ResolvedTheme, side: str) -> Any:
    return theme.get(f"axis.title.{_AXIS_SUFFIX[side]}")


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
    """`axis.ticks.length` → cm（无刻度元素时为 0）。"""
    if tick_paint(theme, side) is None:
        return 0.0
    value = theme.get(f"axis.ticks.length.{_AXIS_SUFFIX[side]}")
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
        return axis_line_cm(element) + mt + mb
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
    mt, mr, mb, ml = margin_sides_cm(element.margin)
    if side == "bottom":
        return axis_line_cm(element) + mt + mb
    # y 轴标题旋转 90°：外向尺寸是行高（不是文字宽度）。
    return axis_line_cm(element) + ml + mr


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

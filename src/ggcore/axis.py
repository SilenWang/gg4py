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
- 主轴 + 次轴（M2-1）：`scale_*(sec.axis = sec_axis(~ . * 2))` 的断点 / 标签
  与上游 `AxisSecondary$break_info()` 逐步对齐（数值反演用 `np.interp`，等价于
  R 的 `approx()`）；次轴画在 **top / right**（R 的 axis-t / axis-r 槽），主轴
  仍只占 bottom / left，两层互不撑大对方。

坐标约定：面板矩形是 cm、**y 向上**（与 grid 的 `subRegion()` 一致），所有
轴 grob 都以页面 cm 坐标直接落位，不引入新的视口层级。
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Callable, Sequence
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
    "DERIVE",
    "FALLBACK_CHAR_EM",
    "TEXT_LINE_EM",
    "AxisError",
    "AxisTicks",
    "SecondaryAxis",
    "axis_extent",
    "axis_grobs",
    "axis_ticks",
    "axis_title_extent",
    "axis_title_grob",
    "dup_axis",
    "font_int",
    "margin_sides_cm",
    "paint",
    "polar_axis_row_cm",
    "sec_axis",
    "secondary_ticks",
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

#: 布局列宽里「拉丁文字」的度量字面。M2-a（SIL-728）把参考产线的默认拉丁字面
#: 定位成 **Arimo**（R/svglite 的 `font-family: "Arimo"`），绘制端
#: `ggskia.text.SANS_FAMILY` 与它一致；布局量宽必须用同一字面，否则 `gear`
#: 这类字符串会差 7%（Noto Sans 的 g 更宽），图例盒 / y 轴列宽随之偏。
#: 这里只**量宽度**（列宽 / 图例标签盒），不换绘制字面。
LAYOUT_LATIN_FONT = "Arimo"

#: 没有 `Metrics` 时每字符的宽度（em）。只在布局估算里用，渲染宽度由 IR 文本节点
#: 自带的 `text.width` 决定；有度量时一律走 `Metrics.strwidth()`。
FALLBACK_CHAR_EM = 0.6

_CM_PER_INCH = 2.54
_POINTS_PER_INCH = 72.0


class AxisError(ValueError):
    """轴参数无法表达（secondary axis 的非法变换 / 旋转标签等）。"""


#: `sec_axis()` 的「沿用主轴」标记（上游 `derive()`）：`dup_axis()` 的缺省标题。
#: `None` 则是上游 `waiver()` / `NULL`：**不显示次轴标题**（SIL-759）。
DERIVE: Any = object()


@dataclass(frozen=True, slots=True)
class SecondaryAxis:
    """`sec_axis(transform, name, breaks, labels, guide)`（上游 `AxisSecondary`）。

    `transform` 是**主轴值 → 次轴值**的函数（`~ . * 2` 即 `lambda v: v * 2`）。
    断点 / 标签缺省 `None`（= 上游 `waiver()`：按主轴推）。

    标题三条口径（R 4.0.3 实测）：

    - `name=None`（`sec_axis()` 的缺省，= R 的 `waiver()` / `NULL`）：不显示标题；
    - `name=DERIVE`（`dup_axis()` 的缺省，= R 的 `derive()`）：沿用主轴标题；
    - 其它值：原样作为次轴标题。
    """

    transform: Callable[[Any], Any] | None = None
    name: Any = None
    breaks: Any = None
    labels: Any = None
    guide: Any = None

    def __post_init__(self) -> None:
        if self.transform is not None and not callable(self.transform):
            raise AxisError(
                f"sec_axis() 的 transform 必须是函数（`~ . * 2` → `lambda v: v * 2`），"
                f"收到 {self.transform!r}"
            )
        if self.breaks is not None and self.breaks is not DERIVE:
            if isinstance(self.breaks, (str, bytes)) or not isinstance(self.breaks, Sequence):
                raise AxisError(f"sec_axis(breaks = ...) 必须是序列（数值），收到 {self.breaks!r}")
            for item in self.breaks:
                if not isinstance(item, numbers.Real) or isinstance(item, bool):
                    raise AxisError(f"sec_axis(breaks = ...) 的每一项必须是数值，收到 {item!r}")
        if self.labels is not None and self.labels is not DERIVE:
            if isinstance(self.labels, (str, bytes)):
                raise AxisError(f"sec_axis(labels = ...) 必须是序列或回调，收到 {self.labels!r}")

    @property
    def empty(self) -> bool:
        return self.transform is None

    @property
    def is_identity(self) -> bool:
        """`dup_axis()` 的口径：变换就是恒等（不传或显式 identity）。"""
        return self.transform is None or self.transform is _identity

    def forward(self, values: np.ndarray) -> np.ndarray:
        if self.transform is None:
            return np.asarray(values, dtype=np.float64)
        return np.asarray(self.transform(np.asarray(values, dtype=np.float64)), dtype=np.float64)


def _identity(values: Any) -> Any:
    return values


def sec_axis(
    transform: Callable[[Any], Any] | None = None,
    name: Any = None,
    breaks: Any = None,
    labels: Any = None,
    guide: Any = None,
) -> SecondaryAxis:
    """`sec_axis(~ . * 2)`：给位置标度加第二条轴（画在 top / right）。

    `name` 缺省 `None` = 上游 `waiver()`：**不显示次轴标题**（主轴标题仍在
    自己的轴上）；要沿用主轴标题用 `dup_axis()` 或 `name=DERIVE`。
    """
    return SecondaryAxis(transform, name, breaks, labels, guide)


def dup_axis(
    transform: Callable[[Any], Any] | None = None,
    name: Any = DERIVE,
    breaks: Any = None,
    labels: Any = None,
    guide: Any = None,
) -> SecondaryAxis:
    """`dup_axis()`：与主轴同值的第二条轴（`sec_axis(identity)`）。

    上游 `dup_axis()` 的 `name = derive()`：缺省**沿用主轴标题**（`SEC_AXIS` 的
    `sec_axis()` 缺省则是 `waiver()`，不显示标题）。
    """
    return SecondaryAxis(transform or _identity, name, breaks, labels, guide)


@dataclass(frozen=True, slots=True)
class AxisTicks:
    """一条主轴的刻度：`side` 是 `"bottom"` / `"left"`。"""

    side: str
    positions: tuple[float, ...]
    labels: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.side not in ("bottom", "left", "top", "right"):
            raise AxisError(f"side 只能是 bottom / left / top / right，收到 {self.side!r}")
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


def text_block_cm(text: str, size_pt: float, lineheight: float | None = None) -> float:
    """整块文字的占高（cm）：`(n-1) × 行距 + 单行高`。

    R 的 `textGrob` 把 `\\n` 切成多行，块高 = 首行高 + (n-1) 个行距；行距是
    `lineheight × 1.2 × fontsize`（`ggskia.text.LINE_PITCH` 同一口径，`axis.text.*`
    的 `lineheight = 0.9`）。早先按单行量，`"X\\nX\\nX\\nX\\nX"` 这类多行轴标签的
    轴带高度只有一行的量，面板因此被撑高（SIL-816 的
    `outside-justified-labels`）。
    """
    lines = len(_lines(text)) or 1
    pitch = float(size_pt) * 1.2 * float(lineheight if lineheight else 1.2)
    return text_line_cm(size_pt) + (lines - 1) * pitch * _CM_PER_INCH / _POINTS_PER_INCH


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
                    font=str(family),
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


def paint(value: Any) -> Any:
    """主题颜色 → 可绘制的颜色；`NA` / `transparent` / 缺失 → None。

    渐变 / 图案的待解析规格（`ggcore.fills`）原样透传——`panel.background` /
    `plot.background` 的 `element_rect(fill = 渐变)` 走这一条。
    """
    if hasattr(type(value), "resolve"):
        return value
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


def axis_breaks(scale: Any, params: Any, axis: str) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    """一条轴的断点 / 标签（npc 之前）。

    连续标度用面板自己的 `continuous_range` 取断点（R
    `view_scales_from_scale()` 把连续范围喂给 `scale$break_info()`）：这是
    `coord_cartesian(xlim=)` / `coord_trans()` 下 1 / 3 / 10 与 1 / 10 / 100 的
    分水岭。离散标度按 1..n 的水平序号，和标度自己的断点一致。
    """
    breaks = tuple(scale.breaks())
    labels = tuple(scale.labels())
    if bool(getattr(scale, "discrete", False)) or not hasattr(scale, "breaks_in"):
        return breaks, labels
    continuous = getattr(params, "continuous_ranges", None)
    if continuous is None or axis not in continuous:
        return breaks, labels
    low, high = continuous[axis]
    sized = tuple(scale.breaks_in(low, high))
    if sized == breaks:
        return breaks, labels
    return sized, tuple(scale.labels_in(sized))


def _tick_positions(
    scale: Any,
    params: Any,
    side: str,
    values: Sequence[Any],
    labels: Sequence[Any],
    *,
    filter_outside: bool,
) -> AxisTicks:
    """断点 / 标签 → npc；两条路径（离散 1..n、连续数值）最后都走 `position_of()`。"""
    axis = params.screen_axis(side)
    positions: list[float] = []
    texts: list[str] = []
    discrete = bool(getattr(scale, "discrete", False))
    levels = tuple(scale.levels) if discrete else ()
    for value, label in zip(values, labels, strict=True):
        if value is None or label is None:
            continue
        text = str(label)
        if not text:
            continue
        if discrete:
            try:
                number = float(levels.index(str(value)) + 1)
            except ValueError:
                continue
        else:
            number = float(value)
            if not math.isfinite(number):
                continue
        position = params.position_of(axis, number)
        if not math.isfinite(position):
            continue
        if filter_outside and not (-1e-9 <= position <= 1.0 + 1e-9):
            continue
        positions.append(min(max(position, 0.0), 1.0))
        texts.append(text)
    return AxisTicks(side, tuple(positions), tuple(texts))


def axis_ticks(
    scale: Any,
    params: Any,
    side: str,
    *,
    secondary: bool = False,
) -> AxisTicks:
    """一个面板在某条边上的刻度位置（npc 0..1）+ 标签文本。

    `scale` 是该面板自己的标度（`PanelScaleSet.scale(...)`；flip 时由
    `params.scale_key(side)` 给出对侧标度）；`params` 是
    :class:`ggcore.coord.PanelParams`。标度缺失 / 断点为空时返回空刻度。

    - 主轴：`bottom` / `left`；
    - 次轴（`secondary=True`）：`top` / `right`，断点由
      :func:`secondary_ticks()` 从 `scale.secondary_axis` 推出；
    - 极坐标：theta 轴不占 gtable 槽（标签画在面板里，见
      :func:`polar_theta_ticks`），r 轴在 `left`（`r.axis.inside = TRUE` 时为空）。
    """
    if side not in ("bottom", "left", "top", "right"):
        raise AxisError(f"side 只能是 bottom / left / top / right，收到 {side!r}")
    if scale is None:
        return AxisTicks(side, (), ())
    if secondary:
        return secondary_ticks(scale, params, side)
    if getattr(params, "polar", None) is not None:
        return _polar_ticks(scale, params, side)
    breaks, labels = axis_breaks(scale, params, params.screen_axis(side))
    ticks = _tick_positions(
        scale,
        params,
        side,
        breaks,
        labels,
        filter_outside=bool(getattr(params, "flipped", False))
        or not getattr(params, "is_linear", True),
    )
    return AxisTicks(side, ticks.positions, ticks.labels)


def _primary_param(scale: Any, name: str) -> Any:
    """主轴标度上的原始参数（`breaks` / `labels`）；没写就是 `None`（R 的 waiver）。"""
    getter = getattr(scale, "_param", None)
    if getter is None:
        return None
    try:
        return getter(name)
    except TypeError:  # pragma: no cover - 自定义标度子类可能没有该参数
        return None


def secondary_ticks(scale: Any, params: Any, side: str) -> AxisTicks:
    """次轴刻度：`AxisSecondary$break_info()` 的移植（M2-1）。

    步骤与上游一致：

    1. 主轴范围 `continuous_range`（标度空间 + expand）上取 1000 个样点，
       过 `transform()` 得到次轴空间；样点必须严格单调（上游 `mono_test()`）。
    2. `breaks` 缺省时，在次轴空间的范围内用 `extended_breaks()` 取断点
       （`dup_axis()` 的恒等变换直接沿用主轴断点 / 标签）。
    3. 用 `np.interp()` 把次轴断点反演回主轴值（R 是 `approx(full, old, ...)`），
       再按主轴范围映射成 npc。
    """
    sa = getattr(scale, "secondary_axis", None)
    if sa is None:
        return AxisTicks(side, (), ())
    polar = getattr(params, "polar", None)
    axis = polar.r_axis if polar is not None else params.screen_axis(side)

    def _position(value: float) -> float:
        """次轴值（主轴空间的数值）→ 该边上的 npc 位置。"""
        if polar is not None:
            # 极坐标 / 径向坐标的次轴是 r 轴：位置 = `r_rescale(r) + 0.5`
            # （上游 `CoordPolar$render_axis_v()`）。
            return float(polar.radius(np.array([value]))[0]) + 0.5
        return params.position_of(axis, float(value))

    low, high = params.continuous_ranges[axis]
    if high < low:
        low, high = high, low
    if bool(getattr(sa, "is_identity", False)):
        breaks = tuple(scale.breaks())
        labels = tuple(scale.labels())
        # `breaks()` 里的越界项是 `None`（R 的 `NA`），标签与它逐位对齐；
        # 先配对再丢 None，不能先滤断点再 zip（长度会错位）。
        pairs = [
            (_position(float(value)), str(label))
            for value, label in zip(breaks, labels, strict=False)
            if value is not None and label is not None and str(label)
        ]
        pairs = [(position, label) for position, label in pairs if -1e-9 <= position <= 1.0 + 1e-9]
        return AxisTicks(
            side,
            tuple(min(max(position, 0.0), 1.0) for position, _ in pairs),
            tuple(text for _, text in pairs),
        )
    samples = np.linspace(low, high, 1000)
    forward = sa.forward(samples)
    if not np.all(np.isfinite(forward)):
        raise AxisError(
            "sec_axis() 的变换在主轴范围上给出了非有限值（R: Transformation for "
            "secondary axes must be strictly monotonic）；检查定义域"
        )
    steps = np.diff(forward)
    if not (np.all(steps > 0) or np.all(steps < 0)):
        raise AxisError(
            "sec_axis() 的变换必须严格单调（R: Transformation for secondary "
            "axes must be strictly monotonic）"
        )
    order = np.argsort(forward)
    forward = forward[order]
    primary = samples[order]
    sec_range = (float(forward[0]), float(forward[-1]))
    breaks_param = getattr(sa, "breaks", None)
    if breaks_param is DERIVE:
        # `sec_axis(breaks = derive())`：沿用主轴的 breaks **规格**（数值向量 /
        # 回调 / NULL）。上游 `AxisSecondary$init()` 直接 `self$breaks <- scale$breaks`，
        # 随后在次轴空间里重新求值。
        breaks_param = _primary_param(scale, "breaks")
    if breaks_param is not None:
        sec_breaks = list(breaks_param)
    else:
        from ggcore.scales import extended_breaks

        sec_breaks = list(extended_breaks(sec_range[0], sec_range[1], 5))
    labels_param = getattr(sa, "labels", None)
    if labels_param is DERIVE:
        labels_param = _primary_param(scale, "labels")
    if labels_param is not None:
        labels = [str(item) for item in labels_param]
        if len(labels) != len(sec_breaks):
            raise AxisError(
                f"sec_axis(labels=) 有 {len(labels)} 项，断点有 {len(sec_breaks)} 项（必须等长）"
            )
    else:
        date_kind = getattr(getattr(scale, "transform_", None), "date_kind", None)
        if date_kind is not None:
            # 日期 / 时间标度的次轴：标签按主轴的时间口径格式化（上游对 date / time
            # 变换建临时标度，`get_labels()` 仍走日期格式）。
            transform_ = scale.transform_
            labels = [str(item) for item in transform_.label(sec_breaks)]
        else:
            from ggcore.scales import format_numbers

            labels = [str(item) for item in format_numbers(sec_breaks)]
    primary_values = np.interp(np.asarray(sec_breaks, dtype=np.float64), forward, primary)
    positions = [_position(float(value)) for value in primary_values]
    pairs = [
        (position, label)
        for position, label in zip(positions, labels, strict=True)
        if label and -1e-9 <= position <= 1.0 + 1e-9
    ]
    return AxisTicks(
        side,
        tuple(min(max(position, 0.0), 1.0) for position, _ in pairs),
        tuple(label for _, label in pairs),
    )


def _polar_ticks(scale: Any, params: Any, side: str) -> AxisTicks:
    """极坐标的 r 轴（`left`）：`r_rescale(r, r.range) + 0.5`（上游同式）。

    theta 轴没有 gtable 槽（R 的 `render_axis_h()` 给的是 `zeroGrob()`），
    标签画在面板里，由 :func:`polar_theta_ticks` 提供。
    """
    polar = params.polar
    if side in ("bottom", "top"):
        return AxisTicks(side, (), ())
    if bool(getattr(polar, "r_axis_inside", False)):
        return AxisTicks(side, (), ())
    axis = params.screen_axis(side)
    values: list[float] = []
    texts: list[str] = []
    breaks = tuple(scale.breaks())
    labels = tuple(scale.labels())
    discrete = bool(getattr(scale, "discrete", False))
    levels = tuple(scale.levels) if discrete else ()
    for value, label in zip(breaks, labels, strict=True):
        if value is None or label is None or not str(label):
            continue
        if discrete:
            try:
                number = float(levels.index(str(value)) + 1)
            except ValueError:
                continue
        else:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
        if not math.isfinite(number):
            continue
        values.append(float(polar.radius(np.array([number]))[0]) + 0.5)
        texts.append(str(label))
    del axis
    return AxisTicks(side, tuple(values), tuple(texts))


def polar_theta_ticks(scale: Any, params: Any) -> tuple[tuple[float, float, str], ...]:
    """theta 轴的标签锚点：`(x_npc, y_npc, text)`，半径 0.45（外圈 0.05 留给标签）。

    满圆时首尾两个标签（0 与 2π 是同一个位置）按上游 `render_fg()` 的规则合并成
    `"a/b"`：`ends_apart < 0.05` 才合并。
    """
    polar = params.polar
    if polar is None or scale is None:
        return ()
    breaks = tuple(scale.breaks())
    labels = tuple(scale.labels())
    angles: list[float] = []
    texts: list[str] = []
    for value, label in zip(breaks, labels, strict=True):
        if value is None or label is None or not str(label):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(number):
            continue
        angles.append(float(polar.theta_angle(np.array([number]))[0]))
        texts.append(str(label))
    if not texts:
        return ()
    if len(angles) >= 2:
        ends_apart = (angles[-1] - angles[0]) % (2.0 * math.pi)
        if ends_apart < 0.05:
            texts = [f"{texts[0]}/{texts[-1]}", *texts[1:-1]]
            angles = angles[:-1]
    (x0, x1), (y0, y1) = polar.bbox
    out: list[tuple[float, float, str]] = []
    for angle, text in zip(angles, texts, strict=True):
        px = 0.45 * math.sin(angle) + 0.5
        py = 0.45 * math.cos(angle) + 0.5
        out.append(((px - x0) / (x1 - x0), (py - y0) / (y1 - y0), text))
    return tuple(out)


# ---------------------------------------------------------------------------
# 尺寸
# ---------------------------------------------------------------------------


def _horizontal(side: str) -> bool:
    return side in ("bottom", "top")


def _tick_element(theme: ResolvedTheme, side: str) -> Any:
    return theme.get("axis.ticks.x" if _horizontal(side) else "axis.ticks.y")


def _text_element(theme: ResolvedTheme, side: str) -> Any:
    return theme.get("axis.text.x" if _horizontal(side) else "axis.text.y")


def _title_element(theme: ResolvedTheme, side: str) -> Any:
    return theme.get("axis.title.x" if _horizontal(side) else "axis.title.y")


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
    side_names = {
        "bottom": ("axis.ticks.length.x.bottom", "axis.ticks.length.x"),
        "top": ("axis.ticks.length.x.top", "axis.ticks.length.x"),
        "left": ("axis.ticks.length.y.left", "axis.ticks.length.y"),
        "right": ("axis.ticks.length.y.right", "axis.ticks.length.y"),
    }.get(side, ())
    value = None
    for name in (*side_names, "axis.ticks.length"):
        value = theme.get(name)
        if value is not None:
            break
    if value is None:
        return 0.0
    context = UnitContext()
    convert = convert_height if _horizontal(side) else convert_width
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
    if _horizontal(side):
        return text_line_cm(size) + mt + mb
    if not labels:
        return 0.0
    widest = max(text_width_cm(label, size, metrics, family) for label in labels)
    return widest + ml + mr


def polar_axis_row_cm(theme: ResolvedTheme) -> float:
    """极性坐标留在 `axis-b` 行的高度（cm）。

    上游 `CoordPolar` 把 theta 标签画在面板**内部**（`render_fg()`），但
    `ggplotGrob()` 仍然给它们留一行 `axis-b`：刻度长度 + 标签行高。标签行高来自
    `titleGrob`（`grobheight + |cos θ|·descent`），**不是**整行文字高度，所以
    跟 `axis_extent()` 的 cartesian 口径不一样。

    对 4–52 pt 的轴文字，R 4.5.3 + ggplot2 4.0.3 + svglite 实测是一条直线
    `0.22·size + 2.2` pt（误差 < 0.1 pt；缺省 `axis.text` 8.8 pt → 4.19 pt）。
    轴文字是 `element_blank()` 时只剩刻度长度（实测 2.75 pt）。
    """
    tick = tick_length_cm(theme, "bottom")
    text = theme.get("axis.text.x")
    if isinstance(text, ElementBlank) or not isinstance(text, ElementText):
        return tick
    size = float(text.size or 0.0)
    return tick + (0.22 * size + 2.2) * _CM_PER_INCH / _POINTS_PER_INCH


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
    if _horizontal(side):
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
        if _horizontal(side):
            xs = [box.x_cm + position * box.width_cm for position in ticks.positions]
            edge = box.y_cm + box.height_cm if side == "top" else box.y_cm
            inward = tick if side == "top" else -tick
            grobs.append(
                segments_grob(
                    xs,
                    [edge] * len(xs),
                    xs,
                    [edge + inward] * len(xs),
                    default_units="cm",
                    gp=gpar(col=colour, lwd=lwd, lty=lty),
                    name=f"{name}.ticks",
                )
            )
        else:
            ys = [box.y_cm + position * box.height_cm for position in ticks.positions]
            # 左轴刻度朝外（面板左边缘 → 更左），右轴（次轴）朝右。
            edge = box.right if side == "right" else box.x_cm
            inward = tick if side == "right" else -tick
            grobs.append(
                segments_grob(
                    [edge] * len(ys),
                    ys,
                    [edge + inward] * len(ys),
                    ys,
                    default_units="cm",
                    gp=gpar(col=colour, lwd=lwd, lty=lty),
                    name=f"{name}.ticks",
                )
            )

    mt, mr, _mb, _ml = margin_sides_cm(text.margin)
    gp = _text_gp(text)
    if _horizontal(side):
        if side == "top":
            y = box.y_cm + box.height_cm + tick + _mb
            vjust = 0.0
        else:
            y = box.y_cm - tick - mt
            vjust = 1.0
        for index, (position, label) in enumerate(zip(ticks.positions, ticks.labels, strict=True)):
            grobs.append(
                text_grob(
                    label,
                    box.x_cm + position * box.width_cm,
                    y,
                    hjust=float(text.hjust if text.hjust is not None else 0.5),
                    vjust=vjust,
                    default_units="cm",
                    gp=gpar(**gp),
                    name=f"{name}.text.{index}",
                )
            )
    else:
        if side == "right":
            x = box.right + tick + mr
            hjust = 0.0
        else:
            x = box.x_cm - tick - mr
            hjust = 1.0
        for index, (position, label) in enumerate(zip(ticks.positions, ticks.labels, strict=True)):
            grobs.append(
                text_grob(
                    label,
                    x,
                    box.y_cm + position * box.height_cm,
                    hjust=hjust,
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
    """轴标题（x 轴水平、y 轴旋转 90°），与 R 的 `axis.title.*` 同一锚点口径。

    `top` / `right`（次轴）也走这里：左侧标题 `rotate(-90)`（本仓 IR 的 y 向下，
    对应 `rot = 90`），右侧标题 `rotate(90)`（`rot = -90`）——与 R 的 SVG 同向。
    """
    element = _title_element(theme, side)
    if title is None or not title or not isinstance(element, ElementText):
        return None
    mt, mr, _mb, _ml = margin_sides_cm(element.margin)
    gp = _text_gp(element)
    anchor = labels_extent_cm
    if _horizontal(side):
        if side == "top":
            y = box.top + anchor + _mb
            vjust = 0.0
        else:
            y = box.y_cm - anchor - mt
            vjust = 1.0
        return text_grob(
            title,
            box.x_cm + box.width_cm / 2.0,
            y,
            hjust=float(element.hjust if element.hjust is not None else 0.5),
            vjust=vjust,
            default_units="cm",
            gp=gpar(**gp),
            name=name,
        )
    right = side == "right"
    x = (box.right + anchor + mr) if right else (box.x_cm - anchor - mr)
    return text_grob(
        title,
        x,
        box.y_cm + box.height_cm / 2.0,
        hjust=0.5,
        vjust=0.5,
        rot=-90.0 if right else 90.0,
        default_units="cm",
        gp=gpar(**gp),
        name=name,
    )

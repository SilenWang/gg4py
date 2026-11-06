"""轴 guide（M2-S2 / SIL-739）：`guide_axis` / `guide_axis_logticks` /
`guide_axis_stack` / `guide_axis_theta`。

对齐 ggplot2 4.0.3 的 `R/guide-axis.R`、`R/guide-axis-logticks.R`、
`R/guide-axis-stack.R`、`R/guide-axis-theta.R`：

- **断点 / 标签**仍由 :mod:`ggcore.axis` 的 `axis_ticks()` 给出（离散 1..n、
  连续变换后的空间、polar / secondary 三条路径共用）；
- 本模块只负责 guide 层的语义：旋转（`angle`）、稀疏（`check.overlap`）、
  分行（`n.dodge`）、次刻度（`minor.ticks`）、对数刻度（`guide_axis_logticks`
  的 long / mid / short 三档）、叠放（`guide_axis_stack`）与极坐标 theta 轴。

尺寸公式照 R 的 `GuideAxis$measure_grobs()`：

```
横向轴高 = max(刻度长) + 行数 × 标签盒高
标签盒高 = |w·sin a| + |h·cos a| + margin_t + margin_b      （a = 标签角度）
竖向轴宽 = max(刻度长) + 行数 × 标签盒宽
标签盒宽 = |w·cos a| + |h·sin a| + margin_l + margin_r
```

`w` 是标签文字宽（`Metrics.strwidth()`），`h` 是行高（`text_line_cm()`）。
R 的 pdf 设备用 Helvetica 的回退度量（0.959em），本仓用 svglite 口径的
0.8945em；差 0.02cm，远小于 0.05cm 的对拍容差（`docs/notes/guide.md`）。

对数刻度直接用 `scales::minor_breaks_log()` 的移植
（:func:`minor_breaks_log`），位置 / 档位与 R 逐段一致。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

from ggcore.axis import (
    AxisTicks,
    text_width_cm,
)
from ggcore.gtable import CellBox
from ggcore.theme import ElementBlank, ElementLine, ElementText, ResolvedTheme

__all__ = [
    "AxisGuide",
    "AxisGuideTicks",
    "AxisLabel",
    "AxisMark",
    "AxisSuffixTheme",
    "axis_guide_extent",
    "axis_guide_from_component",
    "axis_guide_grobs",
    "axis_guide_ticks",
    "axis_line_grobs",
    "axis_line_range",
    "draw_axis",
    "guide_axis",
    "guide_axis_logticks",
    "guide_axis_stack",
    "guide_axis_theta",
    "guide_for",
    "minor_breaks_log",
    "polar_axis_grobs",
]

#: `title=waiver()` 的对等物（轴 guide 的标题不参与绘制，保留以便转写）。
AUTO: Any = object()


class AxisSuffixTheme:
    """把 `axis.*.y` 换到 `axis.*.r` 的只读主题视图（`coord_radial()` 的 r 轴）。

    上游 `GuideAxis$setup_elements()` 把 `params$theme_suffix` 拼到每个元素名后面；
    `CoordRadial$train_panel_guides()` 给 r 轴设的是 `"r"`，于是它读
    `axis.text.r` / `axis.ticks.r` / `axis.line.r`——`axis.text.r` 两侧各 2.2pt
    margin 且 `hjust = 0.5`，与 `axis.text.y` 只留右侧 margin、`hjust = 1` 不同
    （SIL-843：`guide-axis-theta with angle adapting` 的 axis-l 列宽 16.97pt 就差
    在这 2.2pt 上，面板整体横移 1.1pt）。
    """

    def __init__(self, theme: ResolvedTheme, suffix: str) -> None:
        self._theme = theme
        self._suffix = suffix

    def _map(self, name: str) -> str:
        for prefix in ("axis.text.", "axis.ticks.", "axis.line.", "axis.minor.ticks."):
            if name.startswith(prefix):
                rest = name[len(prefix) :]
                if rest.split(".")[0] in ("x", "y"):
                    return f"{prefix}{self._suffix}"
        return name

    def get(self, name: str, default: Any = None) -> Any:
        return self._theme.get(self._map(name), default)

    def __getitem__(self, name: str) -> Any:
        return self._theme[self._map(name)]

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and self._map(name) in self._theme

    def size_pt(self, name: str) -> float:
        return self._theme.size_pt(self._map(name))

    def __getattr__(self, item: str) -> Any:
        return getattr(self._theme, item)


#: ggplot2 的 `.pt`：主题的 `linewidth`（mm）→ `lwd`（pt）用 72.27，不是 72。
_POINT_PER_MM = 72.27 / 25.4

_AXIS_NAMES = ("axis", "axis_logticks", "axis_stack", "stacked_axis", "axis_theta", "none")


@dataclass(frozen=True, slots=True)
class AxisGuide:
    """一条轴 guide 的参数（`guide_axis()` 及其变体共用）。"""

    name: str = "axis"
    title: Any = AUTO
    angle: float | None = None
    check_overlap: bool = False
    n_dodge: int = 1
    minor_ticks: bool = False
    cap: str = "none"
    position: str | None = None
    #: `guide_axis_logticks()`：三档长度的倍数与是否用展开后的范围。
    long: float = 2.25
    mid: float = 1.5
    short: float = 0.75
    expanded: bool = True
    negative_small: float | None = None
    #: `guide_axis_stack()`：按顺序叠放的子 guide。
    guides: tuple[AxisGuide, ...] = ()
    spacing: Any = None
    #: 逐 guide 主题（`guide_axis(theme = ...)`）：只覆盖**这一条 guide** 的元素，
    #: 不串到全局 theme。R 里它挂在 `Guide$theme` 上，渲染时与全局 theme 合并后
    #: 只作用在该 guide 的 grob 上（`axis.line.theta` / `r.axis.inside` /
    #: `rotate.angle` 都读它）。
    theme: Any = None

    def __post_init__(self) -> None:
        if self.name not in _AXIS_NAMES:
            raise ValueError(f"未知的轴 guide {self.name!r}；可用：{', '.join(_AXIS_NAMES)}")
        if self.angle is not None and not isinstance(self.angle, (int, float)):
            raise ValueError(f"axis guide 的 angle 必须是数字，收到 {self.angle!r}")
        if not isinstance(self.n_dodge, int) or self.n_dodge < 1:
            raise ValueError(f"axis guide 的 n.dodge 必须是正整数，收到 {self.n_dodge!r}")
        if self.cap not in ("none", "both", "upper", "lower", "top", "bottom"):
            raise ValueError(
                "axis guide 的 cap 只能是 none / both / upper / lower（top / bottom 是别名），"
                f"收到 {self.cap!r}"
            )
        object.__setattr__(self, "guides", tuple(self.guides))

    @property
    def is_stack(self) -> bool:
        return self.name in ("axis_stack", "stacked_axis")

    @property
    def is_logticks(self) -> bool:
        return self.name == "axis_logticks"

    @property
    def is_theta(self) -> bool:
        return self.name == "axis_theta"


def guide_axis(
    title: Any = AUTO,
    *,
    check_overlap: bool = False,
    angle: float | None = None,
    n_dodge: int = 1,
    minor_ticks: bool = False,
    cap: str = "none",
    position: str | None = None,
    order: float = 0.0,
    theme: Any = None,
) -> AxisGuide:
    del order  # 轴 guide 的 order 在 R 里也只用于 guides() 排序，轴本身不读
    return AxisGuide(
        name="axis",
        title=title,
        angle=angle,
        check_overlap=bool(check_overlap),
        n_dodge=int(n_dodge),
        minor_ticks=bool(minor_ticks),
        cap=cap,
        position=position,
        theme=theme,
    )


def guide_axis_logticks(
    long: float = 2.25,
    mid: float = 1.5,
    short: float = 0.75,
    prescale_base: float | None = None,
    negative_small: float | None = None,
    expanded: bool = True,
    cap: str = "none",
    *,
    preserve: str | None = None,
    order: float = 0.0,
) -> AxisGuide:
    """对数轴次刻度。

    4.0.3 的参数是 `long` / `mid` / `short` / `cap` / `expanded`；
    `preserve` 是本仓为「保留最外两段」提供的别名（`"top"` → `cap="upper"`、
    `"bottom"` → `cap="lower"`、`"both"` → `cap="both"`），见 docs/notes/guide.md。
    """
    del order
    if preserve is not None:
        cap = {"top": "upper", "bottom": "lower"}.get(str(preserve), str(preserve))
    if prescale_base not in (None, 10):
        raise ValueError("guide_axis_logticks 只支持 base 10 的 prescale.base")
    return AxisGuide(
        name="axis_logticks",
        long=float(long),
        mid=float(mid),
        short=float(short),
        expanded=bool(expanded),
        negative_small=negative_small,
        cap=cap,
        minor_ticks=True,
    )


def guide_axis_stack(
    first: Any = "axis",
    *guides: Any,
    title: Any = AUTO,
    spacing: Any = None,
    angle: float | None = None,
) -> AxisGuide:
    """`guide_axis_stack(guide_axis(), guide_axis_logticks())`：从内到外叠放。"""
    items = [first, *guides]
    parsed: list[AxisGuide] = []
    for item in items:
        if isinstance(item, AxisGuide):
            parsed.append(item)
        elif isinstance(item, str):
            # R 的 `guide_axis_stack("axis_theta", ...)`：字符串是 sub-guide 的
            # 注册名（`"axis"` / `"axis_theta"` / `"axis_logticks"`）。
            if item == "axis":
                parsed.append(guide_axis())
            elif item == "axis_theta":
                parsed.append(guide_axis_theta())
            elif item == "axis_logticks":
                parsed.append(guide_axis_logticks())
            else:
                raise ValueError(
                    "guide_axis_stack() 的子 guide 必须是 AxisGuide 或 "
                    f"'axis' / 'axis_theta' / 'axis_logticks'，收到 {item!r}"
                )
        else:
            raise ValueError(
                "guide_axis_stack() 的子 guide 必须是 AxisGuide（guide_axis() / "
                f"guide_axis_logticks()），收到 {item!r}"
            )
    if not parsed:
        parsed = [guide_axis()]
    if angle is not None:
        parsed = [replace_angle(item, angle) for item in parsed]
    return AxisGuide(
        name="axis_stack",
        title=title,
        guides=tuple(parsed),
        spacing=spacing,
    )


def replace_angle(guide: AxisGuide, angle: float) -> AxisGuide:
    from dataclasses import replace

    return replace(guide, angle=guide.angle if guide.angle is not None else float(angle))


def guide_axis_theta(
    title: Any = AUTO,
    *,
    angle: float | None = None,
    minor_ticks: bool = False,
    cap: str = "none",
    theme: Any = None,
) -> AxisGuide:
    return AxisGuide(
        name="axis_theta",
        title=title,
        angle=angle,
        minor_ticks=bool(minor_ticks),
        cap=cap,
        theme=theme,
    )


# ---------------------------------------------------------------------------
# component → AxisGuide
# ---------------------------------------------------------------------------


def axis_guide_from_component(component: Any) -> AxisGuide | None:
    """`components.Guide`（注册名 + 参数）→ :class:`AxisGuide`；`none` 返回 None。

    `guide_none(title=...)` 例外：它在 R 里仍保留**轴标题**（`guides(x =
    guide_none(title = "x (primary)"))` 只去掉刻度与标签），所以带标题时返回
    `AxisGuide(name="none", title=...)`，让 scene 的标题阶段照常落字。

    字符串也认（`guides(x = "axis_theta")`）：按注册名构造成组件再走同一条路。
    """
    if isinstance(component, str):
        from ggcore import registry as _registry

        if component not in _registry.registered("guide"):
            return None
        component = _registry.construct("guide", component)
    name = getattr(component, "name", None)
    params = dict(getattr(component, "params", {}) or {})
    if name == "none":
        title = params.get("title", AUTO)
        if title is AUTO or title is None:
            return AxisGuide(name="none", title=None)
        return AxisGuide(name="none", title=title)
    if name is None:
        return None
    if name in ("axis", "axis_theta"):
        factory = guide_axis if name == "axis" else guide_axis_theta
        allowed = {
            "title",
            "angle",
            "check_overlap",
            "check.overlap",
            "n_dodge",
            "n.dodge",
            "minor_ticks",
            "minor.ticks",
            "cap",
            "position",
            "order",
        }
        cleaned = {key.replace(".", "_"): value for key, value in params.items() if key in allowed}
        return factory(**cleaned)
    if name == "axis_logticks":
        allowed = {
            "long",
            "mid",
            "short",
            "negative_small",
            "negative.small",
            "expanded",
            "cap",
            "preserve",
            "order",
        }
        cleaned = {key.replace(".", "_"): value for key, value in params.items() if key in allowed}
        return guide_axis_logticks(**cleaned)
    if name in ("axis_stack", "stacked_axis"):

        def _sub(item: Any) -> Any:
            if isinstance(item, (str, AxisGuide)):
                return item
            return axis_guide_from_component(item) or "axis"

        items = [_sub(params.get("first", "axis"))]
        for key in ("guides", "axes", "rest"):
            value = params.get(key)
            if value:
                items.extend(_sub(item) for item in value)
        if "guide" in params:
            items.append(_sub(params["guide"]))
        return guide_axis_stack(
            *items,
            title=params.get("title", AUTO),
            spacing=params.get("spacing"),
            angle=params.get("angle"),
        )
    raise ValueError(
        f"未知的轴 guide {name!r}；已实现：axis / axis_logticks / axis_stack / axis_theta / none"
    )


def guide_for(build: Any, aesthetic: str) -> AxisGuide | None:
    """该美学的轴 guide：`guides()` 优先，其次标度的 `guide=`，都没有用默认轴。"""
    guides = getattr(build, "guides", None) or {}
    for key, component in guides.items():
        owner = getattr(component, "aesthetic", None)
        if owner == aesthetic or (key == aesthetic and owner in (None, aesthetic)):
            return axis_guide_from_component(component)
    scales = getattr(build, "scales", None)
    scale = scales.scale(aesthetic) if scales is not None else None
    params = getattr(scale, "params", None) or {}
    component = params.get("guide")
    if component is not None:
        return axis_guide_from_component(component)
    return None


# ---------------------------------------------------------------------------
# 刻度：位置 + 档位 + 标签
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AxisMark:
    """一根刻度线：位置（0..1）、长度（cm）、样式名（`major` / `minor` …）。"""

    position: float
    length_cm: float
    style: str = "major"


@dataclass(frozen=True, slots=True)
class AxisLabel:
    """一个刻度标签：位置（0..1）+ 文本。"""

    position: float
    text: str


@dataclass(frozen=True, slots=True)
class AxisGuideTicks:
    """一条轴 guide 的刻度与标签。"""

    side: str
    labels: tuple[AxisLabel, ...]
    marks: tuple[AxisMark, ...]
    angle: float = 0.0
    check_overlap: bool = False
    n_dodge: int = 1
    #: 轴带留给刻度的长度；`guide_axis_logticks` 即使范围内没有 long 刻度，
    #: 轴带也按 `long` 留位（R `measure_grobs()` 用 `elements$major_length`）。
    longest: float | None = None
    #: 子 guide 的叠放（`guide_axis_stack`）；空表示单层。
    children: tuple[AxisGuideTicks, ...] = field(default_factory=tuple)
    #: 标签锚点（`hjust` / `vjust`）；`None` = 由 `angle` + 方位推（R 的
    #: `label_angle_heuristic()`）。guide 的 `angle` 是 waiver 时 R **原样保留**
    #: 主题元素自己的 `hjust` / `vjust`——`axis.text.r` 就是靠这条居中
    #: （`hjust = 0.5`），与 `axis.text.y` 的 `hjust = 1` 不同（SIL-844）。
    hjust: float | None = None
    vjust: float | None = None


def _normal_angle(value: float | None) -> float:
    return float(value or 0.0) % 360.0


def _text_element(theme: ResolvedTheme, side: str) -> Any:
    horizontal = side in ("bottom", "top")
    name = "axis.text.x" if horizontal else "axis.text.y"
    suffix = (
        ".bottom"
        if side == "bottom"
        else ".top"
        if side == "top"
        else ".left"
        if side == "left"
        else ".right"
    )
    element = theme.get(name + suffix)
    if element is None:
        element = theme.get(name)
    return element


def _major_length(theme: ResolvedTheme, side: str) -> float:
    """主轴刻度长（cm）；`axis.ticks.*` 是 `element_blank()` 时为 0。

    R 的 `GuideAxis$measure_grobs()` 量的是刻度 grob 的长度：`element_blank()`
    的 zeroGrob 长度是 0，所以 `theme_minimal()` 的 axis-b = 文字高 + **4.95pt**
    margin，不含 `axis.ticks.length`（2.75pt）。旧 `axis_extent()` 在这里两项各错
    一次（算进 2.75pt 刻度、用了 base 的 2.2pt margin），和 R 只差 0.02pt 纯属
    巧合；见 docs/notes/guide.md §6。
    """
    from ggcore.axis import tick_length_cm, tick_paint

    if tick_paint(theme, side) is None:
        return 0.0
    return tick_length_cm(theme, side)


def _minor_length(theme: ResolvedTheme, side: str) -> float:
    """`axis.minor.ticks.length.<aes>.<side>`：Rel(0.75) 相对主轴刻度长。"""
    horizontal = side in ("bottom", "top")
    axis = "x" if horizontal else "y"
    name = f"axis.minor.ticks.length.{axis}.{side}"
    value = theme.get(name)
    if value is None:
        value = theme.get(f"axis.minor.ticks.length.{axis}")
    from ggcore.axis import tick_length_cm

    mult = 0.75
    # 基准是 `axis.ticks.length`，与主轴刻度是否 blank 无关（R 的
    # `elements$minor_length` 是 Rel(0.75)，不读 `axis.ticks` 的可见性）。
    if hasattr(value, "mult"):
        return float(value.mult) * tick_length_cm(theme, side)
    if value is None:
        return mult * tick_length_cm(theme, side)
    from ggcore.axis import margin_sides_cm  # noqa: F401  (保持与主题同一换算路径)
    from ggcore.units import UnitContext, convert_height, convert_width

    convert = convert_height if horizontal else convert_width
    try:
        return float(np.asarray(convert(value, "cm", ctx=UnitContext())).sum())
    except Exception:  # pragma: no cover - 非法单位由主题层报错
        return mult * _major_length(theme, side)


def minor_breaks_log(
    limits: Sequence[float],
    smallest: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """`scales::minor_breaks_log()` 的移植：返回 `(ticks, detail)`。

    `detail` 是每根刻度的档位：10 = long（每十进位），5 = mid（5×10^n），
    1 = short（其余）。
    """
    values = np.asarray(tuple(limits), dtype=np.float64)
    has_negatives = bool(np.any(values <= 0))
    if has_negatives:
        large = float(np.max(np.abs(values)))
        small = smallest if smallest is not None else min(1.0, large) * 0.1
        values = np.sort(np.concatenate([[small * 10.0], [large]]))
    low = float(np.min(values))
    high = float(np.max(values))
    start = math.floor(math.log10(low)) - 1
    end = math.ceil(math.log10(high)) + 1
    span = abs(end - start)
    detail = 1 if span < 8 else 5 if span < 15 else 10
    ladder = np.power(10.0, np.arange(start, end + 1, dtype=np.float64))
    tens = ladder if detail in (10, 5, 1) else np.array([])
    fives = 5.0 * ladder if detail in (5, 1) else np.array([])
    ones = np.array([])
    if detail == 1:
        ones = (np.arange(1, 10, dtype=np.float64)[:, None] * ladder[None, :]).reshape(-1)
        ones = np.setdiff1d(ones, np.concatenate([tens, fives]), assume_unique=False)
    if has_negatives:
        small = smallest if smallest is not None else min(1.0, float(np.max(np.abs(limits)))) * 0.1
        tens = tens[tens >= small]
        tens = np.concatenate([tens, -tens, [0.0]])
        fives = fives[fives >= small]
        fives = np.concatenate([fives, -fives])
        ones = ones[ones >= small]
        ones = np.concatenate([ones, -ones])
    ticks = np.concatenate([tens, fives, ones])
    detail_array = np.concatenate(
        [
            np.full(tens.size, 10, dtype=np.int32),
            np.full(fives.size, 5, dtype=np.int32),
            np.full(ones.size, 1, dtype=np.int32),
        ]
    )
    return ticks, detail_array


def _log_marks(
    scale: Any,
    params: Any,
    side: str,
    guide: AxisGuide,
    theme: ResolvedTheme,
) -> tuple[AxisMark, ...]:
    """`GuideAxisLogticks$extract_params()`：limits → 逆变换 → log 阶梯 → 变换回。"""
    if bool(getattr(scale, "discrete", False)):
        raise ValueError("guide_axis_logticks 不能用于离散标度")
    transform = getattr(scale, "transform_", None)
    if transform is None:
        raise ValueError("guide_axis_logticks 需要连续标度（找不到变换对象）")
    axis = params.screen_axis(side)
    ranges = getattr(params, "continuous_ranges", None) or {}
    if axis not in ranges:
        ranges = {"x": params.x_range, "y": params.y_range}
    low, high = (float(value) for value in ranges[axis])
    if high < low:
        low, high = high, low
    inverse = transform.inverse(np.array([low, high]))
    ticks, detail = minor_breaks_log(inverse, guide.negative_small)
    transformed, _ = transform.transform(ticks)
    if not guide.expanded:
        limits = tuple(float(value) for value in scale.limits())
        low, high = (min(limits), max(limits))
    major = _major_length(theme, side)
    lengths = {
        10: major * float(guide.long),
        5: major * float(guide.mid),
        1: major * float(guide.short),
    }
    styles = {10: "long", 5: "mid", 1: "short"}
    marks: list[AxisMark] = []
    for value, level in zip(transformed.tolist(), detail.tolist(), strict=True):
        if not (low - 1e-12 <= value <= high + 1e-12):
            continue
        position = params.position_of(axis, float(value))
        if not math.isfinite(position) or not (-1e-9 <= position <= 1.0 + 1e-9):
            continue
        marks.append(
            AxisMark(
                min(max(float(position), 0.0), 1.0),
                lengths[int(level)],
                styles[int(level)],
            )
        )
    return tuple(marks)


def axis_guide_ticks(
    scale: Any,
    params: Any,
    side: str,
    guide: AxisGuide | None,
    theme: ResolvedTheme,
    *,
    secondary: bool = False,
    base: AxisTicks | None = None,
) -> AxisGuideTicks:
    """一条轴的 guide 刻度：主断点标签 + 刻度线（含次刻度 / 对数三档）。"""
    guide = guide or AxisGuide()
    if guide.name == "none":
        # `guide_none()`：刻度与标签全去掉（标题由 scene 的标题阶段单独处理）。
        return AxisGuideTicks(side, (), ())
    if guide.is_stack and guide.guides:
        children = tuple(
            axis_guide_ticks(
                scale,
                params,
                side,
                child,
                theme,
                secondary=secondary,
                base=base,
            )
            for child in guide.guides
        )
        return AxisGuideTicks(side, (), (), children=children)
    ticks = base
    if ticks is None:
        from ggcore.axis import axis_ticks

        ticks = axis_ticks(scale, params, side, secondary=secondary)
    text = _text_element(theme, side)
    angle = _normal_angle(guide.angle if guide.angle is not None else getattr(text, "angle", None))
    # `label_angle_heuristic()`：`params$angle` 是 waiver 时元素原样返回（保留
    # `axis.text.*` 自己的 hjust / vjust）；给了 angle 才按角度重算。
    hjust = vjust = None
    if guide.angle is None and isinstance(text, ElementText):
        hjust = None if text.hjust is None else float(text.hjust)
        vjust = None if text.vjust is None else float(text.vjust)
    labels = tuple(
        AxisLabel(position, label)
        for position, label in zip(ticks.positions, ticks.labels, strict=True)
    )
    longest = None
    if guide.is_logticks and scale is not None:
        marks = _log_marks(scale, params, side, guide, theme)
        longest = _major_length(theme, side) * float(guide.long)
    else:
        major = _major_length(theme, side)
        marks_list = [AxisMark(position, major, "major") for position in ticks.positions]
        if guide.minor_ticks and scale is not None:
            minor = _minor_length(theme, side)
            major_positions = set(ticks.positions)
            for position in _minor_positions(scale, params, side):
                if any(abs(position - value) < 1e-12 for value in major_positions):
                    continue
                marks_list.append(AxisMark(position, minor, "minor"))
        marks = tuple(marks_list)
    return AxisGuideTicks(
        side,
        labels,
        marks,
        angle=angle,
        check_overlap=bool(guide.check_overlap),
        n_dodge=int(guide.n_dodge),
        longest=longest,
        hjust=hjust,
        vjust=vjust,
    )


def _theta_minor_tick_grobs(
    scale: Any,
    params: Any,
    theme: ResolvedTheme,
    box: CellBox,
    *,
    name: str,
) -> list[Any]:
    """`guide_axis_theta(minor.ticks=TRUE)`：沿圆周向外画 theta 次刻度。

    R 的 `GuideAxisTheta$build_ticks()` 用 `theta_tickmarks()`：位置在圆周
    （半径 1）上，沿径向伸出 `axis.minor.ticks.length`（缺省 0.75 × 主轴刻度长），
    样式取 `axis.minor.ticks`。只在 theta 标度有 minor breaks 时才有内容
    （连续标度；离散标度没有次刻度，与 R 一致）。
    """
    from ggcore.grobs import segments_grob
    from ggcore.viewport import gpar

    polar = getattr(params, "polar", None)
    if polar is None or scale is None:
        return []
    try:
        values = tuple(scale.minor_breaks())
    except Exception:  # pragma: no cover - 自定义标度的 minor_breaks 可能缺失
        return []
    numbers = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            numbers.append(number)
    if not numbers:
        return []
    style = _tick_line(theme, "bottom", AxisMark(0.0, 0.0, "minor"))
    if style is None:
        return []
    colour, lwd, lty = style
    length_cm = _minor_length(theme, "bottom")
    if length_cm <= 0.0:
        return []
    (x0, x1), _yrange = polar.bbox
    span = x1 - x0
    if span <= 0 or box.width_cm <= 0:
        return []
    # 半径 0.5 在 npc 里是 `0.5 / span`；再从圆周沿径向外推 length_cm。
    step = length_cm * span / box.width_cm
    angles = polar.theta_angle(np.asarray(numbers, dtype=np.float64))
    base_x, base_y = polar.point(angles, np.full(angles.shape, 0.5))
    tip_x, tip_y = polar.point(angles, np.full(angles.shape, 0.5 + step))
    xs0 = [box.x_cm + float(value) * box.width_cm for value in np.asarray(base_x)]
    ys0 = [box.y_cm + float(value) * box.height_cm for value in np.asarray(base_y)]
    xs1 = [box.x_cm + float(value) * box.width_cm for value in np.asarray(tip_x)]
    ys1 = [box.y_cm + float(value) * box.height_cm for value in np.asarray(tip_y)]
    return [
        segments_grob(
            xs0,
            ys0,
            xs1,
            ys1,
            default_units="cm",
            gp=gpar(col=colour, lwd=lwd, lty=lty),
            name=f"{name}.ticks",
        )
    ]


def _minor_positions(scale: Any, params: Any, side: str) -> tuple[float, ...]:
    """`scale$get_breaks_minor()` → npc（去掉与主断点重合的值）。"""
    try:
        values = tuple(scale.minor_breaks())
    except Exception:  # pragma: no cover - 自定义标度
        return ()
    axis = params.screen_axis(side)
    discrete = bool(getattr(scale, "discrete", False))
    out: list[float] = []
    for value in values:
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(number):
            continue
        position = params.position_of(axis, number)
        if not math.isfinite(position) or not (-1e-9 <= position <= 1.0 + 1e-9):
            continue
        out.append(min(max(float(position), 0.0), 1.0))
    del discrete
    return tuple(out)


# ---------------------------------------------------------------------------
# 尺寸
# ---------------------------------------------------------------------------


def _horizontal(side: str) -> bool:
    return side in ("bottom", "top")


#: 负刻度时锚点要换到对面那一侧（标签压进面板内侧）。
_OPPOSITE_SIDE = {"bottom": "top", "top": "bottom", "left": "right", "right": "left"}


def _label_box(
    labels: Sequence[AxisLabel],
    element: Any,
    side: str,
    angle: float,
    metrics: Any,
) -> tuple[float, float, float, float]:
    """标签盒的 `(w, h, margin_main, margin_cross)`，已含旋转。

    `margin_main` 是沿轴方向的 margin（横向轴的左右 / 竖向轴的上下），
    `margin_cross` 是垂直于轴方向的 margin。
    """
    from ggcore.axis import margin_sides_cm, text_block_cm

    size = float(getattr(element, "size", 0.0) or 0.0)
    family = getattr(element, "family", "") or ""
    mt, mr, mb, ml = margin_sides_cm(getattr(element, "margin", None))
    line = max(
        (text_block_cm(label.text, size, getattr(element, "lineheight", None)) for label in labels),
        default=0.0,
    )
    width = max(
        (text_width_cm(label.text, size, metrics, family) for label in labels),
        default=0.0,
    )
    radians = math.radians(angle % 360.0)
    cos = abs(math.cos(radians))
    sin = abs(math.sin(radians))
    if _horizontal(side):
        return width * cos + line * sin, width * sin + line * cos, ml + mr, mt + mb
    return width * cos + line * sin, width * sin + line * cos, mt + mb, ml + mr


def _max_tick_length(theme: ResolvedTheme, ticks: AxisGuideTicks) -> float:
    if ticks.children:
        return max(_max_tick_length(theme, child) for child in ticks.children)
    if ticks.longest is not None:
        return max(ticks.longest, max((mark.length_cm for mark in ticks.marks), default=0.0))
    return max((mark.length_cm for mark in ticks.marks), default=0.0)


def axis_line_range(guide: AxisGuide | None, ticks: AxisGuideTicks) -> tuple[float, float] | None:
    """`cap=` 的 axis.line 端点（npc 0..1）；`None` = 整条边（`cap="none"`）。

    R 的 `GuideAxis$extract_decor()`：轴线本来是 `(-Inf, Inf)`（整条边），
    `cap = "upper"` 把上端收到**最外一根刻度**、`"lower"` 收下端、`"both"` 两端
    都收。刻度取 guide 的 major key（`ticks.labels` 的位置，已是 npc），叠放的
    轴 guide 取所有子层的标签并集。
    """
    if guide is None:
        return None
    cap = str(getattr(guide, "cap", "none") or "none")
    if cap == "none":
        return None
    positions = [label.position for label in ticks.labels]
    for child in ticks.children:
        positions.extend(label.position for label in child.labels)
    if not positions:
        return None
    low, high = min(positions), max(positions)
    trim_low = cap in ("both", "lower", "bottom")
    trim_high = cap in ("both", "upper", "top")
    return (float(low) if trim_low else 0.0, float(high) if trim_high else 1.0)


def _guide_extent(
    theme: ResolvedTheme,
    ticks: AxisGuideTicks,
    side: str,
    metrics: Any,
    *,
    stack_gap: float,
) -> float:
    """单层 / 叠放的轴外向占位（cm）。"""
    if ticks.children:
        return sum(
            _guide_extent(theme, child, side, metrics, stack_gap=stack_gap)
            for child in ticks.children
        ) + stack_gap * (len(ticks.children) - 1)
    element = _text_element(theme, side)
    if isinstance(element, ElementBlank) or not isinstance(element, ElementText):
        # `axis.text.* = element_blank()` 只去掉**标签**：R 的 `draw_axis()` 仍把
        # 刻度线放进轴单元格，列宽 / 行高就是刻度长度（`axis-l` = 2.75pt）。
        # 早先整条轴返回空，极坐标的 r 轴连刻度都不见了。
        return _max_tick_length(theme, ticks)
    width, height, _margin_main, margin_cross = _label_box(
        ticks.labels, element, side, ticks.angle, metrics
    )
    rows = max(1, ticks.n_dodge) if ticks.labels else 0
    # 横向轴：轴高 = 刻度长 + 行数 × 标签盒高；竖向轴：轴宽 = 刻度长 + 行数 × 标签盒宽。
    box = (height if _horizontal(side) else width) + margin_cross
    return _max_tick_length(theme, ticks) + rows * box


def axis_guide_extent(
    theme: ResolvedTheme,
    ticks: AxisGuideTicks,
    guide: AxisGuide | None,
    *,
    side: str,
    metrics: Any = None,
) -> float:
    """一条轴 guide 的外向占位（cm）。`guide=None` 与默认 `guide_axis()` 相同。"""
    from ggcore.axis import tick_length_cm

    gap = tick_length_cm(theme, side)
    return _guide_extent(theme, ticks, side, metrics, stack_gap=gap)


# ---------------------------------------------------------------------------
# 绘制
# ---------------------------------------------------------------------------


def _label_stats(
    label: AxisLabel, element: Any, side: str, angle: float, metrics: Any
) -> tuple[float, float]:
    """单个标签旋转后的 `(沿轴长, 垂直轴长)`。"""
    from ggcore.axis import margin_sides_cm, text_block_cm

    size = float(getattr(element, "size", 0.0) or 0.0)
    family = getattr(element, "family", "") or ""
    mt, mr, mb, ml = margin_sides_cm(getattr(element, "margin", None))
    line = text_block_cm(label.text, size, getattr(element, "lineheight", None))
    width = text_width_cm(label.text, size, metrics, family)
    radians = math.radians(angle % 360.0)
    cos = abs(math.cos(radians))
    sin = abs(math.sin(radians))
    along = width * cos + line * sin
    cross = width * sin + line * cos
    if _horizontal(side):
        return along + ml + mr, cross + mt + mb
    # 竖轴的「沿轴长」是旋转后包围盒的**高度**：angle=0 时是行高，不是文字宽。
    return cross + mt + mb, along + ml + mr


def _overlap_order(n: int) -> list[int]:
    """R 的 `axis_label_priority()`：1, n, 中点递归 —— 保留首尾附近的标签。

    照 `axis_label_priority_between(x, y)` 的闭区间口径：`n = y - x + 1`，
    `mid = x - 1 + (n + 1) // 2`（1-based），换成 0-based 是
    `left + (right - left + 2) // 2`... 两端都算进跨度，`n <= 2` 时停。
    早先的迭代版在 `right - left` 为奇数时会把 `middle` 算成 `right`，
    `(5, 10)` 这种区间会自我入栈（`check_overlap` + 20 个断点直接挂死）。
    """
    if n <= 0:
        return []

    order: list[int] = [0, n - 1] if n > 1 else [0]

    def between(left: int, right: int) -> None:
        span = right - left + 1
        if span <= 2:
            return
        middle = left + (span + 1) // 2 - 1
        order.append(middle)
        between(left, middle)
        between(middle, right)

    between(0, n - 1)
    return order


def _without_labels(ticks: AxisGuideTicks) -> AxisGuideTicks:
    """把一条轴（含叠放子轴）的标签清空，只留刻度。"""
    children = tuple(_without_labels(child) for child in ticks.children)
    return replace(ticks, labels=(), children=children)


def _visible_labels(
    ticks: AxisGuideTicks, element: Any, metrics: Any, *, axis_length_cm: float
) -> list[tuple[AxisLabel, int]]:
    """按 `check.overlap` 过滤标签；返回 `(label, dodge 行号)`。

    `label.position` 是 npc（0..1），`_label_stats()` 给的是 cm，所以比较前先把
    标签长度折回 npc —— 少了这一步，20 个断点的
    `guide_axis(check_overlap=True)` 会把除第一个之外的全部丢掉（早先
    `axis-guides-check-overlap` 快照就是这么红的）。
    """
    labels = list(ticks.labels)
    if not labels:
        return []
    span = [
        (label, _label_stats(label, element, ticks.side, ticks.angle, metrics)) for label in labels
    ]
    if ticks.check_overlap:
        kept: list[tuple[float, float]] = []
        keep: set[int] = set()
        length = axis_length_cm if axis_length_cm > 1e-12 else 1.0
        for index in _overlap_order(len(span)):
            _label, (along, _cross) = span[index]
            half = (along / length) / 2.0
            low = _label.position - half
            high = _label.position + half
            if any(not (high <= a or low >= b) for a, b in kept):
                continue
            keep.add(index)
            kept.append((low, high))
        span = [item for index, item in enumerate(span) if index in keep]
    return [(label, index % ticks.n_dodge) for index, (label, _stats) in enumerate(span)]


def _tick_line(theme: ResolvedTheme, side: str, mark: AxisMark) -> tuple[str, float, float] | None:
    """刻度的 `(colour, lwd_pt, lty)`；`long/mid` 用主刻度，`short` / `minor` 用次刻度。"""
    horizontal = _horizontal(side)
    axis = "x" if horizontal else "y"
    if mark.style in ("minor", "short"):
        element = theme.get(f"axis.minor.ticks.{axis}.{side}")
    else:
        from ggcore.axis import tick_paint

        return tick_paint(theme, side)
    if not isinstance(element, ElementLine):
        return None
    from ggcore.axis import paint

    colour = paint(element.colour)
    if colour is None:
        return None
    width = float(element.linewidth or 0.0) * _POINT_PER_MM
    return colour, width, int(element.linetype or 1)


def axis_guide_grobs(
    theme: ResolvedTheme,
    ticks: AxisGuideTicks,
    box: CellBox,
    guide: AxisGuide | None,
    *,
    metrics: Any = None,
    name: str = "axis",
    draw_labels: bool = True,
) -> list[Any]:
    """一条轴的刻度线 + 标签（页面 cm 坐标，y 向上）。

    `draw_labels=False` 只去掉标签（刻度 / 轴线照画）：`facet_grid(axes = "all",
    axis.labels = "margins")` 的内面板走这条口径（R 的 `censor_labels()` 把
    内面板的 `draw_labels` 置空，轴带本身仍留刻度位置）。
    """
    from ggcore.axis import font_int, margin_sides_cm, paint
    from ggcore.grobs import segments_grob, text_grob
    from ggcore.viewport import gpar

    if not draw_labels:
        ticks = _without_labels(ticks)
    element = _text_element(theme, ticks.side)
    horizontal = _horizontal(ticks.side)
    side = ticks.side
    blank_text = isinstance(element, ElementBlank) or not isinstance(element, ElementText)
    size = 0.0 if blank_text else float(element.size or 0.0)
    gp = (
        {}
        if blank_text
        else {
            "col": paint(element.colour) or "black",
            "fontsize": size or 11.0,
            "fontfamily": element.family or "",
            "font": font_int(element.face),
            "lineheight": float(element.lineheight or 1.2),
        }
    )
    if blank_text:
        mt = mr = mb = ml = 0.0
    else:
        mt, mr, mb, ml = margin_sides_cm(element.margin)
    grobs: list[Any] = []
    # 叠放：每一层向外推 offset。
    offset = 0.0
    layers: list[tuple[AxisGuideTicks, float]] = []
    if ticks.children:
        from ggcore.axis import tick_length_cm

        gap = tick_length_cm(theme, side)
        for child in ticks.children:
            layers.append((child, offset))
            offset += _guide_extent(theme, child, side, metrics, stack_gap=gap) + gap
    else:
        layers = [(ticks, 0.0)]
    for layer_index, (layer, layer_offset) in enumerate(layers):
        visible = (
            []
            if blank_text
            else _visible_labels(
                layer,
                element,
                metrics,
                axis_length_cm=box.width_cm if horizontal else box.height_cm,
            )
        )
        max_tick = _max_tick_length(theme, layer)
        if blank_text:
            width = height = margin_cross = 0.0
        else:
            width, height, _margin_main, margin_cross = _label_box(
                layer.labels, element, side, layer.angle, metrics
            )
        row_size = (height if horizontal else width) + margin_cross
        hjust, vjust = _anchor(layer.angle, side)
        if layer.hjust is not None:
            hjust = layer.hjust
        if layer.vjust is not None:
            vjust = layer.vjust
        if max_tick < 0:
            # 负的 `axis.ticks.length` 把刻度画进面板内侧，标签也随之压在内侧：
            # 锚点换成对面那一侧的口径（R 的 `measure_grobs()` 用 spacer 吸收
            # 负刻度，轴线 / 刻度 / 文字保持在面板边界内的同一侧）。
            hjust, vjust = _anchor(layer.angle, _OPPOSITE_SIDE[side])
        # 刻度线：同一档（major / minor / long / mid / short）合成一个 segments
        # grob（R 的 `grobTree(major, minor)` 同构；逐个 mark 画会把面板内的
        # 线段拆成多个 grob，`tests/test_panel_grid.py` 的计数口径也会跟着变）。
        groups: dict[tuple[str, float, int], list[AxisMark]] = {}
        for mark in layer.marks:
            style = _tick_line(theme, side, mark)
            if style is None or mark.length_cm <= 0:
                continue
            colour, lwd, lty = style
            groups.setdefault((colour, lwd, lty), []).append(mark)
        for group_index, ((colour, lwd, lty), marks) in enumerate(groups.items()):
            xs: list[float] = []
            ys: list[float] = []
            xs2: list[float] = []
            ys2: list[float] = []
            for mark in marks:
                length = mark.length_cm
                if horizontal:
                    x = box.x_cm + mark.position * box.width_cm
                    if side == "top":
                        edge = box.y_cm + box.height_cm + layer_offset
                        inner = edge + length
                    else:
                        edge = box.y_cm - layer_offset
                        inner = edge - length
                    xs.extend([x, x])
                    ys.extend([edge, edge])
                    xs2.extend([x, x])
                    ys2.extend([inner, inner])
                else:
                    y = box.y_cm + mark.position * box.height_cm
                    if side == "right":
                        edge = box.right + layer_offset
                        inner = edge + length
                    else:
                        edge = box.x_cm - layer_offset
                        inner = edge - length
                    xs.extend([edge, edge])
                    ys.extend([y, y])
                    xs2.extend([inner, inner])
                    ys2.extend([y, y])
            grobs.append(
                segments_grob(
                    xs,
                    ys,
                    xs2,
                    ys2,
                    default_units="cm",
                    gp=gpar(col=colour, lwd=lwd, lty=lty),
                    name=f"{name}.ticks-{layer_index}-{group_index}",
                )
            )
        # 标签：n.dodge 分行；第一行贴刻度，其余向外推一行（负刻度时向面板内侧推）。
        inside = max_tick < 0
        sign = 1.0 if inside else -1.0
        # guide 的 `angle` 是 waiver 时，R 的 `label_angle_heuristic()` 原样返回
        # 主题元素——标签于是走 `titleGrob()` 的 margin 盒（宽 = margin_l + 文字 +
        # margin_r），锚点由元素自己的 hjust / vjust 决定。水平 / 垂直居中
        # （`axis.text.r` 的 hjust = 0.5）比「贴边」多退半个文字宽，差这半格整条
        # r 轴会偏 4.9pt（SIL-844）。只剩 0 / 180 度：旋转标签的 just 还要过
        # `rotate_just()`，那条路径仍走旧的贴边口径。
        precise = (layer.hjust is not None or layer.vjust is not None) and (
            abs(layer.angle % 180.0) < 1e-9
        )
        for label, dodge in visible:
            offset_out = max_tick + layer_offset
            if precise:
                from ggcore.axis import text_block_cm

                own_w = text_width_cm(label.text, size, metrics, element.family or "")
                own_h = text_block_cm(label.text, size, getattr(element, "lineheight", None))
                if horizontal:
                    x = box.x_cm + label.position * box.width_cm
                    if side == "top":
                        y = box.y_cm + box.height_cm + offset_out + mb + vjust * own_h
                    else:
                        y = box.y_cm - offset_out - mt - (1.0 - vjust) * own_h
                else:
                    y = box.y_cm + label.position * box.height_cm
                    if side == "right":
                        x = box.right + offset_out + hjust * (own_w + ml) + ml * (1.0 - hjust)
                    else:
                        x = box.x_cm - offset_out - (1.0 - hjust) * (own_w + mr) - mr * hjust
                if dodge:
                    if horizontal:
                        y += sign * dodge * row_size
                    else:
                        x += sign * dodge * row_size
            elif horizontal:
                x = box.x_cm + label.position * box.width_cm
                if side == "top":
                    y = box.y_cm + box.height_cm + offset_out - sign * mb - sign * dodge * row_size
                else:
                    y = box.y_cm - offset_out + sign * mt + sign * dodge * row_size
            else:
                y = box.y_cm + label.position * box.height_cm
                if side == "right":
                    x = box.right + offset_out - sign * ml - sign * dodge * row_size
                else:
                    x = box.x_cm - offset_out + sign * mr + sign * dodge * row_size
            grobs.append(
                text_grob(
                    label.text,
                    x,
                    y,
                    hjust=hjust,
                    vjust=vjust,
                    rot=layer.angle,
                    default_units="cm",
                    gp=gpar(**gp),
                    name=f"{name}.text-{layer_index}",
                )
            )
    return grobs


def axis_line_grobs(
    theme: ResolvedTheme,
    box: CellBox,
    *,
    name: str = "axis-line",
    ranges: Mapping[str, tuple[float, float] | None] | None = None,
    sides: Sequence[str] = ("bottom", "left"),
) -> list[Any]:
    """`axis.line.x` / `axis.line.y`；`ranges` 给 `cap=` 裁出的端点（npc 0..1）。

    R 的轴线是 guide 的 decor（`GuideAxis$extract_decor()`），`cap=` 会把它收到
    最外一根刻度（`upper` / `lower` / `both`）；`None` = 整条边。`sides` 决定画哪
    几条：主轴总有 bottom / left，有次轴时再加 top / right（R 里次轴自己的 guide
    也带 decor）。

    搬到这里（原先是 `geom/scene.py` 的私有函数）是因为 `draw_axis()` 也要画轴线：
    两处走同一份实现，`caps` 的口径才不会各改一份。
    """
    from ggcore.axis import paint
    from ggcore.grobs import segments_grob
    from ggcore.viewport import gpar

    ranges = ranges or {}
    elements = {
        "bottom": ("axis.line.x.bottom", "axis.line.x"),
        "top": ("axis.line.x.top", "axis.line.x"),
        "left": ("axis.line.y.left", "axis.line.y"),
        "right": ("axis.line.y.right", "axis.line.y"),
    }
    grobs: list[Any] = []
    for side in sides:
        element = None
        for element_name in elements[side]:
            element = theme.get(element_name)
            if element is not None:
                break
        colour = paint(getattr(element, "colour", None))
        if colour is None:
            continue
        lwd = float(getattr(element, "linewidth", None) or 0.0) * _POINT_PER_MM
        low, high = ranges.get(side) or (0.0, 1.0)
        if high - low <= 1e-12:
            continue
        if side == "bottom":
            x0, y0 = box.x_cm + low * box.width_cm, box.y_cm
            x1, y1 = box.x_cm + high * box.width_cm, box.y_cm
        elif side == "top":
            x0, y0 = box.x_cm + low * box.width_cm, box.y_cm + box.height_cm
            x1, y1 = box.x_cm + high * box.width_cm, box.y_cm + box.height_cm
        elif side == "left":
            x0, y0 = box.x_cm, box.y_cm + low * box.height_cm
            x1, y1 = box.x_cm, box.y_cm + high * box.height_cm
        else:
            x0, y0 = box.right, box.y_cm + low * box.height_cm
            x1, y1 = box.right, box.y_cm + high * box.height_cm
        grobs.append(
            segments_grob(
                x0,
                y0,
                x1,
                y1,
                default_units="cm",
                gp=gpar(col=colour, lwd=lwd),
                name=f"{name}-{side}",
            )
        )
    return grobs


def draw_axis(
    theme: ResolvedTheme,
    side: str,
    positions: Sequence[float],
    labels: Sequence[str],
    *,
    box: CellBox,
    check_overlap: bool = False,
    angle: float | None = None,
    n_dodge: int = 1,
    metrics: Any = None,
    name: str = "axis",
) -> list[Any]:
    """R 的 `draw_axis()`：不经过 ggplot 版面，把一条轴画进 `box`。

    `positions` 是 npc（0..1，R 里 `draw_axis(seq_len(n) / (n + 1), ...)` 直接就是
    分数）；`labels` 与之一一对应。返回「轴线 + 刻度 + 标签」的 grob 列表，坐标是
    `box` 所在视口的 cm（y 向上），可以直接放进 gtable 单元格或 `gTree`。

    与 `axis_guide_ticks()` 的区别只在输入：那边从 scale / params 推出断点，
    这边收现成的断点与标签——R 的 `draw_axis()` 就是给 `coord_map()` 这类
    「没有 ggplot_build 产物」的场景用的，也是上游 `test_draw_axis()` 的快照入口。

    方位口径照 R 的 `GuideAxis$assemble_drawing()`：`side` 描述的是**这条轴贴着
    哪条边、刻度朝哪边伸**，不是「画在单元格的哪个角」。`side="top"` 的轴贴单元格
    的**下**沿、刻度向上伸（真实版式里它的单元格就在面板上方，下沿即面板边界），
    `"bottom"` 反之；`"left"` / `"right"` 同理。所以这里把盒子在垂直于轴的尺寸上
    压成 0、挪到对应的那条边，再交给同一个 :func:`axis_guide_grobs`。
    """
    guides = AxisGuide(check_overlap=bool(check_overlap), n_dodge=int(n_dodge))
    element = _text_element(theme, side)
    resolved_angle = _normal_angle(angle if angle is not None else getattr(element, "angle", None))
    major = _major_length(theme, side)
    ticks = AxisGuideTicks(
        side,
        tuple(
            AxisLabel(float(position), str(label))
            for position, label in zip(positions, labels, strict=True)
        ),
        tuple(AxisMark(float(position), major, "major") for position in positions),
        angle=resolved_angle,
        check_overlap=bool(check_overlap),
        n_dodge=int(n_dodge),
    )
    if side in ("top", "bottom"):
        # 沿轴方向的尺寸（宽）留着：标签位置与 check.overlap 都要用它。
        edge = box.y_cm if side == "top" else box.y_cm + box.height_cm
        anchor = CellBox(box.t, box.l, box.b, box.r, box.x_cm, edge, box.width_cm, 0.0)
    else:
        edge = box.right if side == "left" else box.x_cm
        anchor = CellBox(box.t, box.l, box.b, box.r, edge, box.y_cm, 0.0, box.height_cm)
    grobs = axis_line_grobs(theme, anchor, name=f"{name}-line", sides=(side,))
    grobs.extend(
        axis_guide_grobs(
            theme,
            ticks,
            anchor,
            guides,
            metrics=metrics,
            name=name,
        )
    )
    return grobs


def _anchor(angle: float, side: str) -> tuple[float, float]:
    """R 的 `label_angle_heuristic()`：按角度与方位给出 `(hjust, vjust)`。

    `cosine = sign(round(cos a)) / 2 + 0.5`、`sine = sign(round(sin a)) / 2 + 0.5`：

    | 方位 | hjust | vjust |
    | --- | --- | --- |
    | bottom | `sine` | `cosine` |
    | top | `1 - sine` | `1 - cosine` |
    | left | `cosine` | `1 - sine` |
    | right | `1 - cosine` | `sine` |
    """
    radians = math.radians(angle % 360.0)

    def sign(value: float) -> float:
        rounded = round(value, 3)
        return 0.0 if rounded == 0 else (1.0 if rounded > 0 else -1.0)

    cosine = sign(math.cos(radians)) / 2.0 + 0.5
    sine = sign(math.sin(radians)) / 2.0 + 0.5
    if side == "top":
        return 1.0 - sine, 1.0 - cosine
    if side == "left":
        return cosine, 1.0 - sine
    if side == "right":
        return 1.0 - cosine, sine
    return sine, cosine


# ---------------------------------------------------------------------------
# 极坐标 theta 轴
# ---------------------------------------------------------------------------


#: theta 标签角度的量化位数：`90 < angle < 270` 的翻转判定不能被 libm 末位噪声
#: 翻档（SIL-824 返工）。1e-6 度远小于任何渲染端的可见分辨率。
ANGLE_DECIMALS = 6


def polar_axis_grobs(
    scale: Any,
    params: Any,
    theme: ResolvedTheme,
    box: CellBox,
    guide: AxisGuide | None,
    *,
    metrics: Any = None,
    name: str = "axis-theta",
    secondary: bool = False,
    stack_offset_cm: float = 0.0,
) -> list[Any]:
    """极坐标 theta 轴：轴线 + 刻度 + 标签（`GuideAxisTheta`）。

    几何照 4.0.3 的 `GuideAxisTheta$transform()` / `build_labels()`：

    - key 落在 `coord_radial()` 的**径向端点**：主轴 `inner_radius[1]`（满圆 0.4）、
      `theta.sec` 是 `inner_radius[0]`（内半径，full circle 时 0.2）——上游把
      key 的另一个美学设成 `±Inf`，再经 `r_rescale()` 夹到 donut 的两端；
    - `theta.sec` 的 key 角度再加 `π`（`if (position == 'theta.sec') key$theta + pi`）；
    - 标签从 key 沿半径外推 `offset = max(0, 主轴刻度长, 次刻度长) + max(文字 margin)`，
      `guide_axis_stack()` 叠放时再加 `spacing + 上一层 offset`（`stack_offset_cm`）；
    - 标签旋转：`guide$angle` 是 waiver 时**不随 theta 转**（用 `axis.text.theta$angle`）；
      显式给定时 `flip_text_angle(angle - rad2deg(theta))`；
      `hjust = 0.5 - sin(θ + rad)/2`、`vjust = 0.5 - cos(θ + rad)/2`；
    - 轴线是沿 key 半径的弧（`axis.line.theta`），`cap` 把两端各延长一个刻度长。
    """
    from ggcore.axis import (
        font_int,
        margin_sides_cm,
        paint,
        polar_theta_ticks,
        tick_length_cm,
    )
    from ggcore.grobs import polyline_grob, segments_grob, text_grob
    from ggcore.viewport import gpar

    polar = getattr(params, "polar", None)
    if polar is None or scale is None or box.width_cm <= 0:
        return []
    entries = polar_theta_ticks(scale, params)
    if not entries:
        return []
    guide = guide or AxisGuide(name="axis_theta")
    if getattr(guide, "theme", None) is not None:
        # `guides(theta.sec = guide_axis_theta(theme = theme(...)))`：只改这一条
        # theta 轴的 `axis.line.theta` / `axis.text.theta`（上游 `GuideAxis$setup_elements`
        # 把 guide 自己的 theme 合并到用户主题上再取元素名）。
        from ggcore.guide import guide_theme

        theme = guide_theme(theme, guide)
    element = theme.get("axis.text.theta") or _text_element(theme, "bottom")
    grobs: list[Any] = []

    # `coord_radial()` 的 key 落在径向端点（主轴 `inner_radius[1]`、`theta.sec` 是
    # `inner_radius[0]`）；`coord_polar()` 的历史口径是网格外圈 0.45（SIL-839 之前
    # 就按 0.45 画，`matrix-report-facet-polar-grey` 已经在这条口径上转绿，不动它）。
    if polar.radial:
        key_radius = float(polar.inner_radius[0] if secondary else polar.inner_radius[1])
    else:
        key_radius = 0.45
    thetas = np.asarray([entry[3] for entry in entries], dtype=np.float64)
    # `theta.sec` 的 key 与主轴**同角**、只是落在内半径上；`+π` 只参与
    # 「沿半径的方向」（刻度朝内、标签压进弧内、文字角度反向），不改位置
    # （上游 `GuideAxisTheta$transform()` 先算 x/y，之后才 `key$theta + pi`）。
    directions = thetas + math.pi if secondary else thetas

    tick_cm = tick_length_cm(theme, "bottom")
    text_margin = 0.0
    if isinstance(element, ElementText):
        margins = margin_sides_cm(getattr(element, "margin", None))
        text_margin = max(margins) if margins else 0.0
    offset = (max(0.0, tick_cm) + text_margin + stack_offset_cm) / box.width_cm

    # 轴线 / 刻度只在 `coord_radial()` 上补：`coord_polar()` 的 `render_fg()`
    # 只画 theta 标签（`matrix-report-facet-polar-grey` 等 7 条已纳管 case 就是
    # 在那条口径上转绿的，别顺手改它）。
    line_element = theme.get("axis.line.theta") if polar.radial else None
    line_gp = _line_gp(line_element) if line_element is not None else None
    if line_gp is not None and len(thetas) > 1:
        angles = _arc_angles(thetas, cap=guide.cap, tick=tick_cm / box.width_cm)
        xs, ys = polar.point(angles, np.full(angles.shape, key_radius))
        grobs.append(
            polyline_grob(
                [box.x_cm + float(value) * box.width_cm for value in np.asarray(xs)],
                [box.y_cm + float(value) * box.height_cm for value in np.asarray(ys)],
                default_units="cm",
                gp=line_gp,
                name=f"{name}.line",
            )
        )

    # 刻度：从 key 沿半径向外（`theta_tickmarks()` 的 `length` 从 0 到 length）。
    tick_element = theme.get("axis.ticks.theta") or theme.get("axis.ticks")
    tick_gp = _line_gp(tick_element) if polar.radial and tick_element is not None else None
    if tick_gp is not None and tick_cm > 0:
        step = tick_cm / box.width_cm
        x0, y0 = polar.point(thetas, np.full(thetas.shape, key_radius))
        # 刻度从 key 沿 `directions` 伸出去：与标签同理，方向在 npc 空间里加
        # `sin/cos`，不能直接换角度再取点（那会横跨圆心连成弦）。
        x1 = np.asarray(x0, dtype=np.float64) + np.sin(directions) * step
        y1 = np.asarray(y0, dtype=np.float64) + np.cos(directions) * step
        grobs.append(
            segments_grob(
                [box.x_cm + float(value) * box.width_cm for value in np.asarray(x0)],
                [box.y_cm + float(value) * box.height_cm for value in np.asarray(y0)],
                [box.x_cm + float(value) * box.width_cm for value in np.asarray(x1)],
                [box.y_cm + float(value) * box.height_cm for value in np.asarray(y1)],
                default_units="cm",
                gp=tick_gp,
                name=f"{name}.ticks",
            )
        )

    if guide.minor_ticks:
        grobs.extend(_theta_minor_tick_grobs(scale, params, theme, box, name=f"{name}.minor"))

    if not isinstance(element, ElementText) or isinstance(element, ElementBlank):
        return grobs

    base_angle = None if guide.angle is None else float(guide.angle)
    element_angle = float(getattr(element, "angle", 0.0) or 0.0)
    gp = {
        "col": paint(element.colour) or "black",
        "fontsize": float(element.size or 0.0) or 11.0,
        "fontfamily": element.family or "",
        "font": font_int(element.face),
        "lineheight": float(element.lineheight or 1.2),
    }
    # `coord_polar()` 的标签历史口径就是网格外圈 0.45（不加 offset），保持不动；
    # 只有 `coord_radial()` 走 R 的「key + offset」——offset 在 **npc 空间**里沿
    # `sin/cos(direction)` 加（上游 `build_labels()` 的 `xoffset` / `yoffset`），
    # 部分弧的 bbox 非正方形时这与「半径 + offset」不等价。
    key_x, key_y = polar.point(thetas, np.full(thetas.shape, key_radius))
    label_radius = key_radius + offset if polar.radial else key_radius
    xs, ys = polar.point(thetas, np.full(thetas.shape, label_radius))
    for index, theta in enumerate(directions):
        position_x = float(xs[index])
        position_y = float(ys[index])
        if polar.radial:
            position_x = float(key_x[index]) + math.sin(float(theta)) * offset
            position_y = float(key_y[index]) + math.cos(float(theta)) * offset
        if base_angle is None:
            # waiver：不随 theta 转，直接用 `axis.text.theta$angle`（R 同）。
            angle = element_angle
        else:
            angle = round((base_angle - math.degrees(float(theta))) % 360.0, ANGLE_DECIMALS)
            if 90.0 < angle < 270.0:
                angle += 180.0
        radians = math.radians(angle)
        hjust = 0.5 - math.sin(float(theta) + radians) / 2.0
        vjust = 0.5 - math.cos(float(theta) + radians) / 2.0
        grobs.append(
            text_grob(
                entries[index][2],
                box.x_cm + position_x * box.width_cm,
                box.y_cm + position_y * box.height_cm,
                hjust=hjust,
                vjust=vjust,
                rot=angle,
                default_units="cm",
                gp=gpar(**gp),
                name=f"{name}.text-{index}",
            )
        )
    return grobs


def _line_gp(element: Any) -> Any:
    """`axis.line.*` / `axis.ticks.*` → gpar；blank 或没有颜色时返回 None。"""
    from ggcore.axis import paint
    from ggcore.viewport import gpar

    if element is None or isinstance(element, ElementBlank):
        return None
    colour = paint(getattr(element, "colour", None))
    if colour is None:
        return None
    return gpar(
        col=colour,
        lwd=_POINT_PER_MM * float(getattr(element, "linewidth", 0.0) or 0.0),
        lty=getattr(element, "linetype", None) or 1,
        lineend="round",
        linejoin="round",
    )


def _arc_angles(thetas: np.ndarray, *, cap: str, tick: float) -> np.ndarray:
    """轴线采样角度：覆盖 key 的范围；`cap` 在两端各延长一个刻度长（弧度）。"""
    ordered = np.sort(np.mod(np.asarray(thetas, dtype=np.float64), 2.0 * math.pi))
    span = float(ordered[-1] - ordered[0])
    full = span >= 2.0 * math.pi - 1e-6
    start = float(ordered[0])
    stop = float(ordered[-1])
    if not full and cap not in (None, "none"):
        # 端帽沿圆周延长：角度步长 ≈ 刻度长 / 半径，这里按 0.05 npc 的半径折算。
        step = tick / max(0.05, 0.5)
        if cap in ("both", "upper", "top"):
            stop += step
        if cap in ("both", "lower", "bottom"):
            start -= step
    return np.linspace(start, stop, 100)

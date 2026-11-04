"""图例（guide，M1-11 / M2-2）：`GuideLegend` / `GuideColourbar` / `GuideCustom`。

对齐 ggplot2 4.0.3 的 guide 体系（`R/guide-legend.R`、`R/guides-.R`、
`R/guide-custom.R`）：

- **一个美学只有一个 guide**：同一美学在 `plot.guides` 里最多一个条目，
  后加的替换先加的（`plot.guides` 是 dict，与 `plot.scales` 同一口径）；
  `guides(...)`（`ggcore.plot`）是批量入口，值可以是字符串 / 注册表组件 /
  `Guide` 实现；
- **合并规则**：`Guides$merge()` 按 `order` + `hashables = (title, key$.label, name)`
  分组，组内 `Reduce(Guide$merge)`；`params$key <- cbind(key)` 把两个美学的键值
  并到同一行，`override.aes` 先到先得，绘制按图层顺序叠加；
- `show_legend=False`（图层参数）或 `guide="none"` → 不出现；
- 连续 colour / fill 默认 `GuideColourbar`，其余默认 `GuideLegend`；
- 方位：`position`（right / left / top / bottom / inside）逐 guide 可覆盖
  `legend.position`；inside 用 `legend.position.inside` + `legend.justification.inside`；
- 扩展点：运行期 `Guide.train()` / `transform()` / `geom()` / `gengrob()` /
  `draw_keys()`；注册入口是 M2-9 的 `registry.register_guide()` +
  `components.Guide.build_guide()`（见 `docs/notes/extension.md`）。

key 的图形**复用 `Geom.draw()`**：每个几何一个 key grob，不另写形状代码
（`docs/notes/guide.md` 的「key 数据模板」）。

几何尺寸照 R 的 `guide_gengrob.legend` / `measure_grobs`：

```
竖向（legend.position = right / left）
  [legend.margin] [标题行（top）] [key 宽] [间距+标签宽] [legend.margin]
  行：每个 key 一行（key 高；竖向没有行间距）
横向（top / bottom）
  [legend.margin] [标题列（left）] [key 宽] [间距+标签宽] (间距 [key][标签])… [legend.margin]
  行：标题 / key 行
```

`LegendLayout.col_widths_cm` / `row_heights_cm` 是逐列 / 逐行的分解（与 R 的
`guide$widths` / `heights` 对拍），`LegendBoxLayout` 把同一方位的图例排成
`gtable_col` / `gtable_row`。

M2-S2（SIL-739）补齐：`guide_colourbar()` 的全量参数（display / nbin /
draw.ulim / draw.llim / ticks.colour / frame.colour / title.position / alpha）、
`guide_bins()` / `guide_coloursteps()`；轴 guide（`guide_axis` /
`guide_axis_logticks` / `guide_axis_stack` / `guide_axis_theta`）在
:mod:`ggcore.axis_guide`。
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import MISSING, dataclass, field, fields, replace
from types import MappingProxyType
from typing import Any

import numpy as np

from ggcore.axis import (
    font_int,
    margin_sides_cm,
    paint,
    text_line_cm,
    text_width_cm,
)
from ggcore.build import STAT_DEFAULT_AES, LayerBuild, PlotBuild
from ggcore.data import Column, ColumnTable
from ggcore.eval import parse_aes
from ggcore.grobs import NullGrob, ZeroGrob, rect_grob, text_grob
from ggcore.legend_draw import KeyGlyph, default_key_glyph, draw_key, key_glyph_for
from ggcore.theme import (
    ElementBlank,
    ElementLine,
    ElementRect,
    ElementText,
    ResolvedTheme,
    merge_theme,
    resolve_theme,
)
from ggcore.units import UnitContext, convert_height, convert_width, unit
from ggcore.viewport import NA, gpar, viewport

__all__ = [
    "AUTO",
    "GUIDE_AESTHETICS",
    "BinnedKeys",
    "Guide",
    "GuideBins",
    "GuideBuild",
    "GuideColourbar",
    "GuideColoursteps",
    "GuideCustom",
    "GuideError",
    "GuideKey",
    "GuideLegend",
    "GuideNone",
    "LegendBoxLayout",
    "LegendKeyCell",
    "LegendLayout",
    "build_guides",
    "custom_grob",
    "guide_bins",
    "guide_colorbar",
    "guide_colourbar",
    "guide_coloursteps",
    "guide_custom",
    "guide_from_component",
    "guide_gengrob",
    "guide_geom",
    "guide_legend",
    "guide_merge",
    "guide_none",
    "guide_theme",
    "guide_train",
    "guide_transform",
    "legend_box_layout",
    "legend_grob",
    "legend_layout",
]

#: 会产出图例的非位置美学，顺序固定（决定默认的图例顺序）。
GUIDE_AESTHETICS = ("colour", "fill", "size", "shape", "alpha", "linetype", "linewidth")

#: `title=waiver()` 的对等物：没显式给标题时按标度 / 映射推。
AUTO: Any = object()

_POINTS_PER_INCH = 72.0
_CM_PER_INCH = 2.54

#: 色条相邻小矩形多铺的长度（1pt）。R 用 1×nbin 的位图，天然没有缝；我们只能是
#: 矩形，0.34pt 高的条各自抗锯齿时白底会从缝里透出来（整条偏白 ~30%）。
#: 多铺 1pt 让后画的条盖住缝，颜色仍按全量程取样。
_BAND_OVERLAP_CM = 1.0 / _POINTS_PER_INCH * _CM_PER_INCH


class GuideError(ValueError):
    """guide 参数无法表达，或请求了尚未实现的图例类型。"""


# ---------------------------------------------------------------------------
# guide 数据对象
# ---------------------------------------------------------------------------


class Guide:
    """所有 guide 的基类（`kind` 是 `"legend"` / `"colourbar"` / `"custom"` / `"none"`）。

    扩展点（M2-2，接口与 M2-9 的注册表扩展 API 对齐）：

    - :meth:`train` —— `guide$train()` 的对等物：从一个标度训练出
      :class:`GuideBuild`（键 + 标题 + 参与绘制的图层）；返回 ``None`` 表示
      这个 guide 不出图例；
    - :meth:`transform` —— `guide$transform()` 的键变换钩子（默认恒等）；
    - :meth:`geom` —— `guide$geom()` 的键几何钩子（默认用图层自己的
      ``Geom.draw()``，返回 ``None``）；
    - :meth:`gengrob` —— `guide$draw()` / `guide_gengrob()` 的对等物：把
      :class:`LegendLayout` 画成 grob 列表，返回空列表表示不画；
    - ``draw_keys(guide_build, theme, layout, *, metrics, name)`` —— M2-9 的
      key 区钩子：实现它时 `legend_grob()` 只画标题 / 背景，key 由它负责。

    自定义 guide 的注册方式是 `registry.register_guide(name, ComponentSubclass)`
    + 组件子类的 `build_guide()`（返回本类的实例）；运行期再覆盖需要的钩子。
    """

    kind: str = "legend"
    #: 该 guide 能作用的美学；`"any"` = 任意非位置美学（R 的 `available_aes`）。
    available_aes: tuple[str, ...] = ("any",)

    def position_of(self) -> str | None:
        return getattr(self, "position", None)

    def train(self, build: PlotBuild, aesthetic: str, scale: Any) -> GuideBuild | None:
        return _train_scale_guide(self, build, aesthetic, scale)

    def transform(self, keys: tuple[GuideKey, ...]) -> tuple[GuideKey, ...]:
        return keys

    def geom(self, layer: LayerBuild) -> Any | None:
        return None

    def gengrob(
        self,
        guide_build: GuideBuild,
        build: PlotBuild,
        theme: ResolvedTheme,
        layout: LegendLayout,
        *,
        metrics: Any = None,
        name: str = "guide",
    ) -> list[Any]:
        return legend_grob(guide_build, build, theme, layout, metrics=metrics, name=name)


@dataclass(frozen=True, slots=True)
class GuideLegend(Guide):
    """`guide_legend()`：离散键（colour / fill / size / shape / alpha）。"""

    title: Any = AUTO
    direction: str | None = None
    position: str | None = None
    nrow: int | None = None
    ncol: int | None = None
    byrow: bool | None = None
    override_aes: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    keywidth: Any = None
    keyheight: Any = None
    reverse: bool = False
    order: float = 0.0
    #: `legend.title.position` 的逐 guide 覆盖（top / bottom / left / right）。
    title_position: str | None = None
    title_hjust: float | None = None
    title_vjust: float | None = None
    #: 标题下方的一行说明文字（gg4py 扩展；R 4.0.3 的 guide_legend 只有 title）。
    subtitle: str | None = None
    #: `legend.text.position` 的逐 guide 覆盖（top / bottom / left / right）。
    label_position: str | None = None
    label_hjust: float | None = None
    label_vjust: float | None = None
    #: 逐 guide 的主题覆盖（R 4.0.3 的 `guide_legend(theme = theme(...))`）。
    theme: Any = None
    kind: str = "legend"

    def __post_init__(self) -> None:
        if self.direction not in (None, "vertical", "horizontal"):
            raise GuideError(
                f"guide_legend(direction=) 只能是 'vertical' / 'horizontal'，"
                f"收到 {self.direction!r}"
            )
        for name in ("nrow", "ncol"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, int) or value < 1):
                raise GuideError(f"guide_legend({name}=) 必须是正整数，收到 {value!r}")
        if self.nrow is not None and self.ncol is not None and self.nrow * self.ncol < 1:
            raise GuideError("guide_legend(nrow=, ncol=) 至少要有 1 个格位")
        for name in ("position", "title_position", "label_position"):
            value = getattr(self, name)
            if value not in (None, "top", "bottom", "left", "right", "inside"):
                raise GuideError(
                    f"guide_legend({name}=) 只能是 top / bottom / left / right / inside，"
                    f"收到 {value!r}"
                )
        for name in ("title_hjust", "title_vjust", "label_hjust", "label_vjust"):
            value = getattr(self, name)
            if value is not None and not (0.0 <= float(value) <= 1.0):
                raise GuideError(f"guide_legend({name}=) 必须在 0..1，收到 {value!r}")
        object.__setattr__(self, "override_aes", MappingProxyType(dict(self.override_aes)))


@dataclass(frozen=True, slots=True)
class GuideColourbar(Guide):
    """`guide_colourbar()`：连续色标——渐变条 + 断点刻度 + 标签。

    4.0.3 把一批老参数挪进了主题（`legend.key.width/height` → `barwidth/barheight`、
    `legend.ticks` → `ticks.colour`、`legend.frame` → `frame.colour`、
    `legend.title.position` → `title.position`）。这里两套写法都认：guide 上的显式
    参数优先于主题，未给时用主题值（与 R 的 `replace_null()` 同口径）。

    `display` 是 4.0.3 的正式参数（`"raster"` / `"rectangles"` / `"gradient"`）；
    旧写法 `raster=TRUE/FALSE` 在工厂里折成 `"raster"` / `"rectangles"`。
    本仓的 IR 没有渐变填充之外的差别：`raster` / `rectangles` 都画成 `nbin` 条
    相邻矩形（两者在 R 里只差 rasterGrob 还是 rectGrob，像素等价），`gradient`
    的 `nbin` 默认 15。
    """

    title: Any = AUTO
    direction: str | None = None
    position: str | None = None
    barwidth: Any = None
    barheight: Any = None
    nbin: int | None = None
    ticks: bool = True
    display: str = "raster"
    draw_llim: bool = True
    draw_ulim: bool = True
    ticks_colour: Any = None
    frame_colour: Any = None
    title_position: str | None = None
    alpha: float | None = None
    reverse: bool = False
    order: float = 0.0
    #: 逐 guide 的主题覆盖（R 4.0.3 的 `guide_colourbar(theme = theme(...))`）。
    theme: Any = None
    kind: str = "colourbar"

    def __post_init__(self) -> None:
        if self.direction not in (None, "vertical", "horizontal"):
            raise GuideError(
                f"guide_colourbar(direction=) 只能是 'vertical' / 'horizontal'，"
                f"收到 {self.direction!r}"
            )
        if self.position not in (None, "top", "bottom", "left", "right", "inside"):
            raise GuideError(
                f"guide_colourbar(position=) 只能是 top / bottom / left / right / inside，"
                f"收到 {self.position!r}"
            )
        if self.display not in ("raster", "rectangles", "gradient"):
            raise GuideError(
                "guide_colourbar(display=) 只能是 'raster' / 'rectangles' / 'gradient'，"
                f"收到 {self.display!r}"
            )
        if self.nbin is None:
            object.__setattr__(self, "nbin", 15 if self.display == "gradient" else 300)
        if not isinstance(self.nbin, int) or self.nbin < 2:
            raise GuideError(f"guide_colourbar(nbin=) 必须 ≥ 2，收到 {self.nbin!r}")
        if self.title_position not in (None, "top", "bottom", "left", "right"):
            raise GuideError(
                "guide_colourbar(title.position=) 只能是 top / bottom / left / right，"
                f"收到 {self.title_position!r}"
            )
        if self.alpha is not None and not 0.0 <= float(self.alpha) <= 1.0:
            raise GuideError(f"guide_colourbar(alpha=) 必须在 0..1，收到 {self.alpha!r}")


@dataclass(frozen=True, slots=True)
class GuideBins(Guide):
    """`guide_bins()`：分箱图例——每个箱一格键，标签落在箱的边界上。"""

    title: Any = AUTO
    direction: str | None = None
    angle: float | None = None
    position: str | None = None
    override_aes: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    reverse: bool = False
    order: float = 0.0
    show_limits: bool | None = None
    #: 逐 guide 的主题覆盖（R 4.0.3 的 `guide_bins(theme = theme(...))`）。
    theme: Any = None
    kind: str = "bins"

    def __post_init__(self) -> None:
        if self.direction not in (None, "vertical", "horizontal"):
            raise GuideError(
                f"guide_bins(direction=) 只能是 'vertical' / 'horizontal'，收到 {self.direction!r}"
            )
        object.__setattr__(self, "override_aes", MappingProxyType(dict(self.override_aes)))


@dataclass(frozen=True, slots=True)
class GuideColoursteps(Guide):
    """`guide_coloursteps()`：分段色条——等宽（`even.steps=True`）或按数据间距。"""

    title: Any = AUTO
    direction: str | None = None
    angle: float | None = None
    position: str | None = None
    even_steps: bool = True
    show_limits: bool | None = None
    alpha: float | None = None
    reverse: bool = False
    order: float = 0.0
    #: 逐 guide 的主题覆盖（R 4.0.3 的 `guide_coloursteps(theme = theme(...))`）。
    theme: Any = None
    kind: str = "coloursteps"

    def __post_init__(self) -> None:
        if self.direction not in (None, "vertical", "horizontal"):
            raise GuideError(
                "guide_coloursteps(direction=) 只能是 'vertical' / 'horizontal'，"
                f"收到 {self.direction!r}"
            )
        if self.alpha is not None and not 0.0 <= float(self.alpha) <= 1.0:
            raise GuideError(f"guide_coloursteps(alpha=) 必须在 0..1，收到 {self.alpha!r}")


@dataclass(frozen=True, slots=True)
class BinnedKeys:
    """分箱 guide 的训练结果：箱边界 + 每箱的映射值 + 边界标签。

    `edges` / `labels` 长度都是「箱数 + 1」；`bin_values[i]` 是第 i 箱中心的映射
    值（`colour` 是色串，`size` / `alpha` 是数）。`show_limits` 是首尾两个边界
    标签是否画（R 的 `show.limits`，边界本身是断点时总是画）。
    """

    edges: tuple[float, ...]
    labels: tuple[str, ...]
    bin_values: tuple[Mapping[str, Any], ...]
    even: bool = True
    show_limits: tuple[bool, bool] = (False, False)

    @property
    def bins(self) -> int:
        return len(self.bin_values)

    def bin_bounds(self) -> tuple[tuple[float, float], ...]:
        """每箱在 0..1 上的 `(low, high)`（`even=True` 等宽，否则按 edges 间距）。"""
        low, high = self.edges[0], self.edges[-1]
        span = high - low
        if span == 0:
            return tuple((index / self.bins, (index + 1) / self.bins) for index in range(self.bins))
        if self.even:
            return tuple((index / self.bins, (index + 1) / self.bins) for index in range(self.bins))
        fractions = [(edge - low) / span for edge in self.edges]
        return tuple((fractions[index], fractions[index + 1]) for index in range(self.bins))


@dataclass(frozen=True, slots=True)
class GuideCustom(Guide):
    """`guide_custom()`：把任意 grob 放进图例盒，不绑定任何标度。

    `grob` 可以是 :mod:`ggcore.grobs` 的 grob，也可以是
    ``callable(width_cm, height_cm) -> grob | Sequence[grob]``（需要按格子尺寸
    现算时用后者）。尺寸缺省为 `legend.key.width/height`（1.2 lines），显式给
    `width` / `height` 时按 unit 换算。
    """

    grob: Any = None
    width: Any = None
    height: Any = None
    title: str | None = None
    position: str | None = None
    order: float = 0.0
    #: 逐 guide 的主题覆盖（R 4.0.3 的 `guide_custom(theme = theme(...))`）。
    theme: Any = None
    kind: str = "custom"
    available_aes: tuple[str, ...] = ("any",)

    def __post_init__(self) -> None:
        if self.grob is None or not (
            callable(self.grob) or hasattr(self.grob, "name") or hasattr(self.grob, "gps")
        ):
            raise GuideError(
                "guide_custom(grob=) 需要 grob 对象或 (width_cm, height_cm) 可调用对象"
            )
        if self.position not in (None, "top", "bottom", "left", "right", "inside"):
            raise GuideError(
                f"guide_custom(position=) 只能是 top / bottom / left / right / inside，"
                f"收到 {self.position!r}"
            )

    def train(self, build: PlotBuild, aesthetic: str, scale: Any) -> GuideBuild | None:
        # 自定义 guide 不绑定标度：由 `build_guides()` 单独收集。
        return None

    def gengrob(
        self,
        guide_build: GuideBuild,
        build: PlotBuild,
        theme: ResolvedTheme,
        layout: LegendLayout,
        *,
        metrics: Any = None,
        name: str = "guide",
    ) -> list[Any]:
        return custom_grob(guide_build, theme, layout, metrics=metrics, name=name)


@dataclass(frozen=True, slots=True)
class GuideNone(Guide):
    """`guide = "none"`：该美学不画图例。"""

    kind: str = "none"

    def train(self, build: PlotBuild, aesthetic: str, scale: Any) -> GuideBuild | None:
        return None


def guide_legend(
    title: Any = AUTO,
    direction: str | None = None,
    nrow: int | None = None,
    ncol: int | None = None,
    byrow: bool | None = None,
    override_aes: Mapping[str, Any] | None = None,
    keywidth: Any = None,
    keyheight: Any = None,
    reverse: bool = False,
    order: float = 0.0,
    position: str | None = None,
    title_position: str | None = None,
    title_hjust: float | None = None,
    title_vjust: float | None = None,
    subtitle: str | None = None,
    label_position: str | None = None,
    label_hjust: float | None = None,
    label_vjust: float | None = None,
    theme: Any = None,
) -> GuideLegend:
    return GuideLegend(
        title=title,
        direction=direction,
        position=position,
        nrow=nrow,
        ncol=ncol,
        byrow=None if byrow is None else bool(byrow),
        override_aes=dict(override_aes or {}),
        keywidth=keywidth,
        keyheight=keyheight,
        reverse=bool(reverse),
        order=float(order),
        title_position=title_position,
        title_hjust=title_hjust,
        title_vjust=title_vjust,
        subtitle=subtitle,
        label_position=label_position,
        label_hjust=label_hjust,
        label_vjust=label_vjust,
        theme=theme,
    )


def guide_colourbar(
    title: Any = AUTO,
    direction: str | None = None,
    barwidth: Any = None,
    barheight: Any = None,
    nbin: int | None = None,
    ticks: bool = True,
    display: str = "raster",
    draw_llim: bool = True,
    draw_ulim: bool = True,
    ticks_colour: Any = None,
    frame_colour: Any = None,
    title_position: str | None = None,
    alpha: float | None = None,
    reverse: bool = False,
    order: float = 0.0,
    position: str | None = None,
    theme: Any = None,
    *,
    raster: bool | None = None,
    **legacy: Any,
) -> GuideColourbar:
    """`guide_colourbar()`。参数名同时认 R 的点号写法（`ticks.colour` 等）。"""
    if raster is not None:
        display = "raster" if raster else "rectangles"
    ticks_colour = _first_not_none(ticks_colour, legacy.pop("ticks.colour", None))
    frame_colour = _first_not_none(frame_colour, legacy.pop("frame.colour", None))
    title_position = _first_not_none(title_position, legacy.pop("title.position", None))
    if legacy:
        unknown = ", ".join(sorted(legacy))
        raise GuideError(f"guide_colourbar() 不认识这些参数：{unknown}")
    return GuideColourbar(
        title=title,
        direction=direction,
        position=position,
        barwidth=barwidth,
        barheight=barheight,
        nbin=nbin,
        ticks=bool(ticks),
        display=display,
        draw_llim=bool(draw_llim),
        draw_ulim=bool(draw_ulim),
        ticks_colour=ticks_colour,
        frame_colour=frame_colour,
        title_position=title_position,
        alpha=None if alpha is None else float(alpha),
        reverse=bool(reverse),
        order=float(order),
        theme=theme,
    )


#: 上游 `guide_colorbar` 与 `guide_colourbar` 是同一个函数（NAMESPACE 两个都导出）。
guide_colorbar = guide_colourbar


def guide_custom(
    grob: Any,
    width: Any = None,
    height: Any = None,
    title: str | None = None,
    position: str | None = None,
    order: float = 0.0,
    theme: Any = None,
) -> GuideCustom:
    return GuideCustom(
        grob=grob,
        width=width,
        height=height,
        title=title,
        position=position,
        order=float(order),
        theme=theme,
    )


def guide_bins(
    title: Any = AUTO,
    direction: str | None = None,
    angle: float | None = None,
    position: str | None = None,
    override_aes: Mapping[str, Any] | None = None,
    reverse: bool = False,
    order: float = 0.0,
    show_limits: bool | None = None,
    theme: Any = None,
    **legacy: Any,
) -> GuideBins:
    """`guide_bins()`：分箱图例。`show.limits` 的点号写法也认。"""
    show_limits = _first_not_none(show_limits, legacy.pop("show.limits", None))
    if legacy:
        unknown = ", ".join(sorted(legacy))
        raise GuideError(f"guide_bins() 不认识这些参数：{unknown}")
    return GuideBins(
        title=title,
        direction=direction,
        angle=None if angle is None else float(angle),
        position=position,
        override_aes=dict(override_aes or {}),
        reverse=bool(reverse),
        order=float(order),
        show_limits=show_limits,
        theme=theme,
    )


def guide_coloursteps(
    title: Any = AUTO,
    direction: str | None = None,
    angle: float | None = None,
    position: str | None = None,
    even_steps: bool = True,
    show_limits: bool | None = None,
    alpha: float | None = None,
    reverse: bool = False,
    order: float = 0.0,
    theme: Any = None,
    **legacy: Any,
) -> GuideColoursteps:
    """`guide_coloursteps()`（别名 `guide_colorsteps`）。"""
    even_steps = _first_not_none(even_steps, legacy.pop("even.steps", None))
    show_limits = _first_not_none(show_limits, legacy.pop("show.limits", None))
    if not isinstance(even_steps, bool):
        raise GuideError(f"guide_coloursteps(even.steps=) 必须是布尔值，收到 {even_steps!r}")
    if legacy:
        unknown = ", ".join(sorted(legacy))
        raise GuideError(f"guide_coloursteps() 不认识这些参数：{unknown}")
    return GuideColoursteps(
        title=title,
        direction=direction,
        angle=None if angle is None else float(angle),
        position=position,
        even_steps=even_steps,
        show_limits=show_limits,
        alpha=None if alpha is None else float(alpha),
        reverse=bool(reverse),
        order=float(order),
        theme=theme,
    )


def _first_not_none(*values: Any) -> Any:
    """返回第一个非 None 的值（R 的 `%||%`）。"""
    for value in values:
        if value is not None:
            return value
    return None


def guide_none() -> GuideNone:
    return GuideNone()


_LEGEND_PARAMS = frozenset(
    {
        "title",
        "direction",
        "position",
        "nrow",
        "ncol",
        "byrow",
        "override_aes",
        "keywidth",
        "keyheight",
        "reverse",
        "order",
        "title_position",
        "title_hjust",
        "title_vjust",
        "subtitle",
        "label_position",
        "label_hjust",
        "label_vjust",
        "theme",
    }
)
_COLOURBAR_PARAMS = frozenset(
    {
        "title",
        "direction",
        "position",
        "barwidth",
        "barheight",
        "nbin",
        "ticks",
        "display",
        "raster",
        "draw_llim",
        "draw_ulim",
        "ticks_colour",
        "ticks.colour",
        "frame_colour",
        "frame.colour",
        "title_position",
        "title.position",
        "alpha",
        "reverse",
        "order",
        "theme",
    }
)
_BINS_PARAMS = frozenset(
    {
        "title",
        "direction",
        "angle",
        "position",
        "override_aes",
        "override.aes",
        "reverse",
        "order",
        "show_limits",
        "show.limits",
        "theme",
    }
)
_STEPS_PARAMS = frozenset(
    {
        "title",
        "direction",
        "angle",
        "position",
        "even_steps",
        "even.steps",
        "show_limits",
        "show.limits",
        "alpha",
        "reverse",
        "order",
        "theme",
    }
)
_CUSTOM_PARAMS = frozenset({"grob", "width", "height", "title", "position", "order", "theme"})

#: R 4.0.3 的旧参数名（带点）→ gg4py 的字段名。新旧写法等价。
_PARAM_ALIASES = {
    "override.aes": "override_aes",
    "title.position": "title_position",
    "title.hjust": "title_hjust",
    "title.vjust": "title_vjust",
    "label.position": "label_position",
    "label.hjust": "label_hjust",
    "label.vjust": "label_vjust",
}


def _clean(params: Mapping[str, Any], allowed: frozenset[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, value in params.items():
        out[_PARAM_ALIASES.get(name, name)] = value
    return {name: value for name, value in out.items() if name in allowed}


def guide_from_component(component: Any) -> Guide:
    """`components.Guide`（注册名 + 参数）→ :mod:`ggcore.guide` 的实现。

    内置名字走自己的分支；其余名字认 M2-9 的扩展点：组件子类覆写
    ``build_guide()`` 并返回 :class:`Guide` 实现（`registry.register_guide()`）。
    """
    name = getattr(component, "name", None)
    params = dict(getattr(component, "params", {}) or {})
    if name == "none":
        return GuideNone()
    if name == "legend":
        return guide_legend(**{k: v for k, v in _clean(params, _LEGEND_PARAMS).items()})
    if name in ("colourbar", "colorbar"):
        return guide_colourbar(**{k: v for k, v in _clean(params, _COLOURBAR_PARAMS).items()})
    if name == "bins":
        return guide_bins(**{k: v for k, v in _clean(params, _BINS_PARAMS).items()})
    if name in ("coloursteps", "colorsteps", "steps"):
        return guide_coloursteps(**{k: v for k, v in _clean(params, _STEPS_PARAMS).items()})
    if name == "custom":
        cleaned = _clean(params, _CUSTOM_PARAMS)
        if "grob" not in cleaned:
            raise GuideError("guide_custom() 需要 grob 参数（见 docs/notes/guide.md）")
        return guide_custom(**cleaned)
    from ggcore.components import Guide as GuideComponent

    builder = getattr(component, "build_guide", None)
    if callable(builder) and getattr(type(component), "build_guide", None) is not (
        GuideComponent.build_guide
    ):
        built = builder()
        if not isinstance(built, Guide):
            raise GuideError(
                f"guide_{name} 的 build_guide() 必须返回 ggcore.guide.Guide，"
                f"得到 {type(built).__name__}"
            )
        return built
    raise GuideError(
        f"未知的 guide {name!r}；已实现：legend / colourbar / bins / coloursteps / none / custom"
        "，其余用 registry.register_guide() + build_guide() 扩展"
        "（轴 guide 见 ggcore.axis_guide）"
    )


# ---------------------------------------------------------------------------
# 训练好的 guide：keys + 标题
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GuideKey:
    """一个图例键：标签 + 断点原值 + 各美学映射后的值。"""

    label: str
    values: Mapping[str, Any]
    #: 断点在标度空间的原值（连续色条用它算刻度位置）；离散是水平名。
    value: Any = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


@dataclass(frozen=True, slots=True)
class GuideBuild:
    """一张要画的图例：guide 定义 + 美学 + 标题 + 键 + 参与绘制的图层。"""

    guide: Guide
    aesthetics: tuple[str, ...]
    title: str | None
    keys: tuple[GuideKey, ...]
    layers: tuple[int, ...]
    #: 连续标度的范围（色条刻度按它定位）；离散为 None。
    limits: tuple[float, float] | None = None
    #: 标度自己的连续调色板（`positions in 0..1 → colour`）。色条按**全量程**
    #: 取色时用它，与数据映射同一个插值（连续 colour 是 Lab）。
    palette: Callable[[Sequence[float]], Sequence[str]] | None = None
    #: `plot.guides` 里登记的名字（自定义 guide 用；普通 guide 为空）。
    name: str = ""
    #: 分箱 guide（bins / coloursteps）的训练结果；其它 guide 为 None。
    bins: BinnedKeys | None = None
    #: 参与绘制的图层的 `key_glyph=`（每层一项；`None` 表示按 geom 默认画）。
    key_glyphs: tuple[Any, ...] = ()

    @property
    def kind(self) -> str:
        return self.guide.kind

    @property
    def position(self) -> str | None:
        return self.guide.position_of()


def _layer_mapping(build: PlotBuild, index: int) -> Mapping[str, Any]:
    mappings = getattr(build, "raw_mappings", ())
    return mappings[index] if index < len(mappings) else {}


def _default_title(build: PlotBuild, aesthetic: str) -> str | None:
    labels = getattr(build, "labels", {}) or {}
    if aesthetic in labels:
        value = labels[aesthetic]
        return None if value is None else str(value)
    # 取第一条映射该美学的图层的表达式原文（`aes(colour="g")` → "g"）。
    for mapping in getattr(build, "raw_mappings", ()):
        if aesthetic in mapping:
            return str(mapping[aesthetic])
    # `Stat$default_aes` 补的美学用 stat 输出列当标题：`geom_hex()` 的
    # `fill = after_stat(count)` 图例标题是 "count"，不是 "fill"。
    for layer in getattr(build, "layers", ()):
        for name, source in STAT_DEFAULT_AES.get(str(layer.stat), ()):
            if name == aesthetic:
                return source
    return aesthetic


def _resolve_guide_value(value: Any) -> Guide | None:
    """`plot.guides` / `scale_*(guide=)` 里的一个值 → 实现（`None` = 未设置）。"""
    if value is None:
        return None
    if isinstance(value, Guide):
        return value
    if isinstance(value, str):
        return _guide_from_value(value)
    if getattr(value, "name", None) is not None:
        return guide_from_component(value)
    if hasattr(value, "params") and getattr(value, "aesthetic", None) is not None:
        return guide_from_component(value)
    raise GuideError(
        f"无法把 {value!r} 当作 guide；用字符串（'none' / 'legend' / 'colourbar'）、"
        "guide_legend() / guide_colourbar() / guide_custom() 或注册表组件"
    )


def _guide_component(build: PlotBuild, aesthetic: str) -> Guide | None:
    """`plot.guides` 里作用于该美学的条目（后加的已在 `+` 时替换先加的）。"""
    guides = getattr(build, "guides", None) or {}
    for key, component in guides.items():
        component_aesthetic = getattr(component, "aesthetic", None)
        if component_aesthetic == aesthetic:
            return _resolve_guide_value(component)
        if component_aesthetic is None and _rename_key(key) == aesthetic:
            return _resolve_guide_value(component)
    return None


def _rename_key(name: Any) -> Any:
    return "colour" if name == "color" else name


def _guide_from_value(value: Any) -> Guide | None:
    """`scale_*(guide=)` 的值 → 实现。

    R 的 `scale_*_*(guide = )` 接受三种写法，这里一一对等：

    - 字符串：`"none"` → :class:`GuideNone`；`"legend"` / `"colourbar"` 走内置；
      通过 `registry.register_guide()` 登记的名字也认（组件子类覆写
      ``build_guide()``）；
    - `components.Guide`（`registry.guide_legend(...)`）→ :func:`guide_from_component`；
    - `Guide` 实现本身（`ggcore.guide.guide_legend(...)`）原样返回。
    """
    if value is None:
        return None
    if isinstance(value, Guide):
        return value
    if isinstance(value, str):
        if value == "none":
            return guide_none()
        if value == "legend":
            return guide_legend()
        if value in ("colourbar", "colorbar"):
            return guide_colourbar()
        if value == "bins":
            return guide_bins()
        if value in ("coloursteps", "colorsteps", "steps"):
            return guide_coloursteps()
        if value in ("axis", "axis_logticks", "axis_stack", "axis_theta"):
            # 轴 guide 不是图例：`guides(x = "axis_theta")` 由
            # `ggcore.axis_guide` 消费，图例侧没有对应物（不画图例）。
            return None
        from ggcore import registry as _registry

        if value in _registry.registered("guide"):
            return guide_from_component(_registry.construct("guide", value))
        raise GuideError(
            f"未知的 guide {value!r}；已实现：legend / colourbar / bins / coloursteps / none"
            "，其余用 registry.register_guide() + build_guide() 扩展"
            "（轴 guide 用 ggcore.axis_guide，见 docs/notes/guide.md §8）"
        )
    if getattr(value, "name", None) is not None:
        return guide_from_component(value)
    raise GuideError(
        f"无法把 {value!r} 当作 guide；用字符串（'none' / 'legend' / 'colourbar' / "
        "'bins' / 'coloursteps'）或 guide_legend() / guide_colourbar() / guide_custom()"
    )


def _scale_guide(scale: Any) -> Guide | None:
    """标度上的 `guide=` 参数（`plot.guides` 没有对应条目时的回落）。"""
    params = getattr(scale, "params", None) or {}
    return _guide_from_value(params.get("guide"))


def _is_mapped(build: PlotBuild, index: int, aesthetic: str) -> bool:
    layer = build.layers[index]
    show = getattr(layer, "show_legend", None)
    if show is None:
        show = layer.params.get("show_legend", layer.params.get("show.legend"))
    if isinstance(show, Mapping):
        # R 4.0.3：`show.legend = c(colour = NA, alpha = FALSE)` 逐美学生效。
        # `NA` 是自动（照常按映射决定），`FALSE` 只关掉这一条美学。
        for name in (aesthetic, "colour" if aesthetic == "color" else aesthetic):
            if name in show:
                show = show[name]
                break
        else:
            show = None
    if show is False:
        return False
    if aesthetic in getattr(layer, "params", {}):
        # 层参数（R 的 `aes_params`）覆盖同名映射：`geom_point(colour = "black")`
        # 的 colour 不再是映射，因此不产生图例键（上游
        # `setup_plot_labels()` 用 `setdiff(names(mapping), names(layer$aes_params))`）。
        return False
    if aesthetic in _layer_mapping(build, index):
        return True
    # `Stat$default_aes` 补出来的美学不在 `aes()` 里，但确实是映射：
    # `geom_hex()` 的 `fill = after_stat(count)`（`StatBinhex$default_aes`）
    # 要出 `count` 的 colourbar。上游 `Guides$setup()` 只看「标度存在」，
    # 这里的等价条件是「这一层的 stat 自己补了这一列」。
    return aesthetic in _stat_default_aesthetics(str(layer.stat))


def _stat_default_aesthetics(stat: str) -> frozenset[str]:
    """`Stat$default_aes` 里这个 stat 会补的美学名（`after_stat()` 部分）。"""
    from ggcore.build import STAT_DEFAULT_AES

    return frozenset(name for name, _source in STAT_DEFAULT_AES.get(stat, ()))


def _default_guide(build: PlotBuild, aesthetic: str, scale: Any) -> Guide:
    if aesthetic in ("colour", "fill") and not bool(getattr(scale, "discrete", False)):
        return guide_colourbar()
    return guide_legend()


def _key_values(scale: Any) -> tuple[tuple[str, Any, Any], ...]:
    """标度的 `(label, 断点原值, 映射值)` 序列（R `extract_key()` 的 `.label`/键）。"""
    breaks = tuple(scale.breaks())
    labels = tuple(scale.labels())
    values: list[Any] = []
    for value in breaks:
        if value is None:
            values.append(None)
            continue
        if scale.discrete:
            values.append(str(value))
        else:
            values.append(float(value))
    mapped = _list_of(scale.map(_column_of(values, scale)))
    out: list[tuple[str, Any, Any]] = []
    for label, value, item in zip(labels, values, mapped, strict=True):
        if label is None or value is None:
            continue
        if isinstance(item, float) and not np.isfinite(item):
            continue
        if item is None:
            continue
        out.append((str(label), value, item))
    return tuple(out)


def _column_of(values: Sequence[Any], scale: Any) -> Column:
    if getattr(scale, "discrete", False):
        texts = ["" if item is None else str(item) for item in values]
        return Column("str", np.array(texts, dtype=object))
    numbers = np.array(
        [np.nan if item is None else float(item) for item in values], dtype=np.float64
    )
    return Column("float", numbers)


def _list_of(mapped: Any) -> list[Any]:
    if not isinstance(mapped, Column):
        return list(mapped)
    values = np.asarray(mapped.values)
    mask = np.asarray(mapped.na_mask, dtype=bool)
    pairs = zip(values.tolist(), mask.tolist(), strict=True)
    if values.dtype.kind in ("O", "U"):
        return [None if missing else str(item) for item, missing in pairs]
    return [None if missing else float(item) for item, missing in pairs]


def _show_limits(scale: Any, guide: Guide) -> bool:
    """`show.limits`：guide 显式 > 标度参数 > False（R 的 `%||%` 链）。"""
    value = getattr(guide, "show_limits", None)
    if value is None:
        params = getattr(scale, "params", None) or {}
        value = params.get("show.limits", params.get("show_limits", False))
    return bool(value)


def _binned_keys(
    scale: Any,
    aesthetic: str,
    keys: Sequence[tuple[str, Any, Any]],
    limits: tuple[float, float],
    guide: Guide,
) -> BinnedKeys:
    """断点 → 箱：边界 = limits 两端 + 落在范围内的断点。

    与 R 的 `parse_binned_breaks()` 同口径：limit 本身是断点时不再重复加一条，
    且那个边界标签**总是**画（`show.limits` 只管不在断点上的两端）。
    """
    low, high = sorted((float(limits[0]), float(limits[1])))
    inner = [
        (label, float(value))
        for label, value, _item in keys
        if value is not None and low < float(value) < high
    ]
    edges = [low, *(value for _label, value in inner), high]
    label_low, label_high = _limit_labels(scale, low, high)
    labels = [label_low, *(label for label, _value in inner), label_high]
    midpoints = [(edges[index] + edges[index + 1]) / 2.0 for index in range(len(edges) - 1)]
    mapped = _list_of(scale.map(_column_of(midpoints, scale)))
    bin_values = tuple({aesthetic: item} for item in mapped)
    show = _show_limits(scale, guide)
    at_low = any(abs(value - low) <= 1e-12 * max(1.0, abs(low)) for _label, value in inner)
    at_high = any(abs(value - high) <= 1e-12 * max(1.0, abs(high)) for _label, value in inner)
    even = not isinstance(guide, GuideColoursteps) or bool(guide.even_steps)
    return BinnedKeys(
        edges=tuple(edges),
        labels=tuple(labels),
        bin_values=bin_values,
        even=even,
        show_limits=(show or at_low, show or at_high),
    )


def _limit_labels(scale: Any, low: float, high: float) -> tuple[str, str]:
    """limits 两端的标签（`scale.labels_in()`；不可用时退回数值格式）。"""
    labels_in = getattr(scale, "labels_in", None)
    if callable(labels_in):
        try:
            result = tuple(labels_in((low, high)))
        except Exception:  # pragma: no cover - 自定义标度可能没有 labels_in
            result = ()
        if len(result) == 2 and result[0] is not None and result[1] is not None:
            return str(result[0]), str(result[1])
    from ggcore.scales import format_numbers

    numbers = [str(item) for item in format_numbers([low, high])]
    return numbers[0], numbers[1]


def _binned_guide_keys(
    aesthetic: str,
    keys: Sequence[tuple[str, Any, Any]],
    bins: BinnedKeys,
    guide: Guide,
    reverse: bool,
) -> list[GuideKey]:
    """分箱 guide 的 `keys`（`get_guide_data()` 的形状，用于 R 对拍）。

    - `guide_bins`：`箱数 + 1` 行，`.value = i / 箱数`，标签是边界；最后一行的
      映射值是 NA（R 的 `c(scale$map(bin_at), NA)`）。
    - `guide_coloursteps`：断点行，`.value = (i + 1) / 箱数`；`show.limits` 时
      再补两端各一行。
    """
    if isinstance(guide, GuideBins):
        rows: list[GuideKey] = []
        for index, label in enumerate(bins.labels):
            mapped = bins.bin_values[index][aesthetic] if index < bins.bins else None
            rows.append(GuideKey(label, {aesthetic: mapped}, value=index / max(1, bins.bins)))
        if reverse:
            rows.reverse()
            rows = [GuideKey(row.label, row.values, 1.0 - float(row.value)) for row in rows]
        return rows
    rows = []
    n = max(1, bins.bins)
    for index, (label, _value, item) in enumerate(keys):
        rows.append(GuideKey(label, {aesthetic: item}, value=(index + 1) / n))
    if bins.show_limits[0] or bins.show_limits[1]:
        if bins.show_limits[0]:
            rows.insert(0, GuideKey(bins.labels[0], {aesthetic: None}, value=0.0))
        if bins.show_limits[1]:
            rows.append(GuideKey(bins.labels[-1], {aesthetic: None}, value=1.0))
    if reverse:
        rows.reverse()
        rows = [GuideKey(row.label, row.values, 1.0 - float(row.value)) for row in rows]
    return rows


def _train_scale_guide(
    guide: Guide, build: PlotBuild, aesthetic: str, scale: Any
) -> GuideBuild | None:
    """`Guide$train()` 的对等物：一个标度 → 一张（未合并的）guide。

    子类可以覆盖 :meth:`Guide.train` 来换掉整套键提取逻辑；默认路径就是
    ggplot2 的 `extract_key()`：`breaks` 映射后配上 `get_labels()`。
    """
    keys = _key_values(scale)
    if not keys:
        return None
    title_value = getattr(guide, "title", AUTO)
    if title_value is AUTO:
        title = _default_title(build, aesthetic)
        explicit = _scale_name(scale)
        if explicit is not None:
            title = str(explicit)
    else:
        title = None if title_value is None else str(title_value)
    reverse = bool(getattr(guide, "reverse", False))
    layers = tuple(
        index for index in range(len(build.layers)) if _is_mapped(build, index, aesthetic)
    )
    limits = None
    if not bool(getattr(scale, "discrete", False)):
        limits = tuple(float(item) for item in scale.limits())
    palette = getattr(scale, "palette", None)
    bins = None
    if isinstance(guide, (GuideBins, GuideColoursteps)):
        if limits is None:
            raise GuideError(
                f"{aesthetic!r} 是离散标度，guide_bins / guide_coloursteps 只服务连续色标"
            )
        bins = _binned_keys(scale, aesthetic, keys, limits, guide)
        rows = tuple(_binned_guide_keys(aesthetic, keys, bins, guide, reverse))
    else:
        if reverse:
            keys = tuple(reversed(keys))
        rows = tuple(GuideKey(label, {aesthetic: item}, value) for label, value, item in keys)
    built = GuideBuild(
        guide=guide,
        aesthetics=(aesthetic,),
        title=title,
        keys=rows,
        layers=layers,
        limits=limits,
        palette=palette if callable(palette) else None,
        bins=bins,
    )
    return replace(built, keys=guide.transform(built.keys))


#: 轴 guide 在 `plot.guides` 里的键（不产图例，由 scene 的轴阶段消费）。
_AXIS_GUIDE_KEYS = ("x", "y", "theta")

#: 轴 guide 的组件名（`guide_axis()` 家族；见 `ggcore.axis_guide`）。
_AXIS_GUIDE_NAMES = ("axis", "axis_logticks", "axis_stack", "stacked_axis", "axis_theta")


def _is_axis_guide_entry(key: Any, raw: Any) -> bool:
    """这条 `plot.guides` 条目是不是轴 guide（x / y / theta）。"""
    if getattr(raw, "name", None) in _AXIS_GUIDE_NAMES:
        return True
    from ggcore.axis_guide import AxisGuide

    if isinstance(raw, AxisGuide):
        return True
    return _rename_key(key) in _AXIS_GUIDE_KEYS


def _custom_builds(build: PlotBuild) -> list[GuideBuild]:
    """`plot.guides` 里的 `guide_custom()` / 无标度 guide → 自己的 GuideBuild。"""
    out: list[GuideBuild] = []
    seen: dict[Any, int] = {}
    for key, raw in (getattr(build, "guides", None) or {}).items():
        if _is_axis_guide_entry(key, raw):
            continue
        component = _resolve_guide_value(raw)
        if not isinstance(component, GuideCustom):
            continue
        title = None if component.title is None else str(component.title)
        hashable = (
            title,
            id(component.grob),
            _cm_unit(component.width, height=False) if component.width is not None else None,
            _cm_unit(component.height, height=True) if component.height is not None else None,
            component.order,
            component.position,
        )
        if hashable in seen:
            # R 的 `Guides$get_custom()` 会按 hash 合并相同配置的 custom guide。
            continue
        seen[hashable] = len(out)
        out.append(
            GuideBuild(
                guide=component,
                aesthetics=(),
                title=title,
                keys=(),
                layers=(),
                name=str(key),
            )
        )
    return out


def build_guides(build: PlotBuild) -> tuple[GuideBuild, ...]:
    """`PlotBuild` → 要画的 guide 列表（已按上游的 hash / order 折叠排序）。

    步骤照 ggplot2 4.0.3 的 `Guides$build()`：

    1. 每个「被映射的美学 × 标度」训练一个 guide（`Guides$setup()` / `train()`）；
    2. 按 `order` + `hash`（`hashables = (title, key$.label, name)`）分组，组内
       `Reduce(merge)`（`Guides$merge()`）；
    3. 自定义 guide（`guide_custom()`）不绑标度，单独收集、按同样的 hash 去重，
       再与普通 guide 一起按 order 排序（`get_custom()`）。
    """
    scales = build.scales
    candidates: list[GuideBuild] = []
    for aesthetic in GUIDE_AESTHETICS:
        scale = scales.scale(aesthetic) if scales is not None else None
        if scale is None:
            continue
        layers = tuple(
            index for index in range(len(build.layers)) if _is_mapped(build, index, aesthetic)
        )
        if not layers:
            continue
        component = _guide_component(build, aesthetic)
        if isinstance(component, GuideNone):
            continue
        if component is None:
            # `plot.guides` 没有对应条目时回落到 `scale_*(guide=)`。
            component = _scale_guide(scale)
        if isinstance(component, GuideNone):
            continue
        guide = component if component is not None else _default_guide(build, aesthetic, scale)
        if isinstance(guide, GuideColourbar) and bool(getattr(scale, "discrete", False)):
            raise GuideError(
                f"guide_colourbar 只能用于连续标度；{aesthetic!r} 是离散标度"
                "（用 guide_legend() 或默认 guide）"
            )
        if not _guide_supports(guide, aesthetic):
            raise GuideError(
                f"{type(guide).__name__} 不能用于 {aesthetic!r} 美学；"
                f"它支持 {', '.join(guide.available_aes)}"
            )
        trained = guide.train(build, aesthetic, scale)
        if trained is None:
            continue
        candidates.append(trained)

    merged = _merge_guides(candidates)
    custom = _custom_builds(build)

    def with_glyphs(guide_build: GuideBuild) -> GuideBuild:
        if not guide_build.layers:
            return guide_build
        specs = tuple(
            key_glyph_for(build.layers[index])
            or default_key_glyph(
                getattr(getattr(build.layers[index], "geom_object", None), "name", "")
            )
            for index in guide_build.layers
            if _layer_maps_any(build, index, guide_build.aesthetics)
        )
        return replace(guide_build, key_glyphs=specs)

    return tuple(sorted((*(with_glyphs(item) for item in merged), *custom), key=_sort_key))


def guide_transform(guide: Guide, keys: tuple[GuideKey, ...]) -> tuple[GuideKey, ...]:
    """`guide_transform()`（旧 API 名）：键变换钩子，转发到 :meth:`Guide.transform`。"""
    return guide.transform(keys)


def guide_geom(guide: Guide, layer: LayerBuild) -> Any | None:
    """`guide_geom()`（旧 API 名）：键几何钩子，转发到 :meth:`Guide.geom`。"""
    return guide.geom(layer)


def guide_train(guide: Guide, build: PlotBuild, aesthetic: str, scale: Any) -> GuideBuild | None:
    """`guide_train()`（旧 API 名）：转发到 :meth:`Guide.train`。"""
    return guide.train(build, aesthetic, scale)


def guide_merge(guide: Guide, new_guide: Guide) -> Guide:
    """`guide_merge(guide, new_guide)`（旧 API 名）：把新 guide 的显式参数并进旧 guide。

    上游 4.0.3 里这是已废弃的 S3 泛型（`R/guide-old.R`，`guide_merge.default` 就是
    `guide_train.default`）：`Guides$merge()` 早就不用它了，但 NAMESPACE 仍然导出。
    口径按上游那个 default：**新 guide 显式给出的字段覆盖旧的**，其余保留旧值；
    两者类型不同时整体取新的（旧 API 没有跨类型的合并规则）。
    """
    if not isinstance(guide, Guide) or not isinstance(new_guide, Guide):
        raise GuideError(
            "guide_merge() 需要两个 Guide 对象，收到 "
            f"{type(guide).__name__} / {type(new_guide).__name__}"
        )
    if type(guide) is not type(new_guide):
        return new_guide
    explicit: dict[str, Any] = {}
    for item in fields(new_guide):
        value = getattr(new_guide, item.name)
        if item.default is not MISSING:
            if value != item.default:
                explicit[item.name] = value
        elif item.default_factory is not MISSING:  # type: ignore[misc]
            if value != item.default_factory():  # type: ignore[misc]
                explicit[item.name] = value
        else:
            explicit[item.name] = value
    return replace(guide, **explicit)


def guide_gengrob(
    guide_build: GuideBuild,
    build: PlotBuild,
    theme: ResolvedTheme,
    layout: LegendLayout,
    *,
    metrics: Any = None,
    name: str = "guide",
) -> list[Any]:
    """`guide_gengrob()`（旧 API 名）：转发到 :meth:`Guide.gengrob`。"""
    return guide_build.guide.gengrob(guide_build, build, theme, layout, metrics=metrics, name=name)


def _guide_supports(guide: Guide, aesthetic: str) -> bool:
    available = getattr(guide, "available_aes", ("any",))
    return "any" in available or aesthetic in available


def _sort_key(guide_build: GuideBuild) -> tuple[float, int, str]:
    order = float(getattr(guide_build.guide, "order", 0.0))
    # R：`orders[orders == 0] <- 99`，即没写 order 的排在显式 order 之后。
    normalised = 99.0 if order == 0.0 else order
    return (normalised, _order_of(guide_build), guide_build.name or "")


def _merge_hash(guide_build: GuideBuild) -> tuple[Any, ...]:
    """R 的 `hashables = exprs(title, key$.label, name)`（再加上 `order`）。"""
    order = float(getattr(guide_build.guide, "order", 0.0))
    order = 99.0 if order == 0.0 else order
    return (
        order,
        guide_build.kind,
        guide_build.title,
        tuple(key.label for key in guide_build.keys),
    )


def _merge_guides(candidates: list[GuideBuild]) -> list[GuideBuild]:
    """按 hash 分组、组内依次合并（`Reduce(Guide$merge)`）。"""
    groups: dict[tuple[Any, ...], int] = {}
    merged: list[GuideBuild] = []
    for candidate in candidates:
        if candidate.kind == "custom":
            merged.append(candidate)
            continue
        key = _merge_hash(candidate)
        position = groups.get(key)
        if position is None:
            groups[key] = len(merged)
            merged.append(candidate)
            continue
        existing = merged[position]
        if set(existing.aesthetics) & set(candidate.aesthetics):
            # 同一美学只会有一张 guide（`plot.guides` 已按美学去重）。
            continue
        merged[position] = _merge(existing, candidate)
    return merged


def _scale_name(scale: Any) -> Any:
    """标度组件上的显式 `name`（`scale_colour_discrete(name="Cyl")`）。"""
    param = getattr(scale, "_param", None)
    if param is None:
        return None
    try:
        return param("name")
    except TypeError:  # pragma: no cover - 自定义标度子类可能没有 name 参数
        return None


def _order_of(guide: GuideBuild) -> int:
    if not guide.aesthetics:
        return len(GUIDE_AESTHETICS)
    return GUIDE_AESTHETICS.index(guide.aesthetics[0])


def _merge(left: GuideBuild, right: GuideBuild) -> GuideBuild:
    """`GuideLegend$merge()`：键按列拼、`override.aes` 先到先得。"""
    keys = tuple(
        GuideKey(first.label, {**first.values, **second.values}, first.value)
        for first, second in zip(left.keys, right.keys, strict=True)
    )
    layers = tuple(dict.fromkeys((*left.layers, *right.layers)))
    overrides = _merge_overrides(_override(left.guide), _override(right.guide))
    return GuideBuild(
        guide=replace(left.guide, override_aes=overrides),
        aesthetics=tuple(dict.fromkeys((*left.aesthetics, *right.aesthetics))),
        title=left.title,
        keys=keys,
        layers=layers,
        limits=left.limits if left.limits is not None else right.limits,
        palette=left.palette if left.palette is not None else right.palette,
        name=left.name,
        bins=left.bins if left.bins is not None else right.bins,
    )


def _merge_overrides(*items: Mapping[str, Any]) -> dict[str, Any]:
    """R：`c(params$override.aes, new_params$override.aes)`，重名保留第一个并告警。"""
    out: dict[str, Any] = {}
    duplicates: list[str] = []
    for item in items:
        for name, value in item.items():
            if name in out:
                duplicates.append(name)
                continue
            out[name] = value
    if duplicates:
        warnings.warn(
            "override.aes 里重复的键被忽略：" + ", ".join(dict.fromkeys(duplicates)),
            UserWarning,
            stacklevel=3,
        )
    return out


def _override(guide: Guide) -> Mapping[str, Any]:
    return getattr(guide, "override_aes", {}) or {}


# ---------------------------------------------------------------------------
# key 数据：复用 Geom.draw()
# ---------------------------------------------------------------------------

_AES_COLUMNS = (
    "colour",
    "fill",
    "alpha",
    "size",
    "shape",
    "stroke",
    "linewidth",
    "linetype",
    "group",
)

_GEOM_KEYS: Mapping[str, Mapping[str, tuple[float, ...]]] = MappingProxyType(
    {
        "point": MappingProxyType({"x": (0.5,), "y": (0.5,)}),
        "line": MappingProxyType({"x": (0.2, 0.8), "y": (0.2, 0.8)}),
        "path": MappingProxyType({"x": (0.2, 0.8), "y": (0.2, 0.8)}),
        "smooth": MappingProxyType({"x": (0.2, 0.8), "y": (0.2, 0.8)}),
        "bar": MappingProxyType({"xmin": (0.0,), "xmax": (1.0,), "ymin": (0.0,), "ymax": (1.0,)}),
        "col": MappingProxyType({"xmin": (0.0,), "xmax": (1.0,), "ymin": (0.0,), "ymax": (1.0,)}),
        "histogram": MappingProxyType(
            {"xmin": (0.0,), "xmax": (1.0,), "ymin": (0.0,), "ymax": (1.0,)}
        ),
        "area": MappingProxyType({"x": (0.0, 1.0), "ymin": (0.0, 0.0), "ymax": (0.0, 1.0)}),
        "boxplot": MappingProxyType(
            {
                "x": (0.5,),
                "xmin": (0.2,),
                "xmax": (0.8,),
                "ymin": (0.1,),
                "lower": (0.3,),
                "middle": (0.5,),
                "upper": (0.7,),
                "ymax": (0.9,),
            }
        ),
        # M2-7 长尾 B：文本 / 点 / 分布 / 2D 族
        "text": MappingProxyType({"x": (0.5,), "y": (0.5,)}),
        "label": MappingProxyType({"x": (0.5,), "y": (0.5,)}),
        "jitter": MappingProxyType({"x": (0.5,), "y": (0.5,)}),
        "count": MappingProxyType({"x": (0.5,), "y": (0.5,)}),
        "qq": MappingProxyType({"x": (0.5,), "y": (0.5,)}),
        "density": MappingProxyType({"x": (0.0, 1.0), "ymin": (0.0, 0.0), "ymax": (0.0, 1.0)}),
        "contour": MappingProxyType({"x": (0.2, 0.8), "y": (0.2, 0.8)}),
        "density_2d": MappingProxyType({"x": (0.2, 0.8), "y": (0.2, 0.8)}),
        "density2d": MappingProxyType({"x": (0.2, 0.8), "y": (0.2, 0.8)}),
        "qq_line": MappingProxyType({"x": (0.2, 0.8), "y": (0.2, 0.8)}),
        "quantile": MappingProxyType({"x": (0.2, 0.8), "y": (0.2, 0.8)}),
        "function": MappingProxyType({"x": (0.2, 0.8), "y": (0.2, 0.8)}),
        "bin2d": MappingProxyType({"xmin": (0.0,), "xmax": (1.0,), "ymin": (0.0,), "ymax": (1.0,)}),
        "bin_2d": MappingProxyType(
            {"xmin": (0.0,), "xmax": (1.0,), "ymin": (0.0,), "ymax": (1.0,)}
        ),
        "hex": MappingProxyType({"x": (0.5,), "y": (0.5,), "width": (1.0,), "height": (1.0,)}),
        "dotplot": MappingProxyType(
            {"x": (0.5,), "y": (0.5,), "binwidth": (0.5,), "stackpos": (0.0,)}
        ),
        "violin": MappingProxyType(
            {
                "x": (0.5, 0.5, 0.5),
                "y": (0.0, 0.5, 1.0),
                "violinwidth": (0.0, 0.5, 0.0),
                "xmin": (0.2, 0.2, 0.2),
                "xmax": (0.8, 0.8, 0.8),
                "width": (0.6, 0.6, 0.6),
            }
        ),
        "contour_filled": MappingProxyType({"x": (0.0, 1.0, 1.0, 0.0), "y": (0.0, 0.0, 1.0, 1.0)}),
        "density_2d_filled": MappingProxyType(
            {"x": (0.0, 1.0, 1.0, 0.0), "y": (0.0, 0.0, 1.0, 1.0)}
        ),
        "density2d_filled": MappingProxyType(
            {"x": (0.0, 1.0, 1.0, 0.0), "y": (0.0, 0.0, 1.0, 1.0)}
        ),
        # --- M2-S2：模板照各 geom 的 `draw_key_*` ---------------------------
        # 线段族：0.1 → 0.9 的一道横线（R 的 `draw_key_path` / `draw_key_vpath`）。
        **{
            name: MappingProxyType({"x": (0.1,), "y": (0.5,), "xend": (0.9,), "yend": (0.5,)})
            for name in ("abline", "hline", "vline", "segment", "curve", "spoke", "step")
        },
        # 矩形族：整个 key 格（R 的 `draw_key_rect` / `draw_key_polygon`）。
        **{
            name: MappingProxyType({"xmin": (0.0,), "xmax": (1.0,), "ymin": (0.0,), "ymax": (1.0,)})
            for name in ("rect", "tile", "raster")
        },
        "polygon": MappingProxyType({"x": (0.0, 0.0, 1.0, 1.0), "y": (0.0, 1.0, 1.0, 0.0)}),
        "ribbon": MappingProxyType({"x": (0.0, 1.0), "ymin": (0.0, 0.0), "ymax": (0.0, 1.0)}),
        # 区间族：errorbar 是横线（R 的 `draw_key_errorbar` → `draw_key_vpath`），
        # linerange 是竖线，pointrange 再加一个中点，crossbar 是一个窄箱。
        "errorbar": MappingProxyType(
            {
                "xmin": (0.1,),
                "xmax": (0.9,),
                "x": (0.5,),
                "ymin": (0.5,),
                "ymax": (0.5,),
            }
        ),
        "errorbarh": MappingProxyType(
            {
                "xmin": (0.1,),
                "xmax": (0.9,),
                "x": (0.5,),
                "ymin": (0.5,),
                "ymax": (0.5,),
            }
        ),
        "linerange": MappingProxyType({"x": (0.5,), "ymin": (0.1,), "ymax": (0.9,)}),
        "pointrange": MappingProxyType({"x": (0.5,), "y": (0.5,), "ymin": (0.1,), "ymax": (0.9,)}),
        "crossbar": MappingProxyType(
            {
                "xmin": (0.1,),
                "xmax": (0.9,),
                "x": (0.5,),
                "y": (0.5,),
                "ymin": (0.25,),
                "ymax": (0.75,),
            }
        ),
        "rug": MappingProxyType({"x": (0.1, 0.5, 0.9), "y": (0.1, 0.5, 0.9)}),
        "blank": MappingProxyType({"x": (0.5,), "y": (0.5,)}),
    }
)


def _is_mapped_aesthetic(mapping: Mapping[str, Any] | None, name: str) -> bool:
    """该美学是否被**标度映射**（而不是图层上的常量）。

    `aes(colour = "g")` 是映射；`aes(colour = 0.5)` 这类非字符串常量不算。
    """
    if not mapping or name not in mapping:
        return False
    return not parse_aes(mapping[name]).constant


def _missing_column(kind: str, nrows: int) -> Column:
    """全 NA 列：用「缺失」表示这个美学不属于当前 guide。"""
    if kind == "str":
        return Column(
            "str",
            np.array([""] * nrows, dtype=object),
            na_mask=np.ones(nrows, dtype=bool),
        )
    return Column("float", np.full(nrows, np.nan), na_mask=np.ones(nrows, dtype=bool))


def key_table(
    layer: LayerBuild,
    values: Mapping[str, Any],
    geom: str,
    *,
    mapping: Mapping[str, Any] | None = None,
) -> ColumnTable:
    """一个图例键的假数据表：几何模板 + 图层的常量美学 + 键的映射值。

    位置列由 :data:`_GEOM_KEYS` 的模板铺满 key 视口；其余美学取图层数据的第一行
    （常量 `geom_point(colour="red")` 因此能带进图例），再用键值覆盖被 guide 管理
    的那几列。`Geom.draw()` 拿到它与 0..1 的 key 面板就能画出和面板里一致的图形。

    `mapping` 是该图层的 `raw_mappings`：**只有常量美学能带进 key**。被标度映射、
    但不由这张 guide 管理的美学要省略——`colour` / `fill` 置成全 NA，其余用几何
    默认值。否则 `colour = cyl, fill = gear` 时 colour 图例的键会被灌进第一行的
    `fill`（R：colour 图例的圆只有 stroke，fill 图例的圆只有 fill）。
    """
    template = _GEOM_KEYS.get(geom)
    if template is None:
        raise GuideError(
            f"geom_{geom} 没有图例 key 模板（已实现：{', '.join(sorted(_GEOM_KEYS))}）；"
            "见 docs/notes/guide.md「未实现」"
        )
    nrows = len(next(iter(template.values())))
    columns: dict[str, Column] = {}
    managed = set(values)
    for name in _AES_COLUMNS:
        if name in managed:
            # 本 guide 的键值在下面统一写入。
            continue
        if _is_mapped_aesthetic(mapping, name):
            if name in ("colour", "fill") and name in layer.data:
                columns[name] = _missing_column(layer.data.column(name).kind, nrows)
            continue
        if name not in layer.data or layer.data.nrows == 0:
            continue
        first = _first_value(layer.data, name)
        if first is None:
            continue
        if isinstance(first, str):
            columns[name] = Column("str", np.array([first] * nrows, dtype=object))
        elif isinstance(first, bool):
            columns[name] = Column("bool", np.array([first] * nrows, dtype=bool))
        else:
            columns[name] = Column("float", np.full(nrows, float(first), dtype=np.float64))
    for name, value in values.items():
        if isinstance(value, str):
            columns[name] = Column("str", np.array([value] * nrows, dtype=object))
        elif isinstance(value, bool):
            columns[name] = Column("bool", np.array([value] * nrows, dtype=bool))
        else:
            number = float(value)
            columns[name] = Column("float", np.full(nrows, number, dtype=np.float64))
    for name, numbers in template.items():
        columns[name] = Column("float", np.array(numbers, dtype=np.float64))
    if geom == "boxplot":
        columns["flipped_aes"] = Column("bool", np.zeros(nrows, dtype=bool))
        columns["outliers"] = Column("float", np.full(nrows, np.nan))
    if geom in ("text", "label") and "label" not in columns:
        # R 的 `draw_key_text` / `draw_key_label` 用 "a" 作键标签。
        columns["label"] = Column("str", np.array(["a"] * nrows, dtype=object))
    return ColumnTable(list(columns.items()), nrows=nrows)


def _first_value(table: ColumnTable, name: str) -> Any:
    column = table.column(name)
    if column.size == 0:
        return None
    mask = np.asarray(column.na_mask, dtype=bool)
    if bool(mask[0]):
        return None
    value = np.asarray(column.values)[0]
    if isinstance(value, np.generic):
        value = value.item()
    return value


def _key_grob(
    build: PlotBuild,
    layer_index: int,
    values: Mapping[str, Any],
    *,
    override: Mapping[str, Any] | None = None,
    size_cm: tuple[float, float] | None = None,
) -> Any | None:
    layer = build.layers[layer_index]
    geom = _geom_of(layer)
    # R：键值先写，`override.aes` 最后 `modify_list()` —— 覆盖值赢。
    resolved = {**dict(values), **dict(override or {})}
    glyph = key_glyph_for(layer)
    if glyph is None:
        glyph = default_key_glyph(geom.name)
    if glyph is not None:
        if size_cm is None:
            raw_theme = build.theme
            theme = raw_theme if hasattr(raw_theme, "get") else resolve_theme(raw_theme)
            size = _key_size(theme, GuideLegend())
        else:
            size = size_cm
        drawn = draw_key(glyph, resolved, layer.params, size[1] * 10.0)
        if isinstance(drawn, KeyGlyph):
            drawn = drawn.grob
        if isinstance(drawn, (NullGrob, ZeroGrob)):
            return None
        return drawn
    table = key_table(
        layer,
        resolved,
        geom.name,
        mapping=_layer_mapping(build, layer_index),
    )
    key_layer = replace(layer, data=table)
    grob = geom.draw(key_layer, _KeyPanel(), build.coord, build.theme, build.metrics)
    if isinstance(grob, (NullGrob, ZeroGrob)):
        return None
    return grob


class _KeyPanel:
    """0..1 的假面板：`PanelParams` 的 `transform()` 对等物（key 数据坐标即 npc）。"""

    x_range = (0.0, 1.0)
    y_range = (0.0, 1.0)
    x_limits = (0.0, 1.0)
    y_limits = (0.0, 1.0)

    #: 线性 / 不翻转 / 不极坐标：geom 的 `npc_values()` 需要的三个能力。
    flipped = False
    polar = None
    trans: Mapping[str, Any] = {}

    def transform(self, column: Column, aesthetic: str = "x") -> Column:
        values = np.asarray(column.values, dtype=np.float64)
        mask = np.asarray(column.na_mask, dtype=bool)
        out = values.copy()
        out[mask] = 0.0
        return Column("float", out, na_mask=mask)

    def transform_column(self, table: Any, name: str, axis: str) -> Column:
        """key 数据坐标本来就是 0..1，直接原样返回（`PanelParams` 的对等物）。"""
        return self.transform(table.column(name), axis)

    @property
    def is_linear(self) -> bool:
        return True

    def project_xy(self, xs: Any, ys: Any) -> tuple[np.ndarray, np.ndarray]:
        """线性面板：数据坐标即 npc（`munch_xy()` / 几何的 `project_xy()` 对等物）。"""
        return (
            np.asarray(xs, dtype=np.float64),
            np.asarray(ys, dtype=np.float64),
        )

    def position_of(self, axis: str, value: float) -> float:
        return float(value)

    def backtransform_range(self) -> dict[str, tuple[float, float]]:
        return {"x": self.x_range, "y": self.y_range}


def _geom_of(layer: LayerBuild) -> Any:
    geom = getattr(layer, "geom_object", None)
    if geom is None:
        raise GuideError(f"layer[{layer.index}] 没有 geom 对象，无法画图例 key")
    return geom


# ---------------------------------------------------------------------------
# 尺寸
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Box:
    x_cm: float
    y_cm: float
    width_cm: float
    height_cm: float

    @property
    def top(self) -> float:
        return self.y_cm + self.height_cm

    @property
    def right(self) -> float:
        return self.x_cm + self.width_cm


def _cm_unit(value: Any, *, height: bool) -> float:
    if value is None:
        return 0.0
    try:
        convert = convert_height if height else convert_width
        return float(np.asarray(convert(value, "cm", ctx=UnitContext())).sum())
    except Exception as exc:  # pragma: no cover - 主题单位不合法时点名词条
        raise GuideError(f"guide 的尺寸单位无法换算成 cm：{value!r}（{exc}）") from None


def _key_size(theme: ResolvedTheme, guide: Guide) -> tuple[float, float]:
    width = _cm_unit(theme.get("legend.key.width"), height=False)
    height = _cm_unit(theme.get("legend.key.height"), height=True)
    override_w = getattr(guide, "keywidth", None)
    override_h = getattr(guide, "keyheight", None)
    if override_w is not None:
        width = _cm_unit(override_w, height=False)
    if override_h is not None:
        height = _cm_unit(override_h, height=True)
    if width <= 0 or height <= 0:
        raise GuideError("legend.key.width / legend.key.height 解析为 0，图例 key 没有尺寸")
    return width, height


def _key_dimensions(
    guide_build: GuideBuild,
    theme: ResolvedTheme,
    guide: Guide,
) -> tuple[tuple[float, float], ...]:
    """逐键的 `(宽, 高)` cm（R `set_key_size()` + `build_decor()` 的 max 口径）。

    key 的尺寸先取主题的 `legend.key.size`；`size` / `linewidth` 标度把键撑到
    `(size + linewidth) / 10` cm；`key_glyph` 自己带 `width` / `height` 时取更大者。
    """
    base_w, base_h = _key_size(theme, guide)
    out: list[tuple[float, float]] = []
    for key in guide_build.keys:
        width, height = base_w, base_h
        size = key.values.get("size")
        linewidth = key.values.get("linewidth")
        try:
            size_mm = 0.0 if size is None or size is NA else float(size)
            line_mm = 0.0 if linewidth is None or linewidth is NA else float(linewidth)
        except (TypeError, ValueError):
            size_mm = line_mm = 0.0
        if size_mm > 0 or line_mm > 0:
            bump = (size_mm + line_mm) / 10.0
            width = max(width, bump)
            height = max(height, bump)
        for glyph in guide_build.key_glyphs:
            if glyph is None:
                continue
            try:
                drawn = draw_key(glyph, dict(key.values), {}, base_h * 10.0)
            except Exception:
                continue
            if isinstance(drawn, KeyGlyph):
                if drawn.width_cm is not None:
                    width = max(width, float(drawn.width_cm))
                if drawn.height_cm is not None:
                    height = max(height, float(drawn.height_cm))
        out.append((width, height))
    return tuple(out)


def _text_element(theme: ResolvedTheme, name: str) -> ElementText:
    element = theme.get(name)
    if isinstance(element, ElementText):
        return element
    if isinstance(element, ElementBlank):
        return ElementText(size=0.0, colour=NA)
    return ElementText(size=11.0, colour="#000000")


def _text_footprint(
    text: str,
    size: float,
    element: ElementText,
    metrics: Any,
) -> tuple[float, float]:
    """一段图例文字的外接尺寸（cm）：`angle = 90 / 270` 时宽高互换。

    R 在 gtable 里量的是**旋转后**的 grob（`legend.text` 竖排时宽 = 行高、
    高 = 字符串长度），以前这里只量不旋转的那一版，竖排标签的列宽会大出一整条
    字符串的宽度（SIL-788 的 rotated guide titles and labels）。
    """
    width = text_width_cm(text, size, metrics, element.family or "")
    height = text_line_cm(size)
    angle = float(getattr(element, "angle", 0.0) or 0.0)
    if round(angle) % 180 == 90:
        return height, width
    return width, height


def legend_direction(guide: Guide, position: str | None, theme: ResolvedTheme | None = None) -> str:
    """键的排布方向：guide 的 `direction` > 主题 `legend.direction` > 方位默认。

    R 4.0.3 的 `Guide$setup_params()`：`params$direction <- params$direction %||%
    theme$legend.direction %||% (position %in% c("top", "bottom") ? "horizontal" :
    "vertical")`。主题这一档以前漏了，`theme(legend.direction = ...)` 因此不生效
    （SIL-788）。
    """
    explicit = getattr(guide, "direction", None)
    if explicit is not None:
        return explicit
    if theme is not None:
        value = theme.get("legend.direction")
        if isinstance(value, str) and value in ("horizontal", "vertical"):
            return value
    return "horizontal" if position in ("top", "bottom") else "vertical"


def legend_text_position(guide: Guide, theme: ResolvedTheme) -> str:
    """标签相对 key 的位置：逐 guide 覆盖 > `legend.text.position` > "right"。"""
    explicit = getattr(guide, "label_position", None)
    if explicit is None:
        explicit = theme.get("legend.text.position")
    if explicit is None:
        return "right"
    if explicit not in ("top", "bottom", "left", "right"):
        raise GuideError(
            f"legend.text.position 只能是 top / bottom / left / right，收到 {explicit!r}"
        )
    return str(explicit)


def legend_title_position(guide: Guide, theme: ResolvedTheme, direction: str) -> str:
    """标题位置：逐 guide 覆盖 > `legend.title.position` > 竖排 top / 横排 left。"""
    explicit = getattr(guide, "title_position", None)
    if explicit is None:
        explicit = theme.get("legend.title.position")
    if explicit is None:
        return "top" if direction == "vertical" else "left"
    if explicit not in ("top", "bottom", "left", "right"):
        raise GuideError(
            f"legend.title.position 只能是 top / bottom / left / right，收到 {explicit!r}"
        )
    return str(explicit)


def _grid_shape(guide: Guide, n: int, direction: str) -> tuple[int, int, bool]:
    """键的 nrow × ncol 网格（R `GuideLegend$setup_params()` 的默认值）。

    R 4.0.3 在未给 nrow / ncol 时：横排最多 5 列（`nrow = ceil(n / 5)`），竖排
    最多 20 行（`ncol = ceil(n / 20)`）；`byrow` 取 `legend.byrow`（默认 FALSE）。
    """
    nrow = getattr(guide, "nrow", None)
    ncol = getattr(guide, "ncol", None)
    byrow = bool(getattr(guide, "byrow", False))
    if nrow is None and ncol is None:
        if direction == "horizontal":
            nrow = max(1, int(np.ceil(n / 5)))
        else:
            ncol = max(1, int(np.ceil(n / 20)))
    if nrow is None:
        assert ncol is not None
        nrow = max(1, int(np.ceil(n / ncol)))
    elif ncol is None:
        ncol = max(1, int(np.ceil(n / nrow)))
    if int(nrow) * int(ncol) < n:
        # R：`nrow * ncol needs to be larger than the number of legend keys`。
        raise GuideError(
            f"guide_legend(nrow={nrow}, ncol={ncol}) 放不下 {n} 个键；nrow * ncol 至少要 ≥ {n}"
        )
    return int(nrow), int(ncol), byrow


@dataclass(frozen=True, slots=True)
class LegendLayout:
    """一张图例的布局：外框尺寸 + 每个 key / 标签 / 标题的位置（局部 cm，y 向上）。

    `col_widths_cm` / `row_heights_cm` 是**照 R 的 gtable 分解**给出的列宽 / 行高
    （含 padding 与标题占位；标签侧的 `legend.key.spacing` 折进标签列/行，
    与 R 的 `measure_grobs()` 一致）。两者之和就是 `width_cm` / `height_cm`。
    """

    width_cm: float
    height_cm: float
    direction: str
    title_box: _Box | None = None
    subtitle_box: _Box | None = None
    keys: tuple[LegendKeyCell, ...] = ()
    bar: _Box | None = None
    ticks: tuple[tuple[float, str], ...] = ()
    col_widths_cm: tuple[float, ...] = ()
    row_heights_cm: tuple[float, ...] = ()
    label_position: str = "right"
    title_position: str | None = None
    title_hjust: float = 0.0
    title_vjust: float = 0.5
    #: `guide_custom()` 的内容矩形（其它 guide 为 None）。
    content_box: _Box | None = None


@dataclass(frozen=True, slots=True)
class LegendKeyCell:
    key: GuideKey
    box: _Box
    label_box: _Box


@dataclass(frozen=True, slots=True)
class LegendBoxLayout:
    """图例盒（`guide-box`）的布局：一个方位上的所有图例怎么排成行列。

    对齐 R 4.0.3 的 `Guides$package_box()`：

    - `legend.box`（默认：竖排 / 横排随方位）决定 `gtable_col` 还是 `gtable_row`；
    - `legend.box.just`（竖排默认 `left`，横排默认 `center`）决定每个图例在
      盒内的横向对齐；`legend.spacing.x/y` 是图例之间的间隔；
    - `legend.box.margin` 是盒的内边距。

    `boxes` 是每张图例在盒内的局部矩形（cm，y 向上），顺序同传进来的 layouts。
    """

    position: str
    direction: str
    width_cm: float
    height_cm: float
    col_widths_cm: tuple[float, ...]
    row_heights_cm: tuple[float, ...]
    boxes: tuple[_Box, ...]


def _justification(theme: ResolvedTheme, position: str) -> tuple[float, float]:
    """`legend.justification.<position>`（缺省继承 `legend.justification`）。"""
    value = theme.get(f"legend.justification.{position}")
    if value is None:
        value = theme.get("legend.justification")
    return _valid_just(value, default=(0.5, 0.5))


def _valid_just(value: Any, *, default: tuple[float, float]) -> tuple[float, float]:
    if value is None:
        return default
    if isinstance(value, str):
        mapping = {
            "left": (0.0, 0.5),
            "right": (1.0, 0.5),
            "top": (0.5, 1.0),
            "bottom": (0.5, 0.0),
            "center": (0.5, 0.5),
            "centre": (0.5, 0.5),
            "topleft": (0.0, 1.0),
            "topright": (1.0, 1.0),
            "bottomleft": (0.0, 0.0),
            "bottomright": (1.0, 0.0),
        }
        return mapping.get(value.lower(), default)
    try:
        items = list(value)
    except TypeError:
        return default
    if len(items) == 1:
        return (float(items[0]), float(items[0]))
    if len(items) >= 2:
        return (float(items[0]), float(items[1]))
    return default


def _box_just(theme: ResolvedTheme, direction: str) -> tuple[float, float]:
    """`legend.box.just`：竖排默认 `(left, top)`，横排默认 `(center, top)`。"""
    value = theme.get("legend.box.just")
    if value is not None:
        return _valid_just(value, default=(0.0, 1.0))
    if direction == "horizontal":
        return (0.5, 1.0)
    return (0.0, 1.0)


def legend_box_direction(theme: ResolvedTheme, position: str) -> str:
    explicit = theme.get("legend.box")
    if explicit in ("vertical", "horizontal"):
        return str(explicit)
    return "horizontal" if position in ("top", "bottom") else "vertical"


def legend_box_layout(
    layouts: Sequence[LegendLayout],
    position: str,
    theme: ResolvedTheme,
) -> LegendBoxLayout:
    """把同一方位的图例排成一个 `guide-box`（R `Guides$package_box()`）。"""
    direction = legend_box_direction(theme, position)
    mt, mr, mb, ml = margin_sides_cm(theme.get("legend.box.margin"))
    gap = _cm_unit(theme.get("legend.spacing"), height=True) or _cm_unit(
        theme.get("legend.spacing.y"), height=True
    )
    gap_x = _cm_unit(theme.get("legend.spacing.x"), height=False) or gap
    gap_y = _cm_unit(theme.get("legend.spacing.y"), height=True) or gap
    box_xjust, box_yjust = _box_just(theme, direction)
    sizes = list(layouts)
    if direction == "horizontal":
        total_h = max((item.height_cm for item in sizes), default=0.0)
        height = total_h + mt + mb
        col_widths = [ml]
        for index, item in enumerate(sizes):
            if index:
                col_widths.append(gap_x)
            col_widths.append(item.width_cm)
        col_widths.append(mr)
        row_heights = [mt, total_h, mb]
        boxes: list[_Box] = []
        x = ml
        for index, item in enumerate(sizes):
            if index:
                x += gap_x
            boxes.append(
                _Box(
                    x,
                    mt + (total_h - item.height_cm) * box_yjust,
                    item.width_cm,
                    item.height_cm,
                )
            )
            x += item.width_cm
    else:
        total_w = max((item.width_cm for item in sizes), default=0.0)
        height = sum(item.height_cm for item in sizes) + gap_y * max(0, len(sizes) - 1) + mt + mb
        row_heights = [mt]
        for index, item in enumerate(sizes):
            if index:
                row_heights.append(gap_y)
            row_heights.append(item.height_cm)
        row_heights.append(mb)
        col_widths = [ml, total_w, mr]
        boxes = []
        top = height - mt
        for item in sizes:
            y = top - item.height_cm
            boxes.append(
                _Box(
                    ml + (total_w - item.width_cm) * box_xjust,
                    y,
                    item.width_cm,
                    item.height_cm,
                )
            )
            top = y - gap_y
    return LegendBoxLayout(
        position=position,
        direction=direction,
        width_cm=float(sum(col_widths)),
        height_cm=float(sum(row_heights)),
        col_widths_cm=tuple(col_widths),
        row_heights_cm=tuple(row_heights),
        boxes=tuple(boxes),
    )


def guide_theme(theme: ResolvedTheme, guide: Any) -> ResolvedTheme:
    """把 guide 自己的 `theme=` 覆到 plot 主题上（R 4.0.3 的 `guide$theme`）。

    R 在 `guide$draw()` 里按 `plot_theme %+% guide$theme` 给**这一张**图例算元素，
    不影响其它图例；`merge_theme()` 的语义与 `%+%` 一致（override 优先）。
    """
    extra = getattr(guide, "theme", None)
    if extra is None:
        return theme
    base = getattr(theme, "theme", None)
    if base is None:
        return theme
    return resolve_theme(merge_theme(base, extra), getattr(theme, "metrics", None))


def legend_layout(
    guide_build: GuideBuild,
    theme: ResolvedTheme,
    position: str | None = None,
    *,
    metrics: Any = None,
) -> LegendLayout:
    """一张图例的尺寸与内部格位（cm；不含外部的 `legend.box.spacing`）。"""
    guide = guide_build.guide
    theme = guide_theme(theme, guide)
    direction = legend_direction(guide, position, theme)
    padding = margin_sides_cm(theme.get("legend.margin"))
    pad_t, pad_r, pad_b, pad_l = padding
    title_el = _text_element(theme, "legend.title")
    text_el = _text_element(theme, "legend.text")
    title_size = float(title_el.size or 0.0)
    text_size = float(text_el.size or 0.0)
    gap = _cm_unit(theme.get("legend.key.spacing"), height=True)
    if gap == 0.0:
        gap = _cm_unit(theme.get("legend.key.spacing.y"), height=True)
    spacing_x = _cm_unit(theme.get("legend.key.spacing.x"), height=False) or gap
    spacing_y = (
        0.0
        if direction == "vertical"
        else (_cm_unit(theme.get("legend.key.spacing.y"), height=True))
    )
    title_line = text_line_cm(title_size) if guide_build.title else 0.0
    title_w = (
        text_width_cm(guide_build.title or "", title_size, metrics, title_el.family or "")
        if guide_build.title
        else 0.0
    )

    if isinstance(guide, GuideCustom):
        return _custom_layout(
            guide_build,
            theme,
            direction=direction,
            padding=padding,
            gap=gap,
            title_el=title_el,
            metrics=metrics,
        )

    if isinstance(guide, GuideColourbar):
        title_line = text_line_cm(title_size) if guide_build.title else 0.0
        title_h = title_line + gap if guide_build.title else 0.0
        title_w = (
            text_width_cm(guide_build.title or "", title_size, metrics, title_el.family or "")
            if guide_build.title
            else 0.0
        )
        return _colourbar_layout(
            guide_build,
            theme,
            direction=direction,
            padding=padding,
            title_line=title_line,
            title_w=title_w,
            spacing_x=spacing_x,
            text_el=text_el,
            metrics=metrics,
        )
    if isinstance(guide, GuideColoursteps):
        return _steps_layout(
            guide_build,
            theme,
            direction=direction,
            padding=padding,
            title_line=title_line,
            title_w=title_w,
            spacing_x=spacing_x,
            text_el=text_el,
            metrics=metrics,
        )
    if isinstance(guide, GuideBins):
        return _bins_layout(
            guide_build,
            theme,
            direction=direction,
            padding=padding,
            title_line=title_line,
            title_w=title_w,
            spacing_x=spacing_x,
            text_el=text_el,
            metrics=metrics,
        )

    text_position = legend_text_position(guide, theme)
    title_position = legend_title_position(guide, theme, direction)
    n = len(guide_build.keys)
    key_dims = _key_dimensions(guide_build, theme, guide)
    nrow, ncol, byrow = _grid_shape(guide, n, direction)

    # --- 标签 / 标题的文字盒（R：legend.text / legend.title 的 margin + gap）---
    mt, mr, mb, ml = margin_sides_cm(text_el.margin)
    label_footprints = [
        _text_footprint(key.label, text_size, text_el, metrics) for key in guide_build.keys
    ]
    label_text_w = [width for width, _height in label_footprints]
    label_text_h = max(
        (height for _width, height in label_footprints), default=text_line_cm(text_size)
    )
    if text_position == "right":
        label_w = [ml + value + mr + gap for value in label_text_w]
        label_h = mt + label_text_h + mb
        label_pad_x = gap
    elif text_position == "left":
        label_w = [ml + value + mr + gap for value in label_text_w]
        label_h = mt + label_text_h + mb
        label_pad_x = 0.0
    else:
        label_w = [ml + value + mr for value in label_text_w]
        label_h = mt + label_text_h + mb + gap
        label_pad_x = 0.0

    tmt, tmr, tmb, tml = margin_sides_cm(title_el.margin)
    if guide_build.title:
        title_text_w, title_text_h = _text_footprint(
            guide_build.title, title_size, title_el, metrics
        )
    else:
        title_text_w, title_text_h = 0.0, 0.0
    if title_position == "top":
        title_w = tml + title_text_w + tmr
        title_h = tmt + title_text_h + tmb + gap
    elif title_position == "bottom":
        title_w = tml + title_text_w + tmr
        title_h = tmt + gap + title_text_h + tmb
    elif title_position == "left":
        title_w = tml + title_text_w + tmr + gap
        title_h = tmt + title_text_h + tmb
    else:
        title_w = tml + gap + title_text_w + tmr
        title_h = tmt + title_text_h + tmb
    if not guide_build.title:
        title_w = 0.0
        title_h = 0.0

    subtitle_text = getattr(guide, "subtitle", None)
    subtitle_h = 0.0
    if guide_build.title and subtitle_text:
        smt, _smr, smb, _sml = margin_sides_cm(text_el.margin)
        subtitle_h = smt + text_line_cm(text_size) + smb

    # --- 键网格：列宽 / 行高（R `measure_grobs()` 的 interleave 口径）---
    cells: list[tuple[int, int, int]] = []
    for index in range(n):
        if byrow:
            row = index // ncol
            col = index % ncol
        else:
            row = index % nrow
            col = index // nrow
        cells.append((row, col, index))

    col_label = [0.0] * ncol
    row_label = [0.0] * nrow
    key_w = [0.0] * ncol
    key_h = [0.0] * nrow
    for row, col, index in cells:
        col_label[col] = max(col_label[col], label_w[index])
        width, height = key_dims[index] if index < len(key_dims) else (0.0, 0.0)
        key_w[col] = max(key_w[col], width)
        key_h[row] = max(key_h[row], height)
        # R 把 key 与标签放进同一个 gtable 行：行高 = max(key 高度, 标签高度)。
        # 字号放大到 key 比文字还矮时（`base_size = 33` 的 `theme_bw` 族），
        # 行高必须跟着文字走，否则图例整体会比上游矮一截。
        row_label[row] = max(row_label[row], label_h)

    grid_cols: list[float] = []
    key_col_index: list[int] = []
    label_col_index: list[int] = []
    if text_position == "right":
        for col in range(ncol):
            if col > 0:
                grid_cols.append(spacing_x)  # 组间 gap（标签自身的 gap 折在标签列里）
            key_col_index.append(len(grid_cols))
            grid_cols.append(key_w[col])
            label_col_index.append(len(grid_cols))
            grid_cols.append(col_label[col])
    elif text_position == "left":
        for col in range(ncol):
            if col > 0:
                grid_cols.append(spacing_x)
            label_col_index.append(len(grid_cols))
            grid_cols.append(col_label[col])
            key_col_index.append(len(grid_cols))
            grid_cols.append(key_w[col])
    else:
        for col in range(ncol):
            if col > 0:
                grid_cols.append(spacing_x)
            key_col_index.append(len(grid_cols))
            grid_cols.append(max(key_w[col], col_label[col]))

    grid_rows: list[float] = []
    key_row_index: list[int] = []
    label_row_index: list[int] = []
    if text_position in ("top", "bottom"):
        for row in range(nrow):
            if row > 0:
                grid_rows.append(spacing_y)
            if text_position == "top":
                label_row_index.append(len(grid_rows))
                grid_rows.append(row_label[row])
                key_row_index.append(len(grid_rows))
                grid_rows.append(key_h[row])
            else:
                key_row_index.append(len(grid_rows))
                grid_rows.append(key_h[row])
                label_row_index.append(len(grid_rows))
                grid_rows.append(row_label[row])
    else:
        for row in range(nrow):
            if row > 0:
                grid_rows.append(spacing_y)
            key_row_index.append(len(grid_rows))
            grid_rows.append(max(key_h[row], row_label[row]))

    # --- 标题占位 + 额外宽度 / 高度（R `add_title()`）---
    left_cols: list[float] = []
    right_cols: list[float] = []
    top_rows: list[float] = []
    bottom_rows: list[float] = []
    if guide_build.title:
        if title_position == "top":
            top_rows.append(title_h)
            if subtitle_h > 0:
                top_rows.append(subtitle_h)
        elif title_position == "bottom":
            if subtitle_h > 0:
                bottom_rows.append(subtitle_h)
            bottom_rows.append(title_h)
        elif title_position == "left":
            left_cols.append(title_w)
        else:
            right_cols.append(title_w)
    if guide_build.title and title_position in ("top", "bottom"):
        content_w = sum(left_cols) + sum(grid_cols) + sum(right_cols)
        if title_w > content_w + 1e-12:
            extra = title_w - content_w
            hjust = _title_hjust(guide, title_el)
            left_cols.insert(0, (1.0 - hjust) * extra)
            right_cols.append(hjust * extra)
    if guide_build.title and title_position in ("left", "right"):
        content_h = sum(top_rows) + sum(grid_rows) + sum(bottom_rows)
        if title_h > content_h + 1e-12:
            extra = title_h - content_h
            vjust = _title_vjust(guide, title_el)
            top_rows.insert(0, (1.0 - vjust) * extra)
            bottom_rows.append(vjust * extra)

    col_widths = [pad_l, *left_cols, *grid_cols, *right_cols, pad_r]
    row_heights = [pad_t, *top_rows, *grid_rows, *bottom_rows, pad_b]
    width = float(sum(col_widths))
    height = float(sum(row_heights))

    col_x = [0.0]
    for value in col_widths[:-1]:
        col_x.append(col_x[-1] + value)
    row_y_top = [height]
    for value in row_heights[:-1]:
        row_y_top.append(row_y_top[-1] - value)

    grid_col_offset = 1 + len(left_cols)
    grid_row_offset = 1 + len(top_rows)

    def col_left(index: int) -> float:
        return col_x[grid_col_offset + index]

    def row_top(index: int) -> float:
        return row_y_top[grid_row_offset + index]

    key_cells: list[LegendKeyCell] = []
    key_just = _valid_just(theme.get("legend.key.justification"), default=(0.5, 0.5))
    has_key_just = theme.get("legend.key.justification") is not None
    for row, col, index in cells:
        cell_top = row_top(key_row_index[row])
        # key 与标签同处一个 gtable 行、都按中心对齐（R 的 `gtable` 缺省 vjust）：
        # 行高由两者中更高的一边决定，矮的一边在行内居中，而不是贴底。
        row_h = grid_rows[key_row_index[row]]
        cell_x = col_left(key_col_index[col])
        cell_w = grid_cols[key_col_index[col]]
        glyph_w, glyph_h = key_dims[index] if index < len(key_dims) else (cell_w, row_h)
        if has_key_just:
            # `legend.key.justification`：键按自己的尺寸锚在键格里（R 的 key
            # gTree 视口 `viewport(x = just, just = just)`）。
            key_box = _Box(
                cell_x + key_just[0] * (cell_w - glyph_w),
                cell_top - row_h + key_just[1] * (row_h - glyph_h),
                glyph_w,
                glyph_h,
            )
        else:
            key_box = _Box(cell_x, cell_top - row_h, cell_w, row_h)
        if text_position == "right":
            label_box = _Box(
                col_left(label_col_index[col]) + label_pad_x,
                cell_top - (row_h + label_h) / 2.0,
                label_text_w[index],
                label_h,
            )
        elif text_position == "left":
            label_box = _Box(
                col_left(label_col_index[col]) + label_pad_x,
                cell_top - (row_h + label_h) / 2.0,
                label_text_w[index],
                label_h,
            )
        elif text_position == "top":
            label_box = _Box(
                key_box.x_cm + (key_box.width_cm - label_text_w[index]) / 2.0,
                row_top(label_row_index[row]) - label_h,
                label_text_w[index],
                label_h,
            )
        else:
            label_box = _Box(
                key_box.x_cm + (key_box.width_cm - label_text_w[index]) / 2.0,
                row_top(label_row_index[row]) - label_h,
                label_text_w[index],
                label_h,
            )
        key_cells.append(LegendKeyCell(guide_build.keys[index], key_box, label_box))

    title_box = None
    if guide_build.title:
        if title_position == "top":
            title_box = _Box(pad_l, height - pad_t - title_h, width - pad_l - pad_r, title_h)
        elif title_position == "bottom":
            title_box = _Box(pad_l, pad_b, width - pad_l - pad_r, title_h)
        elif title_position == "left":
            title_box = _Box(pad_l, pad_b, title_w, height - pad_t - pad_b)
        else:
            title_box = _Box(width - pad_r - title_w, pad_b, title_w, height - pad_t - pad_b)
    subtitle_box = None
    if subtitle_h > 0:
        if title_position == "top":
            subtitle_box = _Box(
                pad_l,
                height - pad_t - title_h - subtitle_h,
                width - pad_l - pad_r,
                subtitle_h,
            )
        elif title_position == "bottom":
            subtitle_box = _Box(pad_l, pad_b + title_h, width - pad_l - pad_r, subtitle_h)
    return LegendLayout(
        width_cm=width,
        height_cm=height,
        direction=direction,
        title_box=title_box,
        subtitle_box=subtitle_box,
        keys=tuple(key_cells),
        col_widths_cm=tuple(col_widths),
        row_heights_cm=tuple(row_heights),
        label_position=text_position,
        title_position=title_position if guide_build.title else None,
        title_hjust=_title_hjust(guide, title_el),
        title_vjust=_title_vjust(guide, title_el),
    )


def _title_hjust(guide: Guide, element: ElementText) -> float:
    explicit = getattr(guide, "title_hjust", None)
    if explicit is not None:
        return float(explicit)
    return float(element.hjust if element.hjust is not None else 0.0)


def _title_vjust(guide: Guide, element: ElementText) -> float:
    explicit = getattr(guide, "title_vjust", None)
    if explicit is not None:
        return float(explicit)
    return float(element.vjust if element.vjust is not None else 0.5)


def _custom_layout(
    guide_build: GuideBuild,
    theme: ResolvedTheme,
    *,
    direction: str,
    padding: tuple[float, float, float, float],
    gap: float,
    title_el: ElementText,
    metrics: Any,
) -> LegendLayout:
    """`guide_custom()` 的盒子：内容尺寸 + 标题（位置同 legend）。"""
    guide = guide_build.guide
    assert isinstance(guide, GuideCustom)
    pad_t, pad_r, pad_b, pad_l = padding
    content_w = _cm_unit(guide.width, height=False) if guide.width is not None else 0.0
    content_h = _cm_unit(guide.height, height=True) if guide.height is not None else 0.0
    if content_w <= 0 or content_h <= 0:
        key_w, key_h = _key_size(theme, guide)
        content_w = content_w or key_w
        content_h = content_h or key_h
    title_size = float(title_el.size or 0.0)
    title_text_w = (
        text_width_cm(guide_build.title or "", title_size, metrics, title_el.family or "")
        if guide_build.title
        else 0.0
    )
    title_position = legend_title_position(guide, theme, direction)
    title_h = 0.0
    title_w = 0.0
    if guide_build.title:
        if title_position in ("top", "bottom"):
            title_h = text_line_cm(title_size) + gap
            title_w = title_text_w
        else:
            title_w = title_text_w + gap
            title_h = text_line_cm(title_size)
    width = max(content_w, title_w) + pad_l + pad_r
    height = content_h + title_h + pad_t + pad_b
    title_box = None
    if guide_build.title:
        if title_position == "top":
            title_box = _Box(pad_l, height - pad_t - title_h, width - pad_l - pad_r, title_h)
        elif title_position == "bottom":
            title_box = _Box(pad_l, pad_b, width - pad_l - pad_r, title_h)
        elif title_position == "left":
            title_box = _Box(pad_l, pad_b, title_w, height - pad_t - pad_b)
        else:
            title_box = _Box(width - pad_r - title_w, pad_b, title_w, height - pad_t - pad_b)
    content_y = pad_b + (title_h if title_position == "bottom" else 0.0)
    if title_position == "top":
        content_y = pad_b
    col_widths = [pad_l, content_w, pad_r]
    if guide_build.title and title_position == "top":
        row_heights = [pad_t, title_h, content_h, pad_b]
    elif guide_build.title and title_position == "bottom":
        row_heights = [pad_t, content_h, title_h, pad_b]
    elif guide_build.title and title_position == "left":
        row_heights = [pad_t, content_h, pad_b]
        col_widths = [pad_l, title_w, content_w, pad_r]
    elif guide_build.title:
        row_heights = [pad_t, content_h, pad_b]
        col_widths = [pad_l, content_w, title_w, pad_r]
    else:
        row_heights = [pad_t, content_h, pad_b]
    return LegendLayout(
        width_cm=width,
        height_cm=height,
        direction=direction,
        title_box=title_box,
        col_widths_cm=tuple(col_widths),
        row_heights_cm=tuple(row_heights),
        title_position=title_position if guide_build.title else None,
        title_hjust=_title_hjust(guide, title_el),
        title_vjust=_title_vjust(guide, title_el),
        content_box=_Box(
            pad_l + (title_w if title_position == "left" else 0.0),
            content_y,
            content_w,
            content_h,
        ),
    )


def _bar_size(
    guide: GuideColourbar, key_w: float, key_h: float, direction: str = "vertical"
) -> tuple[float, float]:
    """色条尺寸：长轴默认 5 × key，短轴默认 key（与 R 4.0.3 的 30×150 key 比例一致）。"""
    explicit_w = _cm_unit(guide.barwidth, height=False) if guide.barwidth is not None else None
    explicit_h = _cm_unit(guide.barheight, height=True) if guide.barheight is not None else None
    if direction == "horizontal":
        bar_w = explicit_w if explicit_w is not None else 5.0 * key_w
        bar_h = explicit_h if explicit_h is not None else key_h
    else:
        bar_w = explicit_w if explicit_w is not None else key_w
        bar_h = explicit_h if explicit_h is not None else 5.0 * key_h
    return bar_w, bar_h


def _bar_ticks(
    guide_build: GuideBuild,
    guide: GuideColourbar,
    box: _Box,
    direction: str,
) -> tuple[tuple[float, str], ...]:
    """刻度位置（竖向是 y、横向是 x；局部 cm）+ 标签。

    R 4.0.3 的 `extract_params()` 把键值重标到**箱心**：`(0.5, nbin - 0.5) / nbin`
    （`display = "gradient"` 时是 `(0, 1)`）。`reverse=TRUE` 再取 `1 - fraction`。
    `draw.llim = FALSE` / `draw.ulim = FALSE` 只去掉首 / 尾那根刻度和标签（R 的
    `build_ticks()` 在解出位置之后才删，键本身仍在 `get_guide_data()` 里）。
    """
    low, high = guide_build.limits if guide_build.limits is not None else (0.0, 1.0)
    span = float(high) - float(low)
    display = getattr(guide, "display", "raster")
    if display == "gradient":
        to_low, to_high = 0.0, 1.0
    else:
        nbin = int(guide.nbin or 300)
        to_low, to_high = 0.5 / nbin, (nbin - 0.5) / nbin
    ticks: list[tuple[float, str]] = []
    last = len(guide_build.keys) - 1
    for index, key in enumerate(guide_build.keys):
        if span == 0 or not isinstance(key.value, (int, float)):
            fraction = to_low
        else:
            fraction = to_low + (float(key.value) - float(low)) / span * (to_high - to_low)
        if guide.reverse:
            fraction = 1.0 - fraction
        if index == 0 and not guide.draw_llim:
            continue
        if index == last and not guide.draw_ulim:
            continue
        if direction == "horizontal":
            ticks.append((box.x_cm + fraction * box.width_cm, key.label))
        else:
            ticks.append((box.y_cm + fraction * box.height_cm, key.label))
    return tuple(ticks)


def _title_position_of(guide: Guide, direction: str) -> str:
    """`legend.title.position`：guide 显式 > 主题 > 方向默认（竖排 top / 横排 left）。"""
    explicit = getattr(guide, "title_position", None)
    if explicit in ("top", "bottom", "left", "right"):
        return explicit
    return "top" if direction == "vertical" else "left"


def _compose_title(
    content_w: float,
    content_h: float,
    *,
    padding: tuple[float, float, float, float],
    title_position: str,
    title_line: float,
    title_w: float,
    title: bool,
    gap: float = 0.0,
) -> tuple[float, float, _Box | None, float, float]:
    """内容块 + 标题 → `(总宽, 总高, 标题盒, 内容左下角 x, y)`（cm）。

    `gap` 是 `legend.key.spacing`：R 的 `position_margin()` 把它加在标题靠近内容
    的那一侧（`legend.title` 的 margin），所以标题占 `title_line + gap`。
    """
    pad_t, pad_r, pad_b, pad_l = padding
    if not title:
        return content_w + pad_l + pad_r, content_h + pad_t + pad_b, None, pad_l, pad_b
    if title_position == "top":
        height = title_line + gap + content_h + pad_t + pad_b
        width = max(content_w, title_w) + pad_l + pad_r
        box = _Box(pad_l, height - pad_t - title_line, title_w, title_line)
        return width, height, box, pad_l, pad_b
    if title_position == "bottom":
        height = title_line + gap + content_h + pad_t + pad_b
        width = max(content_w, title_w) + pad_l + pad_r
        box = _Box(pad_l, pad_b, title_w, title_line)
        return width, height, box, pad_l, pad_b + title_line + gap
    if title_position == "left":
        # 图例标题**从不旋转**（R 的 `Guide$setup_elements()` 只改 hjust / margin）：
        # 左 / 右标题是普通横排文字，列宽 = 文字宽 + 与内容的 gap。
        width = title_w + gap + content_w + pad_l + pad_r
        height = content_h + pad_t + pad_b
        box = _Box(pad_l, pad_b, title_w, title_line)
        return width, height, box, pad_l + title_w + gap, pad_b
    width = title_w + gap + content_w + pad_l + pad_r
    height = content_h + pad_t + pad_b
    box = _Box(pad_l + content_w + gap, pad_b, title_w, title_line)
    return width, height, box, pad_l, pad_b


def _label_width(guide_build: GuideBuild, text_el: ElementText, metrics: Any) -> float:
    size = float(text_el.size or 0.0)
    return max(
        (text_width_cm(key.label, size, metrics, text_el.family or "") for key in guide_build.keys),
        default=0.0,
    )


def _colourbar_layout(
    guide_build: GuideBuild,
    theme: ResolvedTheme,
    *,
    direction: str,
    padding: tuple[float, float, float, float],
    title_line: float,
    title_w: float,
    spacing_x: float,
    text_el: ElementText,
    metrics: Any,
) -> LegendLayout:
    guide = guide_build.guide
    assert isinstance(guide, GuideColourbar)
    key_w, key_h = _key_size(theme, guide)
    bar_w, bar_h = _bar_size(guide, key_w, key_h, direction)
    text_size = float(text_el.size or 0.0)
    label_w = _label_width(guide_build, text_el, metrics)
    label_row = text_line_cm(text_size)
    gap_row = _cm_unit(theme.get("legend.key.spacing"), height=True)
    if direction == "horizontal":
        content_w = bar_w
        content_h = bar_h + label_row + gap_row
    else:
        content_w = bar_w + spacing_x + label_w
        content_h = bar_h
    title = bool(guide_build.title)
    gap = _cm_unit(theme.get("legend.key.spacing"), height=True)
    width, height, title_box, cx, cy = _compose_title(
        content_w,
        content_h,
        padding=padding,
        title_position=_title_position_of(guide, direction),
        title_line=title_line,
        title_w=title_w,
        title=title,
        gap=gap,
    )
    bar_box = _Box(cx, cy if direction == "vertical" else cy + label_row, bar_w, bar_h)
    return LegendLayout(
        width_cm=width,
        height_cm=height,
        direction=direction,
        title_box=title_box,
        bar=bar_box,
        ticks=_bar_ticks(guide_build, guide, bar_box, direction),
        title_position=_title_position_of(guide, direction),
    )


def _step_ticks(
    guide_build: GuideBuild,
    box: _Box,
    direction: str,
    *,
    show_limits: tuple[bool, bool],
    reverse: bool,
    flip: bool = False,
) -> tuple[tuple[float, str], ...]:
    """分箱 guide 的边界刻度：`edges` 在 0..1 上的位置；两端按 `show.limits` 取舍。

    `flip=True` 是竖排 `guide_bins` 的口径：R 的 `GuideBins$build_labels()` 先做
    `1 - .value`，所以**低值在上**（与色条相反）。`reverse` 再整体翻一次，两者
    互抵（R 的 `extract_params()` 已经把 `.value` 翻过一遍）。
    """
    bins = guide_build.bins
    if bins is None:
        return ()
    low, high = bins.edges[0], bins.edges[-1]
    span = high - low
    fractions = [0.0] if span == 0 else [(edge - low) / span for edge in bins.edges]
    if flip != bool(reverse):
        fractions = [1.0 - value for value in fractions]
    last = len(bins.labels) - 1
    out: list[tuple[float, str]] = []
    for index, (fraction, label) in enumerate(zip(fractions, bins.labels, strict=True)):
        if (index == 0 and not show_limits[0]) or (index == last and not show_limits[1]):
            continue
        if direction == "horizontal":
            out.append((box.x_cm + fraction * box.width_cm, label))
        else:
            out.append((box.y_cm + fraction * box.height_cm, label))
    return tuple(out)


def _steps_layout(
    guide_build: GuideBuild,
    theme: ResolvedTheme,
    *,
    direction: str,
    padding: tuple[float, float, float, float],
    title_line: float,
    title_w: float,
    spacing_x: float,
    text_el: ElementText,
    metrics: Any,
) -> LegendLayout:
    """`guide_coloursteps()`：与色条同构，只是标签落在箱边界上。"""
    guide = guide_build.guide
    assert isinstance(guide, GuideColoursteps)
    bins = guide_build.bins
    if bins is None:  # pragma: no cover - build_guides 一定带上
        raise GuideError("guide_coloursteps 缺少分箱数据（build_guides 没有训练它）")
    key_w, key_h = _key_size(theme, guide)
    bar_w, bar_h = _bar_size(GuideColourbar(), key_w, key_h, direction)
    text_size = float(text_el.size or 0.0)
    label_w = _label_width(guide_build, text_el, metrics)
    label_row = text_line_cm(text_size)
    gap_row = _cm_unit(theme.get("legend.key.spacing"), height=True)
    if direction == "horizontal":
        content_w, content_h = bar_w, bar_h + label_row + gap_row
    else:
        content_w, content_h = bar_w + spacing_x + label_w, bar_h
    gap = _cm_unit(theme.get("legend.key.spacing"), height=True)
    width, height, title_box, cx, cy = _compose_title(
        content_w,
        content_h,
        padding=padding,
        title_position=_title_position_of(guide, direction),
        title_line=title_line,
        title_w=title_w,
        title=bool(guide_build.title),
        gap=gap,
    )
    bar_box = _Box(cx, cy if direction == "vertical" else cy + label_row, bar_w, bar_h)
    return LegendLayout(
        width_cm=width,
        height_cm=height,
        direction=direction,
        title_box=title_box,
        bar=bar_box,
        ticks=_step_ticks(
            guide_build,
            bar_box,
            direction,
            show_limits=bins.show_limits,
            reverse=bool(guide.reverse),
        ),
        title_position=_title_position_of(guide, direction),
    )


def _bins_layout(
    guide_build: GuideBuild,
    theme: ResolvedTheme,
    *,
    direction: str,
    padding: tuple[float, float, float, float],
    title_line: float,
    title_w: float,
    spacing_x: float,
    text_el: ElementText,
    metrics: Any,
) -> LegendLayout:
    """`guide_bins()`：每箱一格键（复用几何），标签落在箱边界。

    R 的竖排 bins **低值在上**（`build_labels()` 先 `1 - .value` 再翻转），与
    colourbar 相反；这里照搬（见 `tools/refs/guide_long_ref.R` 的 `bins` 夹具）。
    """
    guide = guide_build.guide
    assert isinstance(guide, GuideBins)
    bins = guide_build.bins
    if bins is None:  # pragma: no cover
        raise GuideError("guide_bins 缺少分箱数据（build_guides 没有训练它）")
    key_w, key_h = _key_size(theme, guide)
    n = max(1, bins.bins)
    text_size = float(text_el.size or 0.0)
    label_w = _label_width(guide_build, text_el, metrics)
    if direction == "vertical":
        content_w = key_w + spacing_x + label_w
        content_h = n * key_h
    else:
        content_w = n * key_w
        content_h = key_h + text_line_cm(text_size)
    gap = _cm_unit(theme.get("legend.key.spacing"), height=True)
    width, height, title_box, cx, cy = _compose_title(
        content_w,
        content_h,
        padding=padding,
        title_position=_title_position_of(guide, direction),
        title_line=title_line,
        title_w=title_w,
        title=bool(guide_build.title),
        gap=gap,
    )
    reverse = bool(getattr(guide, "reverse", False))
    bin_values = list(bins.bin_values)
    bin_labels = list(bins.labels)
    if reverse:
        # R 的 `GuideBins$extract_params()`：键行倒序 + 美学列左旋一格，
        # 等价于「颜色与边界标签一起镜像」。
        bin_values.reverse()
        bin_labels.reverse()
    cells: list[LegendKeyCell] = []
    if direction == "vertical":
        for index, values in enumerate(bin_values):
            # 低值在顶：第 0 箱占最上面一格。
            y = cy + (n - index - 1) * key_h
            key = GuideKey(
                label=bin_labels[index],
                values=values,
                value=index / max(1, n - 1),
            )
            cells.append(
                LegendKeyCell(
                    key,
                    _Box(cx, y, key_w, key_h),
                    _Box(cx + key_w + spacing_x, y, label_w, key_h),
                )
            )
        bar_box = _Box(cx, cy, key_w, content_h)
    else:
        for index, values in enumerate(bin_values):
            x = cx + index * key_w
            key = GuideKey(
                label=bin_labels[index],
                values=values,
                value=index / max(1, n - 1),
            )
            cells.append(
                LegendKeyCell(
                    key,
                    _Box(x, cy + text_line_cm(text_size), key_w, key_h),
                    _Box(x, cy, key_w, text_line_cm(text_size)),
                )
            )
        bar_box = _Box(cx, cy + text_line_cm(text_size), content_w, key_h)
    return LegendLayout(
        width_cm=width,
        height_cm=height,
        direction=direction,
        title_box=title_box,
        keys=tuple(cells),
        bar=bar_box,
        ticks=_step_ticks(
            guide_build,
            bar_box,
            direction,
            show_limits=bins.show_limits,
            reverse=bool(guide.reverse),
            flip=direction == "vertical",
        ),
        title_position=_title_position_of(guide, direction),
    )


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


def _draw_title(
    guide_build: GuideBuild,
    layout: LegendLayout,
    theme: ResolvedTheme,
    *,
    name: str,
) -> list[Any]:
    grobs: list[Any] = []
    title_el = _text_element(theme, "legend.title")
    if not guide_build.title or layout.title_box is None:
        return grobs
    box = layout.title_box
    position = layout.title_position or "top"
    hjust = layout.title_hjust
    vjust = layout.title_vjust
    if position == "top":
        x, y, h, v = box.x_cm + hjust * box.width_cm, box.y_cm + box.height_cm / 2.0, hjust, 0.5
    elif position == "bottom":
        x, y, h, v = box.x_cm + hjust * box.width_cm, box.y_cm + box.height_cm / 2.0, hjust, 0.5
    elif position == "left":
        x, y, h, v = box.x_cm + box.width_cm, box.y_cm + (1.0 - vjust) * box.height_cm, 1.0, vjust
    else:
        x, y, h, v = box.x_cm, box.y_cm + (1.0 - vjust) * box.height_cm, 0.0, vjust
    grobs.append(
        text_grob(
            guide_build.title,
            x,
            y,
            hjust=h,
            vjust=v,
            rot=float(title_el.angle or 0.0),
            default_units="cm",
            gp=gpar(**_text_gp(title_el)),
            name=f"{name}.title",
        )
    )
    return grobs


def _draw_subtitle(
    guide_build: GuideBuild,
    layout: LegendLayout,
    theme: ResolvedTheme,
    *,
    name: str,
) -> list[Any]:
    subtitle = getattr(guide_build.guide, "subtitle", None)
    if not subtitle or layout.subtitle_box is None:
        return []
    box = layout.subtitle_box
    text_el = _text_element(theme, "legend.text")
    return [
        text_grob(
            str(subtitle),
            box.x_cm,
            box.y_cm + box.height_cm / 2.0,
            hjust=0.0,
            vjust=0.5,
            default_units="cm",
            gp=gpar(**_text_gp(text_el)),
            name=f"{name}.subtitle",
        )
    ]


def _override_for_key(guide: Guide, index: int, count: int) -> dict[str, Any]:
    """`override.aes` 的逐键展开：标量原样复用，序列按键序取（R 的循环规则）。"""
    override = dict(_override(guide))
    if not override:
        return {}
    out: dict[str, Any] = {}
    for name, value in override.items():
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
            out[name] = value
            continue
        values = list(value)
        if not values:
            continue
        out[name] = values[index % len(values)]
    del count
    return out


def _label_anchor(layout: LegendLayout, cell: LegendKeyCell) -> tuple[float, float, float, float]:
    """标签文字锚点 `(x, y, hjust, vjust)`（从标签盒按 label.position 推）。"""
    box = cell.label_box
    position = layout.label_position
    if position == "left":
        return (box.x_cm + box.width_cm, box.y_cm + box.height_cm / 2.0, 1.0, 0.5)
    if position == "top":
        return (box.x_cm, box.y_cm, 0.0, 0.0)
    if position == "bottom":
        return (box.x_cm, box.y_cm + box.height_cm, 0.0, 1.0)
    return (box.x_cm, box.y_cm + box.height_cm / 2.0, 0.0, 0.5)


def legend_grob(
    guide_build: GuideBuild,
    build: PlotBuild,
    theme: ResolvedTheme,
    layout: LegendLayout,
    *,
    metrics: Any = None,
    name: str = "guide",
) -> list[Any]:
    """一张图例的 grob 列表（局部 cm 坐标；调用方给外框视口）。"""
    theme = guide_theme(theme, guide_build.guide)
    if isinstance(guide_build.guide, GuideCustom):
        return custom_grob(guide_build, theme, layout, metrics=metrics, name=name)
    width = layout.width_cm
    height = layout.height_cm
    grobs: list[Any] = []
    background = theme.get("legend.background")
    if isinstance(background, ElementRect):
        fill = paint(background.fill)
        if fill is not None:
            grobs.append(
                rect_grob(
                    0.0,
                    0.0,
                    width,
                    height,
                    just=("left", "bottom"),
                    default_units="cm",
                    gp=gpar(fill=fill, col=NA),
                    name=f"{name}.background",
                )
            )
    grobs.extend(_draw_title(guide_build, layout, theme, name=name))
    grobs.extend(_draw_subtitle(guide_build, layout, theme, name=name))
    # M2-9 扩展点：运行时 guide 实现 `draw_keys()` 时，key 区交给它画；
    # 标题 / 背景 / 布局仍由这里负责（docs/notes/extension.md）。
    draw_keys = getattr(guide_build.guide, "draw_keys", None)
    if callable(draw_keys):
        grobs.extend(draw_keys(guide_build, theme, layout, metrics=metrics, name=name))
        return grobs
    if isinstance(guide_build.guide, GuideColourbar) and layout.bar is not None:
        grobs.extend(_colourbar_grobs(guide_build, theme, layout, name=name))
        return grobs
    if isinstance(guide_build.guide, GuideColoursteps) and layout.bar is not None:
        grobs.extend(_steps_grobs(guide_build, theme, layout, name=name))
        return grobs
    if isinstance(guide_build.guide, GuideBins) and layout.bar is not None:
        grobs.extend(_bins_grobs(guide_build, build, theme, layout, name=name))
        return grobs
    text_el = _text_element(theme, "legend.text")
    key_el = theme.get("legend.key")
    guide = guide_build.guide
    count = len(layout.keys)
    label_hjust = getattr(guide, "label_hjust", None)
    label_vjust = getattr(guide, "label_vjust", None)
    for index, cell in enumerate(layout.keys):
        key_box = cell.box
        if isinstance(key_el, ElementRect) and paint(key_el.fill) is not None:
            grobs.append(
                rect_grob(
                    key_box.x_cm,
                    key_box.y_cm,
                    key_box.width_cm,
                    key_box.height_cm,
                    just=("left", "bottom"),
                    default_units="cm",
                    gp=gpar(
                        fill=paint(key_el.fill),
                        col=paint(key_el.colour) or NA,
                        lwd=0.0,
                    ),
                    name=f"{name}.key-{index}-bg",
                )
            )
        vp = viewport(
            f"{name}-key-{index}",
            x=unit(key_box.x_cm + key_box.width_cm / 2.0, "cm"),
            y=unit(key_box.y_cm + key_box.height_cm / 2.0, "cm"),
            width=unit(key_box.width_cm, "cm"),
            height=unit(key_box.height_cm, "cm"),
            just="centre",
            xscale=(0.0, 1.0),
            yscale=(0.0, 1.0),
            clip="on",
        )
        override = _override_for_key(guide, index, count)
        for layer_index in guide_build.layers:
            if not _layer_maps_any(build, layer_index, guide_build.aesthetics):
                continue
            decor = _key_grob(
                build,
                layer_index,
                cell.key.values,
                override=override,
                size_cm=(key_box.width_cm, key_box.height_cm),
            )
            if decor is None:
                continue
            grobs.append(replace(decor, vp=vp) if getattr(decor, "vp", None) is None else decor)
        x, y, hjust, vjust = _label_anchor(layout, cell)
        if label_hjust is not None:
            hjust = float(label_hjust)
            if layout.label_position == "right":
                x = cell.label_box.x_cm
            elif layout.label_position == "left":
                x = cell.label_box.x_cm
        if label_vjust is not None:
            vjust = float(label_vjust)
            y = cell.label_box.y_cm + (1.0 - vjust) * cell.label_box.height_cm
        grobs.append(
            text_grob(
                cell.key.label,
                x,
                y,
                hjust=hjust,
                vjust=vjust,
                rot=float(text_el.angle or 0.0),
                default_units="cm",
                gp=gpar(**_text_gp(text_el)),
                name=f"{name}.label-{index}",
            )
        )
    return grobs


def custom_grob(
    guide_build: GuideBuild,
    theme: ResolvedTheme,
    layout: LegendLayout,
    *,
    metrics: Any = None,
    name: str = "guide",
) -> list[Any]:
    """`guide_custom(grob)` 的绘制：内容 grob + 标题 + 背景。"""
    guide = guide_build.guide
    theme = guide_theme(theme, guide)
    assert isinstance(guide, GuideCustom)
    grobs: list[Any] = []
    background = theme.get("legend.background")
    if isinstance(background, ElementRect):
        fill = paint(background.fill)
        if fill is not None:
            grobs.append(
                rect_grob(
                    0.0,
                    0.0,
                    layout.width_cm,
                    layout.height_cm,
                    just=("left", "bottom"),
                    default_units="cm",
                    gp=gpar(fill=fill, col=NA),
                    name=f"{name}.background",
                )
            )
    grobs.extend(_draw_title(guide_build, layout, theme, name=name))
    box = layout.content_box
    if box is None:
        return grobs
    content: Any
    if callable(guide.grob):
        content = guide.grob(box.width_cm, box.height_cm)
    else:
        content = guide.grob
    items = list(content) if isinstance(content, (list, tuple)) else [content]
    vp = viewport(
        f"{name}-content",
        x=unit(box.x_cm + box.width_cm / 2.0, "cm"),
        y=unit(box.y_cm + box.height_cm / 2.0, "cm"),
        width=unit(box.width_cm, "cm"),
        height=unit(box.height_cm, "cm"),
        just="centre",
        xscale=(0.0, 1.0),
        yscale=(0.0, 1.0),
        clip="off",
    )
    for item in items:
        if item is None:
            continue
        grobs.append(replace(item, vp=vp) if getattr(item, "vp", None) is None else item)
    return grobs


def _layer_maps_any(build: PlotBuild, index: int, aesthetics: Sequence[str]) -> bool:
    mapping = _layer_mapping(build, index)
    return any(aesthetic in mapping for aesthetic in aesthetics)


def _frame_paint(guide: Any, theme: ResolvedTheme) -> tuple[str | None, float]:
    """图例边框：guide 的 `frame.colour` > **显式**主题 `legend.frame` > 不画。

    R 4.0.3 的 `GuideColourbar$setup_elements()` 用
    `replace_null(theme, legend.frame = element_blank())`：主题里**没有写过**
    `legend.frame` 时边框是 blank，只有用户显式给了才继承 `element_rect()` 的
    黑框。`resolve_theme()` 会把继承出来的 `legend.frame` 填成黑框，所以这里要看
    主题对象里有没有显式条目。
    """
    explicit = getattr(guide, "frame_colour", None)
    if explicit is not None:
        return paint(explicit), 0.5 * 72.0 / 25.4
    source = getattr(theme, "theme", None)
    elements = getattr(source, "elements", None) or {}
    if "legend.frame" not in elements:
        return None, 0.0
    frame = theme.get("legend.frame")
    if not isinstance(frame, ElementRect):
        return None, 0.0
    colour = paint(frame.colour)
    width = float(frame.linewidth or 0.0) * 72.0 / 25.4
    return colour, width


def _tick_style(guide: Any, theme: ResolvedTheme) -> tuple[str | None, float, float]:
    """图例刻度的 `(colour, length_cm, lwd)`；guide 的 `ticks.colour` 优先。"""
    element = theme.get("legend.ticks")
    if isinstance(element, ElementBlank):
        return None, 0.0, 0.0
    colour = paint(getattr(guide, "ticks_colour", None) or getattr(element, "colour", None))
    if colour is None:
        return None, 0.0, 0.0
    length = _cm_unit(theme.get("legend.ticks.length"), height=False)
    width = float(getattr(element, "linewidth", None) or 0.0) * 72.0 / 25.4
    return colour, length, width


def _bar_bands(
    box: _Box,
    bounds: Sequence[tuple[float, float]],
    colours: Sequence[str],
    horizontal: bool,
    *,
    name: str,
) -> list[Any]:
    """一段条带 = 若干 `(low, high)` 小矩形（0..1）；相邻条多铺 1pt 防白缝。"""
    grobs: list[Any] = []
    for index, ((low, high), colour) in enumerate(zip(bounds, colours, strict=True)):
        extra = _BAND_OVERLAP_CM if index < len(bounds) - 1 else 0.0
        if horizontal:
            grobs.append(
                rect_grob(
                    box.x_cm + low * box.width_cm,
                    box.y_cm,
                    (high - low) * box.width_cm + extra,
                    box.height_cm,
                    just=("left", "bottom"),
                    default_units="cm",
                    gp=gpar(fill=colour, col=NA),
                    name=f"{name}.bar-{index}",
                )
            )
        else:
            grobs.append(
                rect_grob(
                    box.x_cm,
                    box.y_cm + low * box.height_cm,
                    box.width_cm,
                    (high - low) * box.height_cm + extra,
                    just=("left", "bottom"),
                    default_units="cm",
                    gp=gpar(fill=colour, col=NA),
                    name=f"{name}.bar-{index}",
                )
            )
    return grobs


def _legend_axis_line_grob(
    layout: LegendLayout,
    theme: ResolvedTheme,
    *,
    name: str,
) -> list[Any]:
    """`legend.axis.line`：沿 key 区外侧边缘的轴线（`guide_bins` 的默认元素）。

    R 的 `GuideBins$draw()` 把轴线放在 key 的 gtable 边上，端点随
    `legend.text.position` 走（`right` → `x = (1, 1)`、`left` → `x = (0, 0)`、
    `bottom` → `y = (0, 0)`、`top` → `y = (1, 1)`）；箭头由元素自带的
    `element_line(arrow = arrow(...))` 决定（`legend.axis.line` 的箭头那条快照）。
    """
    element = theme.get("legend.axis.line")
    box = layout.bar
    if not isinstance(element, ElementLine) or box is None:
        return []
    colour = paint(element.colour)
    if colour is None:
        return []
    text_position = layout.label_position
    if layout.direction == "horizontal":
        y = box.y_cm if text_position == "bottom" else box.y_cm + box.height_cm
        x0, y0 = box.x_cm, y
        x1, y1 = box.x_cm + box.width_cm, y
    else:
        x = box.x_cm + box.width_cm if text_position == "right" else box.x_cm
        x0, y0 = x, box.y_cm
        x1, y1 = x, box.y_cm + box.height_cm
    arrow = None if isinstance(element.arrow, bool) else element.arrow
    width = float(element.linewidth or 0.0) * 72.0 / 25.4
    from ggcore.grobs import segments_grob

    return [
        segments_grob(
            [x0],
            [y0],
            [x1],
            [y1],
            default_units="cm",
            gp=gpar(col=colour, lwd=width),
            arrow=arrow,
            name=f"{name}.axis-line",
        )
    ]


def _bar_axis_grobs(
    layout: LegendLayout,
    theme: ResolvedTheme,
    guide: Any,
    *,
    name: str,
    label_prefix: str,
    ticks: bool = True,
    label_bottom_offset: float = 0.0,
) -> list[Any]:
    """条带外侧的刻度线 + 标签（竖向在右、横向在下）。"""
    from ggcore.grobs import segments_grob

    box = layout.bar
    assert box is not None
    horizontal = layout.direction == "horizontal"
    text_el = _text_element(theme, "legend.text")
    spacing_x = _cm_unit(theme.get("legend.key.spacing.x"), height=False)
    label_x = box.x_cm + box.width_cm + spacing_x
    colour, tick_len, tick_lwd = _tick_style(guide, theme)
    draw_ticks = bool(ticks) and colour is not None and tick_len > 0
    grobs: list[Any] = []
    for index, (position, label) in enumerate(layout.ticks):
        if draw_ticks:
            if horizontal:
                grobs.append(
                    segments_grob(
                        [position, position],
                        [box.y_cm, box.y_cm],
                        [position, position],
                        [box.y_cm - tick_len, box.y_cm - tick_len],
                        default_units="cm",
                        gp=gpar(col=colour, lwd=tick_lwd),
                        name=f"{name}.tick-{index}",
                    )
                )
            else:
                grobs.append(
                    segments_grob(
                        [box.x_cm + box.width_cm, box.x_cm + box.width_cm],
                        [position, position],
                        [box.x_cm + box.width_cm + tick_len, box.x_cm + box.width_cm + tick_len],
                        [position, position],
                        default_units="cm",
                        gp=gpar(col=colour, lwd=tick_lwd),
                        name=f"{name}.tick-{index}",
                    )
                )
        if horizontal:
            grobs.append(
                text_grob(
                    label,
                    position,
                    box.y_cm
                    - _cm_unit(theme.get("legend.key.spacing"), height=True)
                    - tick_len
                    - label_bottom_offset,
                    hjust=0.5,
                    vjust=1.0,
                    default_units="cm",
                    gp=gpar(**_text_gp(text_el)),
                    name=f"{name}.{label_prefix}-{index}",
                )
            )
        else:
            grobs.append(
                text_grob(
                    label,
                    label_x,
                    position,
                    hjust=0.0,
                    vjust=0.5,
                    default_units="cm",
                    gp=gpar(**_text_gp(text_el)),
                    name=f"{name}.{label_prefix}-{index}",
                )
            )
    return grobs


def _colourbar_grobs(
    guide_build: GuideBuild,
    theme: ResolvedTheme,
    layout: LegendLayout,
    *,
    name: str,
) -> list[Any]:
    """渐变条：`nbin` 个 1/nbin 高的小矩形（R 用 rasterGrob；IR 里两者都是矩形）。

    颜色**按标度的全量程**取（`GuideBuild.palette`，与数据映射同一个 Lab 插值），
    不是按断点键的颜色插值：`limits = (16.2, 30.3)` 的标度要把深端也画出来。
    相邻矩形多铺 `_BAND_OVERLAP_CM`，否则 0.34pt 高的相邻条在 resvg 里各自
    抗锯齿、白底从缝里透出来（整条偏白约 30%）。
    """
    guide = guide_build.guide
    assert isinstance(guide, GuideColourbar)
    box = layout.bar
    assert box is not None
    nbin = int(guide.nbin or 300)
    horizontal = layout.direction == "horizontal"
    steps = _apply_alpha(_colourbar_colours(guide_build, nbin), guide.alpha)
    if horizontal:
        bounds = tuple((index / nbin, (index + 1) / nbin) for index in range(nbin))
    else:
        bounds = tuple((index / nbin, (index + 1) / nbin) for index in range(nbin))
    grobs = _bar_bands(box, bounds, steps, horizontal, name=name)
    colour, width = _frame_paint(guide, theme)
    if colour is not None:
        grobs.append(
            rect_grob(
                box.x_cm,
                box.y_cm,
                box.width_cm,
                box.height_cm,
                just=("left", "bottom"),
                default_units="cm",
                gp=gpar(fill=NA, col=colour, lwd=width),
                name=f"{name}.frame",
            )
        )
    grobs.extend(
        _bar_axis_grobs(
            layout,
            theme,
            guide,
            name=name,
            label_prefix="colourbar-label",
            ticks=bool(guide.ticks),
        )
    )
    return grobs


def _steps_grobs(
    guide_build: GuideBuild,
    theme: ResolvedTheme,
    layout: LegendLayout,
    *,
    name: str,
) -> list[Any]:
    """分段色条：每个箱一个矩形（等宽或按数据间距），标签在箱边界。"""
    guide = guide_build.guide
    assert isinstance(guide, GuideColoursteps)
    box = layout.bar
    assert box is not None
    bins = guide_build.bins
    if bins is None:  # pragma: no cover
        raise GuideError("guide_coloursteps 缺少分箱数据")
    horizontal = layout.direction == "horizontal"
    bounds = bins.bin_bounds()
    colours = [
        _apply_alpha([str(values.get("colour") or values.get("fill") or "#808080")], guide.alpha)[0]
        for values in bins.bin_values
    ]
    if guide.reverse:
        # R 的 `.value <- 1 - .value`：色阶与箱位置一起镜像（标签由
        # `_step_ticks(reverse=...)` 翻，三者必须同向）。
        colours.reverse()
        bounds = tuple((1.0 - high, 1.0 - low) for low, high in reversed(bounds))
    grobs = _bar_bands(box, bounds, colours, horizontal, name=name)
    colour, width = _frame_paint(guide, theme)
    if colour is not None:
        grobs.append(
            rect_grob(
                box.x_cm,
                box.y_cm,
                box.width_cm,
                box.height_cm,
                just=("left", "bottom"),
                default_units="cm",
                gp=gpar(fill=NA, col=colour, lwd=width),
                name=f"{name}.frame",
            )
        )
    grobs.extend(
        _bar_axis_grobs(
            layout,
            theme,
            guide,
            name=name,
            label_prefix="coloursteps-label",
        )
    )
    return grobs


def _bins_grobs(
    guide_build: GuideBuild,
    build: PlotBuild,
    theme: ResolvedTheme,
    layout: LegendLayout,
    *,
    name: str,
) -> list[Any]:
    """分箱图例：每箱一个几何 key（与 legend 同一套 `Geom.draw()`），标签在边界。"""
    guide = guide_build.guide
    assert isinstance(guide, GuideBins)
    grobs: list[Any] = []
    key_el = theme.get("legend.key")
    for index, cell in enumerate(layout.keys):
        key_box = cell.box
        if isinstance(key_el, ElementRect) and paint(key_el.fill) is not None:
            grobs.append(
                rect_grob(
                    key_box.x_cm,
                    key_box.y_cm,
                    key_box.width_cm,
                    key_box.height_cm,
                    just=("left", "bottom"),
                    default_units="cm",
                    gp=gpar(fill=paint(key_el.fill), col=paint(key_el.colour) or NA, lwd=0.0),
                    name=f"{name}.key-{index}-bg",
                )
            )
        vp = viewport(
            f"{name}-key-{index}",
            x=unit(key_box.x_cm + key_box.width_cm / 2.0, "cm"),
            y=unit(key_box.y_cm + key_box.height_cm / 2.0, "cm"),
            width=unit(key_box.width_cm, "cm"),
            height=unit(key_box.height_cm, "cm"),
            just="centre",
            xscale=(0.0, 1.0),
            yscale=(0.0, 1.0),
            clip="on",
        )
        for layer_index in guide_build.layers:
            if not _layer_maps_any(build, layer_index, guide_build.aesthetics):
                continue
            decor = _key_grob(
                build,
                layer_index,
                cell.key.values,
                override=_override(guide_build.guide),
            )
            if decor is None:
                continue
            grobs.append(replace(decor, vp=vp) if getattr(decor, "vp", None) is None else decor)
    grobs.extend(_legend_axis_line_grob(layout, theme, name=name))
    grobs.extend(
        _bar_axis_grobs(
            layout,
            theme,
            guide,
            name=name,
            label_prefix="bins-label",
        )
    )
    return grobs


def _apply_alpha(colours: Sequence[str], alpha: float | None) -> list[str]:
    """`alpha` 把颜色混到白底上（R 的 `alpha()` 在 svglite 白底上等价）。"""
    if alpha is None or float(alpha) >= 1.0:
        return list(colours)
    if float(alpha) <= 0.0:
        return ["#FFFFFF"] * len(colours)
    from ggcore.grobs import parse_colour

    out: list[str] = []
    for colour in colours:
        red, green, blue = parse_colour(colour)[:3]
        mixed = [
            round(255.0 + (float(channel) - 255.0) * float(alpha)) for channel in (red, green, blue)
        ]
        out.append("#{:02X}{:02X}{:02X}".format(*mixed))
    return out


def _colourbar_colours(guide_build: GuideBuild, nbin: int) -> list[str]:
    """色条 `nbin` 个位置的颜色（低 → 高；`reverse = TRUE` 时反过来）。

    有标度调色板时按 **limits 全量程**等距取色（端点是标度最小值 / 最大值），
    与数据映射同一套插值；没有调色板（手工构造的 `GuideBuild`）才退回按断点
    键的颜色插值。
    """
    guide = guide_build.guide
    assert isinstance(guide, GuideColourbar)
    if nbin <= 0:
        return []
    palette = guide_build.palette
    if palette is not None:
        positions = [0.5] if nbin == 1 else [index / (nbin - 1) for index in range(nbin)]
        colours = [str(colour) for colour in palette(positions)]
        if len(colours) == nbin:
            if guide.reverse:
                colours.reverse()
            return colours
    values = [key.values.get("colour", key.values.get("fill")) for key in guide_build.keys]
    colours = [value if isinstance(value, str) else "#808080" for value in values]
    return _gradient_stops(colours, nbin)


def _gradient_stops(colours: Sequence[str], nbin: int) -> list[str]:
    """断点色 → `nbin` 个等距色（在 sRGB 里线性插值，与 R 的 colourbar 近似）。"""
    from ggcore.grobs import parse_colour

    if not colours:
        return ["#808080"] * nbin
    if len(colours) == 1:
        return [colours[0]] * nbin
    stops = [parse_colour(colour) for colour in colours]
    out: list[str] = []
    for index in range(nbin):
        position = index / (nbin - 1) * (len(stops) - 1)
        left = int(np.floor(position))
        right = min(left + 1, len(stops) - 1)
        fraction = position - left
        channels = [
            round(stops[left][channel] + (stops[right][channel] - stops[left][channel]) * fraction)
            for channel in range(3)
        ]
        out.append("#{:02X}{:02X}{:02X}".format(*channels))
    return out

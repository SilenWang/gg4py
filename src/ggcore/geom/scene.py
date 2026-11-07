"""整页场景装配：plot 背景 + panel + strip + 主轴 + 图例 + 标题（M1-7 / M1-11）。

结构照 ggplot2 4.0.3 的 `ggplot_gtable()`：

```
page viewport（整页，plot.background）
├── plot.title
├── legend 盒（right / left / top / bottom；legend.box 竖排、legend.spacing 隔开）
├── 每个面板
│   ├── panel.background / panel.border / clipPath + 图层（M1-7）
│   ├── strip（分面时）
│   ├── 主轴：axis.ticks.* / axis.text.* / axis.title.*（M1-11，`ggcore.axis`）
└── x / y 轴标题（整块面板区一份，与 R 的 xlab / ylab 行同口径）
```

口径：

- 面板矩形来自 `FacetTable.panel_boxes()`（gtable 的行列解析），并整块平移进
  「扣掉标题 / 图例 / 轴」之后的 `panel_area`；
- 轴与图例的尺寸全部取 `resolve_theme()` 的解析值（`axis.ticks.length`、
  `legend.key.size`、`legend.margin`、`panel.spacing`、`plot.margin`），见
  `docs/notes/guide.md` 的尺寸表；
- 单面板与分面走同一条路径；`scales="free"` 时每个面板用自己的标度取断点；
- 轴 / 图例 / 标题的隐藏规则跟主题：`element_blank()` 的元素不占位，
  `legend.position="none"` 不画图例（`theme_void()` 只抹轴，图例照 R 保留）。

`plot_layout()` 把上面这些尺寸算成一份可断言的数据结构（对拍测试直接读它）。
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from ggcore import ir, plotmath
from ggcore.axis import (
    DERIVE,
    axis_ticks,
    axis_title_extent,
    axis_title_grob,
    margin_sides_cm,
    paint,
    polar_axis_breaks,
    polar_axis_row_cm,
    polar_minor_breaks,
    polar_r_ticks,
    text_line_cm,
    text_width_cm,
    tick_length_cm,
)
from ggcore.axis_guide import (
    AUTO,
    AxisGuide,
    axis_guide_extent,
    axis_guide_grobs,
    axis_guide_ticks,
    axis_line_grobs,
    axis_line_range,
    guide_for,
    polar_axis_grobs,
    polar_r_axis_inside_grobs,
)
from ggcore.build import _STAT_DEFAULT_AES, LayerBuild, PlotBuild, build_plot
from ggcore.coord import CoordBase, PanelParams
from ggcore.data import ColumnTable
from ggcore.facet import FacetStrip, FacetTable, StripPart
from ggcore.geom.base import POINT_PER_MM
from ggcore.grobs import (
    NullGrob,
    ZeroGrob,
    clip_path,
    g_tree,
    math_text_grobs,
    polyline_grob,
    rect_grob,
    scene,
    segments_grob,
    text_grob,
)
from ggcore.gtable import CellBox
from ggcore.guide import (
    GuideBuild,
    GuideError,
    build_guides,
    guide_theme,
    legend_box_direction,
    legend_box_layout,
    legend_justification,
    legend_layout,
)
from ggcore.theme import (
    ElementBlank,
    ElementLine,
    ElementRect,
    ElementText,
    ResolvedTheme,
    Theme,
    element_grob,
    resolve_theme,
)
from ggcore.units import CM_PER_INCH, UnitContext, unit
from ggcore.viewport import NA, Device, ViewportTree, gpar, viewport

__all__ = [
    "DEFAULT_HEIGHT_IN",
    "DEFAULT_WIDTH_IN",
    "Box",
    "PlotLayout",
    "axis_title_area",
    "plot_layout",
    "scene_from_build",
    "scene_from_plot",
]

DEFAULT_WIDTH_IN = 7.0
DEFAULT_HEIGHT_IN = 7.0


class _FallbackMetrics:
    """没有字体度量时的占位实现（`ggcore.units.Metrics` 协议，返回英寸）。

    宽 0.6em/字符、行高 0.955em，与 `ggcore.axis` 的布局估算同一口径。真实渲染走
    `pixi run render`（`ggskia.text.ShaperMetrics`），IR 里的 `text.width` 以设备
    为准；这里只保证「不给 metrics 也能出场景」且字节稳定。
    """

    def strwidth(self, text: str, *, fontsize: float, cex: float, font: str = "sans") -> float:
        del font
        lines = str(text).split("\n")
        longest = max((len(line) for line in lines), default=0)
        return 0.6 * float(fontsize) * float(cex) * longest / 72.0

    def strheight(self, text: str, *, fontsize: float, cex: float, font: str = "sans") -> float:
        del text, font
        return 0.955 * float(fontsize) * float(cex) / 72.0

    def descent(self, *, fontsize: float, cex: float = 1.0, font: str = "sans") -> float:
        del font
        return 0.22 * float(fontsize) * float(cex) / 72.0


_FALLBACK_METRICS = _FallbackMetrics()


@dataclass(frozen=True, slots=True)
class Box:
    """页面里的一个矩形（cm，y 向上，左下角为原点）。"""

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


@dataclass(frozen=True, slots=True)
class PlotLayout:
    """整页版式：各行列的外向尺寸 + 各区域的矩形（cm）。"""

    width_cm: float
    height_cm: float
    #: `plot.margin` 的 `(上, 右, 下, 左)`（cm）。
    margin_cm: tuple[float, float, float, float]
    title: Box | None
    title_text: str | None
    subtitle: Box | None
    subtitle_text: str | None
    caption: Box | None
    caption_text: str | None
    #: 扣掉标题 / 图例 / 轴之后的面板区（facet 表在这里解析）。
    panel_area: Box
    #: 主轴占位：刻度 + 轴文字（不含轴标题）。
    x_axis_cm: float
    y_axis_cm: float
    #: 轴标题占位。
    x_title_cm: float
    y_title_cm: float
    #: 标题 / 副标题 / 注脚的行高（含 margin）。
    title_cm: float
    subtitle_cm: float
    caption_cm: float
    #: 每个面板的矩形（页面坐标；顺序同 `build.panels`）。
    panel_boxes: Mapping[int, Box]
    #: 图例：位置 + 每张图例的布局 + 页面矩形。
    legend_side: str | None
    legend_layouts: tuple[Any, ...]
    legend_boxes: tuple[Box, ...]
    guides: tuple[GuideBuild, ...]
    #: 次轴（M2-1）：top / right 两条 gtable 槽的占位与是否启用。
    x_axis_top_cm: float = 0.0
    y_axis_right_cm: float = 0.0
    x_title_top_cm: float = 0.0
    y_title_right_cm: float = 0.0
    secondary_x: bool = False
    secondary_y: bool = False
    #: `strip.placement = "outside"` 时 strip 块所在的页面矩形（轴带之外）。
    top_strip_band: Box | None = None
    right_strip_band: Box | None = None
    #: 图例盒（M2-2）：每个方位的 `LegendBoxLayout`（行列尺寸 + 盒内偏移）
    #: 与它在页面上的矩形，二者一一对应。
    legend_box_layouts: tuple[Any, ...] = ()
    legend_box_origins: tuple[Box, ...] = ()
    #: `labs(tag =)` 的锚点（0 尺寸 Box，`x_cm` / `y_cm` 是文字锚点）。
    #: `plot.tag.location` 决定它相对哪块区域定位（margin / panel / plot）。
    tag: Box | None = None
    tag_text: str | None = None
    #: `plot.tag` 的解析后元素（渲染时取字号 / 颜色 / 字体）。
    tag_element: Any = None
    #: 版式实际解析用的 facet gtable（含行间 / 列间轴带）。渲染必须复用这同一张
    #: 表：另建一张不带 `axis_x_cm` / `axis_y_cm` 的表会让 strip 与轴按错位的
    #: 行列落点（SIL-816 的 `facet-wrap-with-omitted-inner-axis-labels`）。
    facet_table: Any = None

    @property
    def legend_width_cm(self) -> float:
        return max((box.width_cm for box in self.legend_boxes), default=0.0)

    @property
    def legend_height_cm(self) -> float:
        return sum(box.height_cm for box in self.legend_boxes)


def axis_title_area(layout: PlotLayout) -> Box:
    """轴标题（xlab / ylab）的横向 / 纵向落点区：**panel 单元格的并集**。

    R 的 xlab / ylab 行只跨 panel 列 / 行；`facet_grid` 的行 strip 自带一列、
    列 strip 自带一行，标题的中心不能把 strip 算进去（SIL-817：行 strip 在右侧
    时 x 标题会右移半个 strip 宽）。没有面板时退回整个 `panel_area`。
    """
    area = layout.panel_area
    if not layout.panel_boxes:
        return area
    left = min(box.x_cm for box in layout.panel_boxes.values())
    right = max(box.right for box in layout.panel_boxes.values())
    bottom = min(box.y_cm for box in layout.panel_boxes.values())
    top = max(box.top for box in layout.panel_boxes.values())
    return Box(left, bottom, right - left, top - bottom)


def scene_from_plot(
    plot: Any,
    *,
    width_in: float = DEFAULT_WIDTH_IN,
    height_in: float = DEFAULT_HEIGHT_IN,
    dpi: float = 72.0,
    metrics: Any = None,
) -> ir.Scene:
    """`ggplot` → `ir.Scene`（构建 + 装配一条路走完）。"""
    return scene_from_build(
        build_plot(plot),
        width_in=width_in,
        height_in=height_in,
        dpi=dpi,
        metrics=metrics,
    )


def scene_from_build(
    build: PlotBuild,
    *,
    width_in: float = DEFAULT_WIDTH_IN,
    height_in: float = DEFAULT_HEIGHT_IN,
    dpi: float = 72.0,
    metrics: Any = None,
) -> ir.Scene:
    """`PlotBuild` → `ir.Scene`（pt、y 向下交给 IR）。"""
    del dpi  # 设备分辨率不属于场景；`Scene.dpi` 由 `ir.Scene` 的默认值给出
    metrics = metrics if metrics is not None else _FALLBACK_METRICS
    prepared = build if build.metrics is metrics else replace(build, metrics=metrics)
    layout = plot_layout(prepared, width_in=width_in, height_in=height_in, metrics=metrics)
    theme = _theme_of(prepared)
    table = layout.facet_table
    if table is None:  # pragma: no cover - `plot_layout()` 总会给出
        table = prepared.facet_table(metrics=metrics)

    tree = ViewportTree(Device(float(width_in), float(height_in)), metrics=metrics)
    tree.push(
        viewport(
            "page",
            x=0.5,
            y=0.5,
            width=1.0,
            height=1.0,
            clip="off",
            gp=gpar(fontsize=12.0, fontfamily=""),
        )
    )

    grobs: list[Any] = []
    background = _rect_for(theme, "plot.background", layout.width_cm, layout.height_cm, centre=True)
    if background is not None:
        grobs.append(background)
    grobs.extend(_text_row_grobs(theme, layout, "title"))

    prepared_layers = [_prepare_layer(layer) for layer in prepared.layers]
    theme_key = _theme_fingerprint(theme)
    for panel, params in _panels(prepared):
        box = layout.panel_boxes.get(panel)
        if box is None:  # pragma: no cover - FacetTable 一定覆盖每个 panel
            continue
        children = _panel_children(
            prepared,
            prepared_layers,
            panel,
            params,
            theme,
            metrics,
            panel_size_in=(box.width_cm / CM_PER_INCH, box.height_cm / CM_PER_INCH),
            theme_key=theme_key,
        )
        if children:
            grobs.append(
                g_tree(
                    *children,
                    name=f"panel-{panel}",
                    vp=viewport(
                        f"panel-{panel}",
                        x=unit(box.x_cm + box.width_cm / 2.0, "cm"),
                        y=unit(box.y_cm + box.height_cm / 2.0, "cm"),
                        width=unit(box.width_cm, "cm"),
                        height=unit(box.height_cm, "cm"),
                        just="centre",
                        xscale=(0.0, 1.0),
                        yscale=(0.0, 1.0),
                        clip=_clip_state(params.clip),
                        gp=gpar(fontsize=12.0, fontfamily=""),
                    ),
                )
            )

    grobs.extend(_text_row_grobs(theme, layout, "subtitle"))
    grobs.extend(_text_row_grobs(theme, layout, "caption"))
    grobs.extend(_strip_grobs(table, theme, layout, metrics))
    grobs.extend(_axis_grobs(prepared, theme, layout, metrics, table=table))
    grobs.extend(_legend_grobs(prepared, theme, layout, metrics))
    grobs.extend(_tag_grobs(layout))
    return scene(grobs, tree, cache=_scene_cache()).to_ir_scene()


# ---------------------------------------------------------------------------
# 版式：plot.margin / title / legend / axes / panel 区
# ---------------------------------------------------------------------------


def _scene_cache() -> Any:
    """增量重算的指令缓存（M3-5）；被关掉时返回 `None`。"""
    from ggcore.perf import scene_cache

    return scene_cache()


def layer_draw_cache() -> Any:
    """增量重算的图层绘制缓存（M3-5）；被关掉时返回 `None`。"""
    from ggcore.perf import layer_draw_cache as _cache

    return _cache()


def _theme_of(build: PlotBuild) -> ResolvedTheme:
    return resolve_theme(build.theme if isinstance(build.theme, Theme) else Theme(), build.metrics)


def _plot_margin(theme: ResolvedTheme) -> tuple[float, float, float, float]:
    element = theme.get("plot.margin")
    values = margin_sides_cm(element)
    return (values[0], values[2], values[1], values[3])  # (top, bottom, right, left)


def _label_text(build: PlotBuild, name: str) -> str | None:
    labels = getattr(build, "labels", {}) or {}
    if name not in labels:
        return None
    value = labels[name]
    return None if value is None else str(value)


def _text_row_cm(theme: ResolvedTheme, name: str, text: str | None) -> tuple[float, Any]:
    """一个标题类 text 元素的行高（含上下 margin）；没有文字给 0。"""
    element = theme.get(name)
    if text is None or not isinstance(element, ElementText):
        return 0.0, element
    mt, _mr, mb, _ml = margin_sides_cm(element.margin)
    return text_line_cm(float(element.size or 0.0)) + mt + mb, element


_UNSET_TITLE: Any = object()


def _scale_axis_title(build: PlotBuild, aesthetic: str) -> Any:
    """位置标度上的显式 `name=`（`_UNSET_TITLE` = 没给，交给下一级）。

    R 的轴标题是 `guide$title %|W% scale$name %|W% plot$labels` 三级链：
    `scale_x_continuous(name = "Unit A")` 覆盖映射名，`name = NULL` 则**去掉**
    标题（不是回落到映射名）。`scale_*()` 的 `name` 参数在 gg4py 里只喂给图例，
    这里补上轴这一侧。
    """
    scales = getattr(build, "scales", None)
    getter = getattr(scales, "scale", None)
    if getter is None:
        return _UNSET_TITLE
    scale = getter(aesthetic)
    if scale is None:
        return _UNSET_TITLE
    has_param = getattr(scale, "_has_param", None)
    param = getattr(scale, "_param", None)
    if has_param is None or param is None or not has_param("name"):
        return _UNSET_TITLE
    try:
        return param("name")
    except TypeError:  # pragma: no cover - 自定义标度子类可能没有 name 参数
        return _UNSET_TITLE


#: `plot.tag.position` 的字符串写法 → `(top, left, right, bottom)`（R `table_add_tag()`）。
_TAG_POSITIONS: Mapping[str, tuple[bool, bool, bool, bool]] = {
    "topleft": (True, True, False, False),
    "top": (True, False, False, False),
    "topright": (True, False, True, False),
    "left": (False, True, False, False),
    "right": (False, False, True, False),
    "bottomleft": (False, True, False, True),
    "bottom": (False, False, False, True),
    "bottomright": (False, False, True, True),
}


def _tag_size(theme: ResolvedTheme, text: str | None, metrics: Any) -> tuple[float, float, Any]:
    """`labs(tag=)` 的（宽, 高）cm；没有标签或元素是 blank 时给 0。

    高走 `text_line_cm()`（R `stringHeight` 的 0.955em 口径），宽走真实度量
    （`metrics.strwidth`）。R 的 `element_grob()` 把 margin 也算进 tag 尺寸；这里
    只用文字本体——`plot.tag` 缺省没有 margin，量级差在 1pt 内。
    """
    element = theme.get("plot.tag")
    if text is None or not isinstance(element, ElementText):
        return 0.0, 0.0, element
    size = float(element.size or 11.0)
    width = text_width_cm(text, size, metrics, element.family or "")
    return width, text_line_cm(size), element


def _tag_position(theme: ResolvedTheme) -> tuple[bool, bool, bool, bool] | tuple[float, float]:
    """`plot.tag.position` → 四边布尔（字符位置）或 `(x, y)` npc（数值位置）。"""
    value = theme.get("plot.tag.position")
    if value is None:
        value = "topleft"
    if isinstance(value, str):
        if value not in _TAG_POSITIONS:
            raise ValueError(
                f"plot.tag.position 只能是 {', '.join(_TAG_POSITIONS)} 或 c(x, y)，收到 {value!r}"
            )
        return _TAG_POSITIONS[value]
    try:
        items = [float(item) for item in value]  # type: ignore[union-attr]
    except TypeError as exc:
        raise ValueError(f"plot.tag.position 无法解析：{value!r}") from exc
    if len(items) != 2:
        raise ValueError(f"plot.tag.position 的数值形式需要 c(x, y)，收到 {value!r}")
    return (items[0], items[1])


def _tag_anchor(
    position: tuple[bool, bool, bool, bool] | tuple[float, float],
    *,
    location: str,
    inner: Box,
    panel_area: Box,
    width_cm: float,
    height_cm: float,
    hjust: float,
    vjust: float,
) -> tuple[float, float]:
    """tag 的文字锚点（页面 cm）。R `table_add_tag()` 的位置解析。

    `location = "margin"` 时 tag 放在 `plot.margin` 的对应边（调用方已把那条边
    扩到 tag 尺寸）；`"plot"` 用 `plot.margin` 内区，`"panel"` 用面板区。
    """
    if location == "margin":
        top, left, right, bottom = position  # type: ignore[misc]
        # 带区：只在该边的那一格；corner（topleft 等）是左带 × 顶带的交。
        cell_x = inner.x_cm - width_cm if left else (inner.right if right else inner.x_cm)
        cell_w = width_cm if (left or right) else inner.width_cm
        cell_y = inner.y_cm - height_cm if bottom else (inner.top if top else inner.y_cm)
        cell_h = height_cm if (top or bottom) else inner.height_cm
        x = cell_x + ((1.0 - hjust) * width_cm if (left or right) else hjust * cell_w)
        y = cell_y + ((1.0 - vjust) * height_cm if (top or bottom) else vjust * cell_h)
        return x, y
    area = panel_area if location == "panel" else inner
    if not isinstance(position, tuple) or len(position) != 4:
        x_npc, y_npc = position  # type: ignore[misc]
        return area.x_cm + x_npc * area.width_cm, area.y_cm + y_npc * area.height_cm
    top, left, right, bottom = position
    if left:
        x = area.x_cm + (1.0 - hjust) * width_cm
    elif right:
        x = area.right - (1.0 - hjust) * width_cm
    else:
        x = area.x_cm + hjust * area.width_cm
    if top:
        y = area.top - (1.0 - vjust) * height_cm
    elif bottom:
        y = area.y_cm + (1.0 - vjust) * height_cm
    else:
        y = area.y_cm + vjust * area.height_cm
    return x, y


def _axis_title_text(build: PlotBuild, aesthetic: str) -> str | None:
    explicit = _scale_axis_title(build, aesthetic)
    if explicit is not _UNSET_TITLE:
        return None if explicit is None else str(explicit)
    labels = getattr(build, "labels", {}) or {}
    if aesthetic in labels:
        value = labels[aesthetic]
        return None if value is None else str(value)
    # 上游 `setup_plot_labels()`：逐层的 computed mapping，`unlabelled` 的层
    # （`annotate()` 的 `aes_all()`）跳过。`raw_mappings` 已在 build 期按这个规则筛过。
    for mapping in getattr(build, "raw_mappings", ()):
        if aesthetic in mapping:
            return str(mapping[aesthetic])
    # 上游 `setup_plot_labels()` 的最后一级：`Stat$default_aes`（`after_stat()`）
    # 也参与轴标题（`geom_bar()` 只映射 `x` 时 y 轴标题是 `count`，不是空），
    # 例如 `geom_dotplot()` / `geom_histogram()` 的 y = "count"。
    for layer in getattr(build, "layers", ()):
        for name, source in _STAT_DEFAULT_AES.get(layer.stat, ()):
            if name == aesthetic:
                return source
    return None


def _guide_title(guide: Any, default: str | None) -> str | None:
    """guide 的 `title` 覆盖轴标题（R：guide 的设定优先于标度名）。

    `AUTO`（缺省）= 用 `default`；`None` = 不显示标题（`guide_none()` 的缺省）；
    其它值原样作为标题。
    """
    if guide is None:
        return default
    title = getattr(guide, "title", AUTO)
    if title is AUTO:
        return default
    if title is None:
        return None
    return str(title)


def _secondary_title(build: PlotBuild, aesthetic: str, scale: Any) -> str | None:
    """次轴的标题（R `AxisSecondary$make_title()`）。

    - `sec_axis(name="...")`：用这个名字；
    - `None`（= R 的 `waiver()` / `NULL`，也是 `sec_axis()` 的缺省）：**不显示标题**
      （R 给零高 `zeroGrob`，顶部不会多出 `xlab-t`）；
    - `DERIVE`（= R 的 `derive()`，`dup_axis()` 的缺省）：沿用主轴标题。
    """
    secondary = getattr(scale, "secondary_axis", None)
    name = getattr(secondary, "name", None) if secondary is not None else None
    if name is DERIVE:
        return _axis_title_text(build, aesthetic)
    if name is None:
        return None
    return str(name)


def _legend_position(theme: ResolvedTheme) -> str | None:
    value = theme.get("legend.position")
    if value is None:
        return "right"
    if isinstance(value, str):
        position = value
    else:
        # R：`legend.position = c(x, y)` 等价于 `"inside"` + `legend.position.inside`。
        try:
            items = list(value)
        except TypeError:
            items = []
        if len(items) == 2 and all(isinstance(item, (int, float)) for item in items):
            return "inside"
        raise GuideError(
            f"legend.position 无法解析：{value!r}；用 right / left / top / bottom / none / "
            "inside 或 c(x, y)"
        )
    if position not in ("right", "left", "top", "bottom", "none", "inside"):
        raise GuideError(
            f"legend.position 只能是 right / left / top / bottom / none / inside，收到 {position!r}"
        )
    return position


def plot_layout(
    build: PlotBuild,
    *,
    width_in: float = DEFAULT_WIDTH_IN,
    height_in: float = DEFAULT_HEIGHT_IN,
    metrics: Any = None,
) -> PlotLayout:
    """算整页版式（不画）：标题行、轴占位、图例盒、面板区与每面板矩形。"""
    theme = _theme_of(build)
    width_cm = float(width_in) * CM_PER_INCH
    height_cm = float(height_in) * CM_PER_INCH
    # `labs(tag=)`：R 的 `table_add_tag()` 会把 `plot.margin` 的对应边扩到 tag
    # 尺寸，再按 `plot.tag.location` 把 tag 放进 margin / plot / panel。这里先
    # 算尺寸与位置写法，扩完 margin 再算其余版式。
    tag_text = _label_text(build, "tag")
    tag_w, tag_h, tag_element = _tag_size(theme, tag_text, metrics)
    tag_position = _tag_position(theme)
    tag_numeric = not isinstance(tag_position[0], bool)
    tag_location = str(theme.get("plot.tag.location") or ("plot" if tag_numeric else "margin"))
    tag_has_label = (
        tag_text is not None and tag_w > 0 and tag_h > 0 and isinstance(tag_element, ElementText)
    )
    if tag_has_label and tag_numeric and tag_location == "margin":
        raise ValueError(
            "plot.tag.position 的数值形式不能与 plot.tag.location = 'margin' 同用"
            "（R 也报错：margin 里的 tag 只能按边定位）"
        )
    top, bottom, right, left = _plot_margin(theme)
    if tag_has_label and tag_location == "margin":
        tag_top, tag_left, tag_right, tag_bottom = tag_position  # type: ignore[misc]
        if tag_top:
            top += tag_h
        if tag_bottom:
            bottom += tag_h
        if tag_left:
            left += tag_w
        if tag_right:
            right += tag_w
    inner = Box(left, bottom, width_cm - left - right, height_cm - top - bottom)
    if inner.width_cm <= 0 or inner.height_cm <= 0:
        raise ValueError(
            f"plot.margin 吃掉了整页（{width_cm:.3f}×{height_cm:.3f}cm，"
            f"margin 上{top:.3f}/右{right:.3f}/下{bottom:.3f}/左{left:.3f}cm）"
        )

    title_text = _label_text(build, "title")
    subtitle_text = _label_text(build, "subtitle")
    caption_text = _label_text(build, "caption")
    title_cm, title_element = _text_row_cm(theme, "plot.title", title_text)
    subtitle_cm, _subtitle_element = _text_row_cm(theme, "plot.subtitle", subtitle_text)
    caption_cm, _caption_element = _text_row_cm(theme, "plot.caption", caption_text)

    position = _legend_position(theme)
    guides = build_guides(build) if position != "none" else ()
    guide_sides = tuple(guide.position or position for guide in guides)
    legend_layouts = tuple(
        legend_layout(guide, theme, side, metrics=metrics)
        for guide, side in zip(guides, guide_sides, strict=True)
    )
    # 同一方位的图例排进一个 `guide-box`；`inside` 是例外：R 4.0.3 里每张
    # `position = "inside"` 的图例各自是一个覆盖在面板上的 guide-box，各用各的
    # `legend.position.inside` / `justification.inside`（可能来自 guide 自己的
    # `theme=`），所以按 guide 分组（SIL-788）。
    group_indices: dict[str, list[int]] = {}
    for index, side in enumerate(guide_sides):
        key = f"inside:{index}" if side == "inside" else str(side)
        group_indices.setdefault(key, []).append(index)
    box_positions: dict[str, str] = {
        key: str(guide_sides[indices[0]]) for key, indices in group_indices.items()
    }
    box_layouts = {
        key: legend_box_layout(
            [legend_layouts[index] for index in indices], box_positions[key], theme
        )
        for key, indices in group_indices.items()
    }

    x_axis = 0.0
    y_axis = 0.0
    x_axis_top = 0.0
    y_axis_right = 0.0
    x_title_top = 0.0
    y_title_right = 0.0
    secondary_x = False
    secondary_y = False
    x_side = "bottom"
    y_side = "left"
    guide_x = guide_for(build, "x")
    guide_y = guide_for(build, "y")
    for panel, params in _panels(build):
        scale_bottom_layout = _panel_scale(build, panel, params.scale_key("bottom"))
        scale_left_layout = _panel_scale(build, panel, params.scale_key("left"))
        x_side = _scale_side(scale_bottom_layout, "bottom")
        y_side = _scale_side(scale_left_layout, "left")
        ticks_x = axis_ticks(scale_bottom_layout, params, x_side)
        ticks_y = axis_ticks(scale_left_layout, params, y_side)
        radial = params.polar is not None and bool(getattr(params.polar, "radial", False))
        guide_x = guide_for(build, "x")
        # `coord_radial()` 的主 r 轴读 `guides(r = ...)`（上游 `setup_panel_guides()`
        # 只登记 r / theta / r.sec / theta.sec 四个位置），直角坐标才读 `y`。
        guide_y = guide_for(build, "r") if radial else guide_for(build, "y")
        if params.polar is not None:
            # θ 标签画在面板里，但 `axis-b` 行不一定在：
            # - `coord_polar()`：上游 `render_axis_h()` 给 `draw_axis(NA, "", "bottom")`，
            #   空标签也占一行（刻度 + 文字行高）；
            # - `coord_radial()`：`render_axis_h()` 委托给 `CoordCartesian`，而 radial
            #   的 `panel_params` 只有 `theta` / `r` 两组 view scale、没有 `x`，于是
            #   拿到的是一对 zeroGrob——**任何** `r.axis.inside` 取值下 bottom 行都是 0
            #   （R 的 gtable 实测：`guide-axis-theta with angle adapting` 的 row 10
            #   高度为 0，只有 xlab 行 12.97pt）。
            if not params.polar.radial:
                x_axis = max(x_axis, polar_axis_row_cm(theme))
        if params.polar is None:
            guide_ticks_x = axis_guide_ticks(
                scale_bottom_layout,
                params,
                x_side,
                guide_x,
                theme,
                base=ticks_x,
            )
            extent_x = axis_guide_extent(
                theme, guide_ticks_x, guide_x, side=x_side, metrics=metrics
            )
            if x_side == "top":
                x_axis_top = max(x_axis_top, extent_x)
                x_title_top = max(
                    x_title_top,
                    axis_title_extent(
                        theme,
                        "top",
                        _guide_title(guide_x, _axis_title_text(build, "x")),
                        metrics=metrics,
                    ),
                )
            else:
                x_axis = max(x_axis, extent_x)
        # `coord_radial()` 的 r 轴走 `theme_suffix = "r"`（`axis.text.r` 两侧都有
        # margin、`hjust = 0.5`），与直角坐标的 `axis.text.y` 不同。
        axis_theme = _axis_guide_theme(theme, params, guide_y)
        guide_ticks_y = axis_guide_ticks(
            scale_left_layout,
            params,
            y_side,
            guide_y,
            axis_theme,
            base=ticks_y,
        )
        extent_y = axis_guide_extent(
            axis_theme, guide_ticks_y, guide_y, side=y_side, metrics=metrics
        )
        if radial and params.polar.r_axis_inside:
            # 面板内的 r 轴不占 gtable 列（上游 `render_axis_v()` 给的是
            # `zeroGrob()`）：轴标签画在面板里，axis-l / axis-r 两列宽度为 0。
            extent_y = 0.0
        if y_side == "right":
            y_axis_right = max(y_axis_right, extent_y)
            y_title_right = max(
                y_title_right,
                axis_title_extent(
                    theme,
                    "right",
                    _guide_title(guide_y, _axis_title_text(build, "y")),
                    metrics=metrics,
                ),
            )
        else:
            y_axis = max(y_axis, extent_y)
        if radial:
            # `guides(r.sec = guide_axis(...))`：径向的次 r 轴占一条 **axis-r 列**
            # （上游 `setup_panel_guides()` 把 r / r.sec 排成 left / right 两个
            # `panel_params$guides` 位置，轴线由 `panel_guides_grob(position)`
            # 画进 gtable 的同名槽）。缺这条列整表会横移一个轴宽（SIL-843 实测
            # 8.45pt）。`r.axis.inside` 为真时两条 r 轴都在面板里，不占列。
            guide_rsec = guide_for(build, "r.sec")
            if guide_rsec is not None:
                # 标题始终占一列（`axis.title.y.right`）——即使 r.sec 画在面板里
                # （`r.axis.inside`），R 的 ylab-r 列照样在。
                y_title_right = max(
                    y_title_right,
                    axis_title_extent(
                        theme,
                        "right",
                        _guide_title(guide_rsec, None),
                        metrics=metrics,
                    ),
                )
            if guide_rsec is not None and not params.polar.r_axis_inside:
                rsec_theme = _axis_guide_theme(theme, params, guide_rsec)
                ticks_rsec = axis_guide_ticks(
                    scale_left_layout,
                    params,
                    "right",
                    guide_rsec,
                    rsec_theme,
                    base=ticks_y,
                )
                y_axis_right = max(
                    y_axis_right,
                    axis_guide_extent(
                        rsec_theme, ticks_rsec, guide_rsec, side="right", metrics=metrics
                    ),
                )
        top_scale = _panel_scale(build, panel, params.scale_key("top"))
        right_scale = _panel_scale(build, panel, params.scale_key("right"))
        if has_secondary_axis(build, "x", top_scale):
            secondary_x = True
            guide_top = secondary_axis_guide(build, "x", top_scale)
            ticks_top = axis_guide_ticks(
                top_scale,
                params,
                "top",
                guide_top,
                theme,
                secondary=getattr(top_scale, "secondary_axis", None) is not None,
                base=_secondary_ticks(build, top_scale, params, "top", "x"),
            )
            x_axis_top = max(
                x_axis_top,
                axis_guide_extent(theme, ticks_top, guide_top, side="top", metrics=metrics),
            )
            x_title_top = max(
                x_title_top,
                axis_title_extent(
                    theme,
                    "top",
                    _guide_title(
                        secondary_axis_guide(build, "x", top_scale),
                        _secondary_title(build, params.scale_key("top"), top_scale),
                    ),
                    metrics=metrics,
                ),
            )
        if has_secondary_axis(build, "y", right_scale):
            secondary_y = True
            guide_right = secondary_axis_guide(build, "y", right_scale)
            ticks_right = axis_guide_ticks(
                right_scale,
                params,
                "right",
                guide_right,
                theme,
                secondary=getattr(right_scale, "secondary_axis", None) is not None,
                base=_secondary_ticks(build, right_scale, params, "right", "y"),
            )
            y_axis_right = max(
                y_axis_right,
                axis_guide_extent(theme, ticks_right, guide_right, side="right", metrics=metrics),
            )
            y_title_right = max(
                y_title_right,
                axis_title_extent(
                    theme,
                    "right",
                    _guide_title(
                        secondary_axis_guide(build, "y", right_scale),
                        _secondary_title(build, params.scale_key("right"), right_scale),
                    ),
                    metrics=metrics,
                ),
            )
    # `position = "top"` / `"right"` 时主轴标题也在那一侧（上面的循环已经把
    # 占位记进 x_title_top / y_title_right），原侧不再占一行 / 一列。
    x_title_text = _guide_title(guide_x, _axis_title_text(build, "x"))
    y_title_text = _guide_title(guide_y, _axis_title_text(build, "y"))
    if x_side == "top":
        x_title = 0.0
    else:
        x_title = axis_title_extent(theme, x_side, x_title_text, metrics=metrics)
    if y_side == "right":
        y_title = 0.0
    else:
        y_title = axis_title_extent(theme, y_side, y_title_text, metrics=metrics)
    if not build.layers:
        # R：没有图层（`ggplot()` + `guides(custom=...)`）时没有任何轴，面板直接
        # 铺满 `plot.margin` 内区（`guides/stylised-guide-custom` 实测边距 5.48pt）。
        x_axis = y_axis = x_axis_top = y_axis_right = 0.0
        x_title = y_title = x_title_top = y_title_right = 0.0

    spacing = _box_spacing_cm(theme)
    right_box = box_layouts.get("right")
    left_box = box_layouts.get("left")
    top_box = box_layouts.get("top")
    bottom_box = box_layouts.get("bottom")
    right_extent = right_box.width_cm + spacing if right_box is not None else 0.0
    left_extent = left_box.width_cm + spacing if left_box is not None else 0.0
    top_extent = top_box.height_cm + spacing if top_box is not None else 0.0
    bottom_extent = bottom_box.height_cm + spacing if bottom_box is not None else 0.0

    content_top = inner.top - title_cm - subtitle_cm
    content_bottom = inner.y_cm + caption_cm
    content_left = inner.x_cm
    content_right = inner.right
    content_right -= right_extent
    content_left += left_extent
    content_top -= top_extent
    content_bottom += bottom_extent

    table = build.facet_table(
        metrics=metrics,
        right_inside=secondary_y,
        axis_x_cm=(2.0 * tick_length_cm(theme, "bottom") if _draw_axes(build)[0] else 0.0),
        axis_y_cm=(2.0 * tick_length_cm(theme, "left") if _draw_axes(build)[1] else 0.0),
    )
    # `strip.placement = "outside"`：strip 放到轴的外侧（R 的 `attach_strips()`
    # 里 shift=2）。没有轴的一侧两者视觉等价，这里只在「外侧」时把 strip 块
    # 从面板区里让出来，画在轴带之外。
    strip_band_top = table.strip_height_cm if table.top_placement == "outside" else 0.0
    strip_band_right = table.strip_width_cm if table.right_placement == "outside" else 0.0
    facet_kind = getattr(build.facet, "kind", "null")
    strip_pad_x = _strip_switch_pad(theme, facet_kind) if x_axis_top > 0 and strip_band_top else 0.0
    strip_pad_y = (
        _strip_switch_pad(theme, facet_kind) if y_axis_right > 0 and strip_band_right else 0.0
    )
    panel_bottom = content_bottom + x_axis + x_title
    panel_left = content_left + y_axis + y_title
    panel_right = content_right - y_axis_right - y_title_right - strip_band_right - strip_pad_y
    panel_top = content_top - x_axis_top - x_title_top - strip_band_top - strip_pad_x
    panel_area = Box(
        panel_left,
        panel_bottom,
        panel_right - panel_left,
        panel_top - panel_bottom,
    )
    if panel_area.width_cm <= 0 or panel_area.height_cm <= 0:
        raise ValueError(
            "轴 / 图例 / 标题吃掉了整块面板区："
            f"面板区 {panel_area.width_cm:.3f}×{panel_area.height_cm:.3f}cm"
            "（页太小，或主题里的 spacing 过大）"
        )
    top_strip_band = (
        Box(panel_left, content_top - strip_band_top, panel_right - panel_left, strip_band_top)
        if strip_band_top > 0
        else None
    )
    right_strip_band = (
        Box(
            panel_right + strip_pad_y,
            panel_bottom,
            strip_band_right,
            panel_top - panel_bottom,
        )
        if strip_band_right > 0
        else None
    )
    panel_area = _aspect_panel_area(build, panel_area, table)
    facet_boxes = table.panel_boxes(panel_area.width_cm, panel_area.height_cm)
    panel_boxes = {
        panel: Box(
            panel_area.x_cm + box.x_cm,
            panel_area.y_cm + box.y_cm,
            box.width_cm,
            box.height_cm,
        )
        for panel, box in facet_boxes.items()
    }

    plot_position = theme.get("plot.title.position") == "plot"
    title_box = None
    if title_text is not None and title_cm > 0 and isinstance(title_element, ElementText):
        title_x = inner.x_cm if plot_position else panel_area.x_cm
        title_width = inner.width_cm if plot_position else panel_area.width_cm
        title_box = Box(title_x, inner.top - title_cm, title_width, title_cm)
    subtitle_box = None
    if subtitle_text is not None and subtitle_cm > 0:
        subtitle_x = inner.x_cm if plot_position else panel_area.x_cm
        subtitle_width = inner.width_cm if plot_position else panel_area.width_cm
        subtitle_box = Box(
            subtitle_x, inner.top - title_cm - subtitle_cm, subtitle_width, subtitle_cm
        )
    caption_box = None
    if caption_text is not None and caption_cm > 0:
        caption_position = theme.get("plot.caption.position") == "plot"
        caption_x = inner.x_cm if caption_position else panel_area.x_cm
        caption_width = inner.width_cm if caption_position else panel_area.width_cm
        caption_box = Box(caption_x, inner.y_cm, caption_width, caption_cm)

    # 竖向图例的居中区是**panel 单元格的并集**，不是整个 `panel_area`。
    # R 里 facet 的 strip 是 gtable 的独立行，guide 列只跨 panel 行：顶部 /
    # 底部 strip 带不算进去（行间的 strip 与 panel.spacing 夹在 panel 之间，
    # 取并集时自然落在里面，不影响包围盒）。SIL-725。
    panel_rows = panel_area
    if panel_boxes:
        rows_bottom = min(box.y_cm for box in panel_boxes.values())
        rows_top = max(box.top for box in panel_boxes.values())
        panel_rows = Box(panel_area.x_cm, rows_bottom, panel_area.width_cm, rows_top - rows_bottom)

    # 横向图例（top / bottom）的水平居中区同理是**panel 单元格的并集**：
    # facet_grid 的行 strip 自带一列（`strip.placement = "inside"` 时它在
    # `panel_area` 里面），R 的 guide-box-bottom 只跨 panel 列，不跨 strip 列。
    # 拿 `panel_area` 居中会把图例往右推半个 strip 宽（SIL-743：margins 3×3）。
    panel_cols = panel_area
    if panel_boxes:
        cols_left = min(box.x_cm for box in panel_boxes.values())
        cols_right = max(box.right for box in panel_boxes.values())
        panel_cols = Box(cols_left, panel_area.y_cm, cols_right - cols_left, panel_area.height_cm)

    # stretchy key（`legend.key.height / width = unit(1, "null")`）：guide-box 在
    # left / right 上占 panel 行高、top / bottom 上占 panel 列宽，剩余尺寸按
    # null 权重分回每张图例（R 的 `redistribute_null_units()`）。inside 是覆盖式
    # 的盒子，不参与这套分配。
    if legend_layouts:
        stretched = list(legend_layouts)
        for key, indices in group_indices.items():
            side = box_positions[key]
            if side == "inside":
                continue
            direction = legend_box_direction(theme, side)
            target = panel_rows.height_cm if direction == "vertical" else panel_cols.width_cm
            box = box_layouts[key]
            current = box.height_cm if direction == "vertical" else box.width_cm
            total_null = sum(
                legend_layouts[index].null_h
                if direction == "vertical"
                else legend_layouts[index].null_w
                for index in indices
            )
            if total_null > 0 and target > current + 1e-9:
                extra = target - current
                for index in indices:
                    weight = (
                        legend_layouts[index].null_h
                        if direction == "vertical"
                        else legend_layouts[index].null_w
                    )
                    if weight <= 0:
                        continue
                    part = extra * weight / total_null
                    if direction == "vertical":
                        stretched[index] = legend_layout(
                            guides[index],
                            theme,
                            guide_sides[index],
                            metrics=metrics,
                            stretch_h=part,
                        )
                    else:
                        stretched[index] = legend_layout(
                            guides[index],
                            theme,
                            guide_sides[index],
                            metrics=metrics,
                            stretch_w=part,
                        )
            # 间隔是 null（`legend.spacing.y = unit(1, "null")`）时由盒子自己把
            # 剩余尺寸摊给间隔，所以这一趟总是带上目标尺寸重排。
            box_layouts[key] = legend_box_layout(
                [stretched[index] for index in indices],
                side,
                theme,
                target_height=panel_rows.height_cm,
                target_width=panel_cols.width_cm,
            )
        legend_layouts = tuple(stretched)

    legend_boxes: list[Box | None] = [None] * len(guides)
    legend_box_origins: list[Box] = []
    legend_box_layouts: list[Any] = []
    for key in (
        key
        for side in ("top", "right", "bottom", "left", "inside")
        for key in group_indices
        if box_positions[key] == side
    ):
        indices = group_indices[key]
        side = box_positions[key]
        box_layout = box_layouts[key]
        origin = _place_legend_box(
            box_layout,
            position=side,
            inner=inner,
            panel_area=panel_area,
            panel_rows=panel_rows,
            panel_cols=panel_cols,
            content_top=content_top,
            spacing=spacing,
            caption_cm=caption_cm,
            theme=(theme if side != "inside" else guide_theme(theme, guides[indices[0]].guide)),
        )
        legend_box_origins.append(origin)
        legend_box_layouts.append(box_layout)
        for offset, index in zip(box_layout.boxes, indices, strict=True):
            legend_boxes[index] = Box(
                origin.x_cm + offset.x_cm,
                origin.y_cm + offset.y_cm,
                offset.width_cm,
                offset.height_cm,
            )
    legend_boxes = [box for box in legend_boxes if box is not None]

    tag_box = None
    if tag_has_label and isinstance(tag_element, ElementText):
        tag_hjust = float(tag_element.hjust) if tag_element.hjust is not None else 0.5
        tag_vjust = float(tag_element.vjust) if tag_element.vjust is not None else 0.5
        tag_x, tag_y = _tag_anchor(
            tag_position,
            location=tag_location,
            inner=inner,
            panel_area=panel_area,
            width_cm=tag_w,
            height_cm=tag_h,
            hjust=tag_hjust,
            vjust=tag_vjust,
        )
        tag_box = Box(tag_x, tag_y, 0.0, 0.0)

    return PlotLayout(
        width_cm=width_cm,
        height_cm=height_cm,
        margin_cm=(top, right, bottom, left),
        title=title_box,
        title_text=title_text,
        subtitle=subtitle_box,
        subtitle_text=subtitle_text,
        caption=caption_box,
        caption_text=caption_text,
        panel_area=panel_area,
        x_axis_cm=x_axis,
        y_axis_cm=y_axis,
        x_title_cm=x_title,
        y_title_cm=y_title,
        title_cm=title_cm,
        subtitle_cm=subtitle_cm,
        caption_cm=caption_cm,
        panel_boxes=panel_boxes,
        legend_side=position if legend_layouts else None,
        legend_layouts=legend_layouts,
        legend_boxes=tuple(legend_boxes),
        legend_box_layouts=tuple(legend_box_layouts),
        legend_box_origins=tuple(legend_box_origins),
        guides=guides,
        x_axis_top_cm=x_axis_top,
        y_axis_right_cm=y_axis_right,
        x_title_top_cm=x_title_top,
        y_title_right_cm=y_title_right,
        secondary_x=secondary_x,
        secondary_y=secondary_y,
        top_strip_band=top_strip_band,
        right_strip_band=right_strip_band,
        tag=tag_box,
        tag_text=tag_text if tag_box is not None else None,
        tag_element=tag_element if tag_box is not None else None,
        facet_table=table,
    )


def _aspect_panel_area(build: PlotBuild, area: Box, table: FacetTable) -> Box:
    """把面板区收成 `respect = TRUE` 要求的等比例（R `Facet$init_gtable()`）。

    R 把 aspect 折进行权重（`heights × |aspect|`）后交给 grid 的 `respect`：
    null 宽与 null 高取**同一物理尺寸**，于是每个面板的高/宽 = 行权重 / 列权重
    （`space = "free"` 时 = `ratio × yspan / xspan`）。这里只做等比例 null 的
    最大内接矩形（等价 aspect = 1），多出来的空间居中；不再拿首面板的
    `aspect_ratio` 去乘范围权重（SIL-759：那会把 `yspan / xspan` 乘两次）。

    `respect = FALSE`（坐标自由）时原样返回。
    """
    if not table.respect:
        return area
    boxes = table.panel_boxes(area.width_cm, area.height_cm)
    if not boxes:
        return area
    ncol = max(1, table.layout.ncol)
    nrow = max(1, table.layout.nrow)
    width_weights = table.width_weights or (1.0,) * ncol
    height_weights = table.height_weights or (1.0,) * nrow
    first = next(iter(boxes.values()))
    scale_w = first.width_cm / width_weights[0] if width_weights[0] else first.width_cm
    scale_h = first.height_cm / height_weights[0] if height_weights[0] else first.height_cm
    extra_w = area.width_cm - scale_w * sum(width_weights)
    extra_h = area.height_cm - scale_h * sum(height_weights)
    # `respect = TRUE`：1 个 null 宽 = 1 个 null 高，取两块都能放下的公共尺寸。
    cell = min(
        (area.width_cm - extra_w) / sum(width_weights),
        (area.height_cm - extra_h) / sum(height_weights),
    )
    used_w = cell * sum(width_weights) + extra_w
    used_h = cell * sum(height_weights) + extra_h
    if abs(used_w - area.width_cm) < 1e-12 and abs(used_h - area.height_cm) < 1e-12:
        return area
    x = area.x_cm + (area.width_cm - used_w) / 2.0
    y = area.y_cm + (area.height_cm - used_h) / 2.0
    return Box(x, y, used_w, used_h)


def _place_legend_box(
    box_layout: Any,
    *,
    position: str,
    inner: Box,
    panel_area: Box,
    panel_rows: Box,
    panel_cols: Box,
    content_top: float,
    spacing: float,
    caption_cm: float,
    theme: ResolvedTheme,
) -> Box:
    """一个方位的 `guide-box` 在页面上的矩形。

    竖向（right / left）在**panel 行**（`panel_rows`，所有面板单元格的并集）里
    垂直居中：R 把 guide-box 挂在 panel 行上的 0.5null 里，facet 的顶部 / 底部
    strip 带不在这一行，所以分面时图例比整个 `panel_area` 的中心低半个 strip。
    横向（top / bottom）贴着内容区的上/下边缘：top 在副标题行之下
    （`content_top` 已经扣掉了 `legend.box.spacing`），bottom 在注脚之上；
    水平居中用 `panel_cols`（panel 单元格的并集），与 R 的 guide-box 只跨
    panel 列（不跨 facet 的行 strip 列）一致。
    inside 用 `legend.position.inside`（npc）+ `legend.justification.inside`
    锚在面板区内，不占版面。
    """
    width = float(box_layout.width_cm)
    height = float(box_layout.height_cm)
    # `legend.location = "plot"`：guide-box 相对整块绘图区定位（`plot_extent`），
    # 否则相对 panel 行 / 列；`legend.justification.<position>` 决定贴哪个角。
    plot_location = str(theme.get("legend.location") or "panel") == "plot"
    rows = inner if plot_location else panel_rows
    cols = inner if plot_location else panel_cols
    if position == "right":
        # 贴着 panel 单元格的右边（R 的 guide-box 列紧挨 panel 列），不是页面
        # 内区的右边：等比例面板（`coord_polar()` 的正圆）比内区窄，剩下的
        # 空白留在图例右侧。
        x = (inner.right if plot_location else panel_area.right) + (
            0.0 if plot_location else spacing
        )
        _, yjust = legend_justification(theme, position)
        y = rows.y_cm + yjust * (rows.height_cm - height)
        return Box(x, y, width, height)
    if position == "left":
        x = inner.x_cm if plot_location else panel_area.x_cm - spacing - width
        _, yjust = legend_justification(theme, position)
        y = rows.y_cm + yjust * (rows.height_cm - height)
        return Box(x, y, width, height)
    if position == "top":
        y = content_top + spacing
        xjust, _ = legend_justification(theme, position)
        x = cols.x_cm + xjust * (cols.width_cm - width)
        return Box(x, y, width, height)
    if position == "bottom":
        y = inner.y_cm + caption_cm
        xjust, _ = legend_justification(theme, position)
        x = cols.x_cm + xjust * (cols.width_cm - width)
        return Box(x, y, width, height)
    # inside
    anchor_x, anchor_y = _inside_position(theme)
    just_x, just_y = _inside_justification(theme)
    x = panel_area.x_cm + anchor_x * panel_area.width_cm - just_x * width
    y = panel_area.y_cm + anchor_y * panel_area.height_cm - just_y * height
    return Box(x, y, width, height)


def _inside_position(theme: ResolvedTheme) -> tuple[float, float]:
    """`legend.position.inside`（npc 0..1）；缺省沿用 `legend.justification.inside`。"""
    value = theme.get("legend.position.inside")
    if value is None:
        value = theme.get("legend.position")
    if isinstance(value, str):
        value = None
    if value is None:
        return (0.5, 0.5)
    try:
        items = list(value)
    except TypeError:
        return (0.5, 0.5)
    if len(items) != 2:
        raise GuideError(f"legend.position.inside 需要 c(x, y)，收到 {value!r}")
    return (float(items[0]), float(items[1]))


def _inside_justification(theme: ResolvedTheme) -> tuple[float, float]:
    value = theme.get("legend.justification.inside")
    if value is None:
        value = theme.get("legend.justification")
    if value is None:
        return (0.5, 0.5)
    if isinstance(value, str):
        mapping = {
            "left": (0.0, 0.5),
            "right": (1.0, 0.5),
            "top": (0.5, 1.0),
            "bottom": (0.5, 0.0),
            "center": (0.5, 0.5),
            "centre": (0.5, 0.5),
        }
        return mapping.get(value.lower(), (0.5, 0.5))
    try:
        items = list(value)
    except TypeError:
        return (0.5, 0.5)
    if len(items) == 1:
        return (float(items[0]), float(items[0]))
    if len(items) >= 2:
        return (float(items[0]), float(items[1]))
    return (0.5, 0.5)


def _strip_switch_pad(theme: ResolvedTheme, kind: str) -> float:
    """`strip.placement = "outside"` 时 strip 与轴之间的间隙（cm）。

    上游用 `strip.switch.pad.grid`（facet_grid）/ `strip.switch.pad.wrap`
    （facet_wrap），且只在**有轴**的那一侧才留：R 的 `attach_strips()` 先看
    `table_has_grob(table, "axis-t")`。
    """
    from ggcore.units import convert_height

    name = "strip.switch.pad.grid" if kind == "grid" else "strip.switch.pad.wrap"
    value = theme.get(name)
    if value is None:
        return 0.0
    return float(np.asarray(convert_height(value, "cm", ctx=UnitContext())).sum())


def _box_spacing_cm(theme: ResolvedTheme) -> float:
    from ggcore.units import convert_width

    value = theme.get("legend.box.spacing")
    if value is None:
        return 0.0
    return float(np.asarray(convert_width(value, "cm", ctx=UnitContext())).sum())


def _panel_scale(build: PlotBuild, panel: int, aesthetic: str) -> Any:
    for item in build.panels:
        if item.panel == panel:
            return item.scales.scale(aesthetic)
    return build.scales.scale(aesthetic)


# ---------------------------------------------------------------------------
# 面板与图层
# ---------------------------------------------------------------------------


def _panels(build: PlotBuild) -> list[tuple[int, PanelParams]]:
    if build.panels:
        return [(panel.panel, panel.panel_params) for panel in build.panels]
    if build.panel_params is not None:
        return [(1, build.panel_params)]
    coord = build.coord if build.coord is not None else CoordBase()
    return [(1, coord.panel_params(build.scales))]


def _prepare_layer(layer: LayerBuild) -> LayerBuild:
    """`Layer$draw_geom()` 的第一步：绘制期删行（每层一次，不是每面板一次）。"""
    geom = _geom_of(layer)
    na_rm = bool(layer.params.get("na_rm", False))
    data = geom.handle_na(layer.data, na_rm)
    return layer if data is layer.data else replace(layer, data=data)


def _panel_children(
    build: PlotBuild,
    layers: list[LayerBuild],
    panel: int,
    params: PanelParams,
    theme: ResolvedTheme,
    metrics: Any,
    *,
    panel_size_in: tuple[float, float] | None = None,
    theme_key: bytes | None = None,
) -> list[Any]:
    children: list[Any] = []
    for name, border_only in (("panel.background", False),):
        element = theme.get(name)
        if isinstance(element, ElementRect):
            if params.polar is not None and params.polar.radial and not border_only:
                # R 的 `guide_grid(square = FALSE)` 把 `panel.background` 换成
                # `c(±Inf)` 的 polygon 再 `coord_munch`：满圆 munched 之后是
                # **外圆 − 内圆的圆环**（SIL-843 实测：上游 SVG 的 `#EBEBEB`
                # polygon 是 317 点的双环，不是外接方形）。铺满 cell 会让四角与
                # 内孔都多出一圈灰底。
                grob = _radial_panel_background(params.polar, element, name=name)
            else:
                grob = _rect_from_element(element, border_only=border_only, name=name)
            if grob is not None:
                children.append(grob)

    # 网格线顺序照 ggplot2 的 panel gtable：major 在 minor 之下，两者都在面板
    # 边框 / 图层之下（R 4.0.3 的 guide_grid() 只由主题元素给颜色、线型与线宽）。
    # 极坐标 / 径向坐标换成「辐条 + 同心圆」（`CoordPolar$render_bg()` /
    # `guide_grid()` 的极坐标形态）。
    if params.polar is not None:
        for kind in ("major", "minor"):
            children.extend(_polar_grid_grobs(build, panel, params, theme, kind=kind))
    elif params.map_geom is not None:
        children.extend(_map_grid_grobs(build, panel, params, theme))
    elif params.sf is not None:
        children.extend(_sf_grid_grobs(params, theme))
    else:
        for kind in ("major", "minor"):
            for axis in ("x", "y"):
                grid = _grid_grob(build, panel, params, theme, kind=kind, axis=axis)
                if grid is not None:
                    children.append(grid)

    element = theme.get("panel.border")
    if isinstance(element, ElementRect):
        grob = _rect_from_element(element, border_only=True, name="panel.border")
        if grob is not None:
            children.append(grob)

    layer_grobs: list[Any] = []
    draw_params = params
    if panel_size_in is not None:
        draw_params = replace(
            params,
            panel_width_in=float(panel_size_in[0]),
            panel_height_in=float(panel_size_in[1]),
        )
    for index, layer in enumerate(layers):
        data = _panel_rows(layer.data, panel)
        if data is None or data.nrows == 0:
            continue
        geom = _geom_of(layer)
        panel_layer = replace(layer, data=data)
        # 整层一个 `layer_tag`：R 的 `pattern()` 内容按整层 grob 的 bbox 折 npc
        # （SIL-833），同一层拆成多条指令时靠它把 bbox 取并集。
        tag = f"panel-{panel}-layer-{index}"
        grob = _draw_layer(
            panel_layer, geom, panel, draw_params, build, theme, theme_key, metrics, tag=tag
        )
        if isinstance(grob, (NullGrob, ZeroGrob)):
            continue
        layer_grobs.append(grob)
    if _clip_state(params.clip) == "on":
        # 面板视口的 clip="on"：R 把背景、网格、边框与图层都放进面板视口裁剪，
        # 面板边框的半条线宽因此被切在面板内（`theme_bw()` 的边缘就是靠这一步
        # 与参考图对齐的）。IR 里是一个 clip 容器（与视口裁剪取交）。
        children.extend(layer_grobs)
        if not children:
            return []
        return [clip_path(*children, x=0.0, y=0.0, width=1.0, height=1.0, name="panel-clip")]
    children.extend(layer_grobs)
    return children


def _draw_layer(
    layer: LayerBuild,
    geom: Any,
    panel: int,
    params: PanelParams,
    build: PlotBuild,
    theme: ResolvedTheme,
    theme_key: bytes | None,
    metrics: Any,
    *,
    tag: str,
) -> Any:
    """`geom.draw()`，带内容键缓存（M3-5 增量重算）。

    键覆盖 geom 读到的全部输入：图层数据（`_panel_rows` 之后那一份）、图层参数、
    面板号与面板参数、主题（几何会读 `geom.<class>` 元素）、度量实例。命中时
    返回的是同一份**不可变** grob（`frozen` dataclass），后续遍历照常。

    `tag` 是整层的 `layer_tag`（SIL-833）：写进 grob 后由遍历期继承给每条指令，
    写 IR 时同标记的指令取并集当填充 bbox。命中缓存时也要保证标签是当前这一层
    的——缓存键不区分同面板的图层序号，两层内容完全一样时会共用一份 grob。

    主题指纹每张场景算一次（`_theme_fingerprint`），不进每个图层的键开销。
    """
    cache = layer_draw_cache()
    if cache is None:
        return replace(geom.draw(layer, params, build.coord, theme, metrics), layer_tag=tag)
    from ggcore.perf import fingerprint, table_fingerprint

    key = (
        layer.geom,
        panel,
        table_fingerprint(layer.data),
        fingerprint(layer.params),
        fingerprint(params),
        # `coord_radial(rotate.angle = TRUE)` 改的是 geom 读到的 `angle` 美学，
        # 不体现在 `PanelParams` 上（`polar` 里没有这个字段），漏进键里会让
        # 同一份数据的两张图共用一份 grob。
        bool(getattr(build.coord, "rotate_angle", False)),
        theme_key,
    )
    cached = cache.get(key, metrics)
    if cached is not None:
        # 命中时 grob 已经带着上一次的 `layer_tag`（同一个面板 + 同一个 key），
        # 但缓存不区分图层序号，顺手改写成当前标签，免得两层共用一份。
        return cached if cached.layer_tag == tag else replace(cached, layer_tag=tag)
    grob = replace(geom.draw(layer, params, build.coord, theme, metrics), layer_tag=tag)
    cache.put(key, grob, metrics, layer.data.nrows)
    return grob


def _theme_fingerprint(theme: ResolvedTheme) -> bytes:
    """主题的内容指纹（每张场景算一次，进每个图层的键）。"""
    from ggcore.perf import fingerprint

    return fingerprint(theme.elements)


def _grid_positions(
    scale: Any, params: PanelParams, axis: str, *, minor: bool
) -> tuple[float, ...]:
    """一个面板的网格位置（npc 0..1），断点口径与 `axis_ticks()` 同源。

    major 用该面板标度的主断点，minor 用 `scale.minor_breaks()`（连续标度是相邻
    主断点的中点，越界端点也算，取完再按面板范围过滤）；离散标度没有次要网格。
    越界断点（`None`）不画。
    """
    if scale is None:
        return ()
    values = scale.minor_breaks() if minor else scale.breaks()
    discrete = bool(getattr(scale, "discrete", False))
    levels = tuple(scale.levels) if discrete else ()
    positions: list[float] = []
    for value in values:
        if value is None:
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
        if -1e-9 <= position <= 1.0 + 1e-9:
            positions.append(min(max(position, 0.0), 1.0))
    return tuple(positions)


def _grid_grob(
    build: PlotBuild,
    panel: int,
    params: PanelParams,
    theme: ResolvedTheme,
    *,
    kind: str,
    axis: str,
) -> Any | None:
    """一条网格线（`panel.grid.<kind>.<axis>`）；元素 blank / 颜色 NA 时返回 None。"""
    name = f"panel.grid.{kind}.{axis}"
    element = theme.get(name)
    if not isinstance(element, ElementLine):
        return None
    colour = paint(element.colour)
    if colour is None:
        return None
    scale = _panel_scale(build, panel, params.scale_key(axis))
    positions = _grid_positions(scale, params, axis, minor=kind == "minor")
    if not positions:
        return None
    gp = gpar(
        col=colour,
        lwd=_mm_to_pt(element.linewidth),
        lty=element.linetype if element.linetype is not None else 1,
        lineend=element.lineend or "butt",
        linejoin=element.linejoin or "round",
    )
    if axis == "x":
        return segments_grob(
            positions,
            [0.0] * len(positions),
            positions,
            [1.0] * len(positions),
            default_units="npc",
            gp=gp,
            name=name,
        )
    return segments_grob(
        [0.0] * len(positions),
        positions,
        [1.0] * len(positions),
        positions,
        default_units="npc",
        gp=gp,
        name=name,
    )


def _map_grid_grobs(
    build: PlotBuild,
    panel: int,
    params: PanelParams,
    theme: ResolvedTheme,
) -> list[Any]:
    """`CoordMap$render_bg()`：面板网格 = 投影后的经纬线（直线在投影里会弯）。

    与线性坐标的 `_grid_grob()` 不同，这里每条网格线是**折线**：R 在 ±0.2 倍
    跨度的展开范围上取 50 个采样点（再按半个地球夹到 ±180° / ±90°），逐点
    `transform()`。`CoordMap$render_bg()` 只画 major（次网格没有对应的绘制），
    x / y 分别取 `panel.grid.major.x` / `.y` 的样式。
    """
    grobs: list[Any] = []
    for axis in ("x", "y"):
        other = "y" if axis == "x" else "x"
        name = f"panel.grid.major.{axis}"
        element = theme.get(name)
        if not isinstance(element, ElementLine):
            continue
        colour = paint(element.colour)
        if colour is None:
            continue
        scale = _panel_scale(build, panel, params.scale_key(axis))
        if scale is None:
            continue
        low, high = params.x_range if axis == "x" else params.y_range
        span = float(high) - float(low)
        sample_low, sample_high = float(low) - 0.2 * span, float(high) + 0.2 * span
        mid = (sample_low + sample_high) / 2.0
        half = 180.0 if other == "x" else 90.0
        sample_low = max(sample_low, mid - half)
        sample_high = min(sample_high, mid + half)
        sample = np.linspace(sample_low, sample_high, 50)
        gp = _grid_gpar(element, colour)
        for value in scale.breaks():
            if value is None:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(number) or not (low - 1e-9 <= number <= high + 1e-9):
                continue
            xs = np.full(sample.size, number) if axis == "x" else sample
            ys = sample if axis == "x" else np.full(sample.size, number)
            px, py = params.project_xy(xs, ys)
            for run_x, run_y in _finite_runs(px, py):
                if run_x.size < 2:
                    continue
                grobs.append(
                    polyline_grob(
                        run_x.tolist(),
                        run_y.tolist(),
                        default_units="npc",
                        gp=gp,
                        name=name,
                    )
                )
    return grobs


def _finite_runs(px: np.ndarray, py: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
    """把投影结果按非有限值切成若干段（`NA` 在 grid 里就是一条折线的断点）。"""
    finite = np.isfinite(px) & np.isfinite(py)
    runs: list[tuple[np.ndarray, np.ndarray]] = []
    start: int | None = None
    for index, keep in enumerate(finite.tolist()):
        if keep:
            if start is None:
                start = index
            continue
        if start is not None:
            runs.append((px[start:index], py[start:index]))
            start = None
    if start is not None:
        runs.append((px[start:], py[start:]))
    return runs


def _sf_grid_grobs(params: PanelParams, theme: ResolvedTheme) -> list[Any]:
    """`CoordSf$render_bg()`：面板网格 = graticule 的经纬线。

    样式取 `panel.grid.major`（不是 `.x` / `.y`：上游给整张网格一份 gpar）；
    主题元素 blank / 颜色 NA 时一条都不画。
    """
    if params.sf is None or not params.sf.graticule:
        return []
    element = theme.get("panel.grid.major")
    if not isinstance(element, ElementLine):
        return []
    colour = paint(element.colour)
    if colour is None:
        return []
    gp = gpar(
        col=colour,
        lwd=_mm_to_pt(element.linewidth),
        lty=element.linetype if element.linetype is not None else 1,
        lineend=element.lineend or "butt",
        linejoin=element.linejoin or "round",
    )
    grobs: list[Any] = []
    for line in params.sf.graticule:
        xs = np.array([point[0] for point in line.coords], dtype=np.float64)
        ys = np.array([point[1] for point in line.coords], dtype=np.float64)
        px = params.npc("x", xs)
        py = params.npc("y", ys)
        if not (np.isfinite(px).any() and np.isfinite(py).any()):
            continue
        grobs.append(
            polyline_grob(
                unit(px.tolist(), "native"),
                unit(py.tolist(), "native"),
                id=[1] * len(px),
                default_units="native",
                gp=gp,
                name="graticule",
            )
        )
    return grobs


def _polar_grid_grobs(
    build: PlotBuild,
    panel: int,
    params: PanelParams,
    theme: ResolvedTheme,
    *,
    kind: str,
) -> list[Any]:
    """极坐标的网格：theta 辐条（中心 → 0.45）+ r 同心圆（100 点折线）。

    几何逐条照 `CoordPolar$render_bg()`：辐条从 `(0.5, 0.5)` 到
    `0.45·sin/cos + 0.5`；圆在 `r_rescale(r.major) + 0.45` 处（外圈额外的 0.45
    也画）。径向坐标走 `guide_grid()` 的极坐标形态：辐条从内半径起、圆只按 r
    断点（major / minor 各取自己那套）。颜色 / 线型 / 线宽取
    `panel.grid.<kind>.<theta|r>`。
    """
    polar = params.polar
    assert polar is not None  # 调用点已判过
    theta_scale = _panel_scale(build, panel, polar.theta_axis)
    r_scale = _panel_scale(build, panel, polar.r_axis)
    grobs: list[Any] = []

    theta_element = theme.get(f"panel.grid.{kind}.{polar.theta_axis}")
    colour = paint(getattr(theta_element, "colour", None))
    if isinstance(theta_element, ElementLine) and colour is not None and theta_scale is not None:
        values = _polar_grid_values(theta_scale, polar, "theta", kind)
        if polar.radial and kind == "minor":
            # `guide_grid(square = FALSE)` 的两步：`x_minor <- setdiff(minor, major)`
            # ——次断点序列里本来就含主断点（`regular_minor_breaks()`），极坐标
            # `render_bg()` 不筛但 radial 走 `guide_grid()` 要筛（SIL-843：不筛会
            # 多画 17 根主辐条，SVG 里 35 对 18）。
            major_codes = {
                code
                for code in (
                    _value_code(theta_scale, value)
                    for value in _polar_grid_values(theta_scale, polar, "theta", "major")
                )
                if code is not None
            }
            values = tuple(
                value
                for value in values
                if (code := _value_code(theta_scale, value)) is not None and code not in major_codes
            )
        angles: list[float] = []
        for value in values:
            if value is None:
                continue
            number = _value_code(theta_scale, value)
            if number is None:
                continue
            angles.append(float(polar.theta_angle(np.array([number]))[0]))
        if angles:
            outer = 0.4 if polar.radial else 0.45
            inner = polar.inner_radius[0] if polar.radial else 0.0
            x0, y0 = polar.point(np.array(angles), np.full(len(angles), inner))
            x1, y1 = polar.point(np.array(angles), np.full(len(angles), outer))
            xs = np.empty(len(angles) * 2)
            ys = np.empty(len(angles) * 2)
            xs[0::2], xs[1::2] = x0, x1
            ys[0::2], ys[1::2] = y0, y1
            grobs.append(
                segments_grob(
                    xs[0::2].tolist(),
                    ys[0::2].tolist(),
                    xs[1::2].tolist(),
                    ys[1::2].tolist(),
                    default_units="npc",
                    gp=_grid_gpar(theta_element, colour),
                    name=f"panel.grid.{kind}.{polar.theta_axis}",
                )
            )

    r_element = theme.get(f"panel.grid.{kind}.{polar.r_axis}")
    colour = paint(getattr(r_element, "colour", None))
    # `CoordPolar$render_bg()` 只画 `panel.grid.major.<r>` 的同心圆（theta 有 minor
    # 辐条、r 没有 minor 圆）；`coord_radial()` 走 `guide_grid(square = FALSE)`，
    # 四个网格都画，r 的次圆是主断点的中点（SIL-843：上游 6 主 + 5 次）。
    if (
        (kind == "major" or polar.radial)
        and isinstance(r_element, ElementLine)
        and colour is not None
        and r_scale is not None
    ):
        values = _polar_grid_values(r_scale, polar, "r", kind)
        if polar.radial and kind == "minor":
            major_codes = {
                code
                for code in (
                    _value_code(r_scale, value)
                    for value in _polar_grid_values(r_scale, polar, "r", "major")
                )
                if code is not None
            }
            values = tuple(
                value
                for value in values
                if (code := _value_code(r_scale, value)) is not None and code not in major_codes
            )
        radii: list[float] = []
        for value in values:
            if value is None:
                continue
            number = _value_code(r_scale, value)
            if number is None:
                continue
            radii.append(float(polar.radius(np.array([number]))[0]))
        if not polar.radial:
            radii.append(0.45)
        angles = np.linspace(0.0, 2.0 * math.pi, 100)
        for radius in radii:
            xs, ys = polar.point(angles, np.full(angles.size, radius))
            grobs.append(
                polyline_grob(
                    xs.tolist(),
                    ys.tolist(),
                    default_units="npc",
                    gp=_grid_gpar(r_element, colour),
                    name=f"panel.grid.{kind}.{polar.r_axis}",
                )
            )
    return grobs


def _polar_grid_values(scale: Any, polar: Any, axis: str, kind: str) -> tuple[Any, ...]:
    """极坐标网格线的取值（`theta` / `r` × major / minor）。

    主网格 = 面板范围内的断点（`polar_axis_breaks()`，不做 5% 展开）；次网格照
    `CoordPolar$render_bg()` 直接用 `theta.minor`（`polar_minor_breaks()` 的
    原序列，含与主断点重合的那些）。
    """
    if kind == "minor":
        return polar_minor_breaks(scale, polar, axis)
    return polar_axis_breaks(scale, polar, axis)[0]


def _grid_gpar(element: Any, colour: str) -> Any:
    return gpar(
        col=colour,
        lwd=_mm_to_pt(element.linewidth),
        lty=element.linetype if element.linetype is not None else 1,
        lineend="butt",
        linejoin="round",
    )


def _value_code(scale: Any, value: Any) -> float | None:
    """断点值 → 数值（离散按水平序号 1..n）；不认识 / 非有限给 None。"""
    discrete = bool(getattr(scale, "discrete", False))
    if discrete:
        try:
            return float(tuple(scale.levels).index(str(value)) + 1)
        except ValueError:
            return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _panel_rows(data: ColumnTable, panel: int) -> ColumnTable | None:
    if "PANEL" not in data:
        return data if panel == 1 else None
    labels = [str(value) for value in data.column("PANEL").values.tolist()]
    if all(label == str(panel) for label in labels):
        return data
    from ggcore.geom.base import row_slice

    return row_slice(data, np.array([label == str(panel) for label in labels], dtype=bool))


def _geom_of(layer: LayerBuild) -> Any:
    """拿图层自己的 `Geom`（手工构造的 `LayerBuild` 退回注册表契约）。"""
    geom = getattr(layer, "geom_object", None)
    if geom is not None:
        return geom
    from ggcore.layer import Geom
    from ggcore.registry import GEOM_SPECS

    spec = GEOM_SPECS.get(layer.geom)
    if spec is None:
        raise KeyError(f"layer[{layer.index}] 的 geom {layer.geom!r} 不在注册表里")
    return Geom(
        name=layer.geom,
        required_aes=spec.required_aes,
        default_aes=spec.default_aes,
        non_missing_aes=spec.non_missing_aes,
        optional_aes=spec.optional_aes,
    )


# ---------------------------------------------------------------------------
# 标题
# ---------------------------------------------------------------------------


def _text_row_grobs(theme: ResolvedTheme, layout: PlotLayout, which: str) -> list[Any]:
    """`plot.title` / `plot.subtitle` / `plot.caption` 三行文字（左对齐或右对齐由元素给）。"""
    box = getattr(layout, which)
    text = getattr(layout, f"{which}_text")
    element = theme.get(f"plot.{which}")
    if box is None or text is None or not isinstance(element, ElementText):
        return []
    mt, _mr, _mb, _ml = margin_sides_cm(element.margin)
    hjust = float(element.hjust if element.hjust is not None else 0.0)
    x = box.x_cm if hjust <= 0.5 else box.right
    return [
        text_grob(
            text,
            x,
            box.top - mt,
            hjust=hjust,
            vjust=1.0,
            default_units="cm",
            gp=_text_gpar(element),
            name=which,
        )
    ]


def _tag_grobs(layout: PlotLayout) -> list[Any]:
    """`labs(tag=)` 的标签文字（R `table_add_tag()` 的 grob）。"""
    element = layout.tag_element
    if layout.tag is None or not layout.tag_text or not isinstance(element, ElementText):
        return []
    hjust = float(element.hjust) if element.hjust is not None else 0.5
    vjust = float(element.vjust) if element.vjust is not None else 0.5
    return [
        text_grob(
            layout.tag_text,
            layout.tag.x_cm,
            layout.tag.y_cm,
            hjust=hjust,
            vjust=vjust,
            default_units="cm",
            gp=_text_gpar(element),
            name="tag",
        )
    ]


def _text_gpar(element: ElementText) -> gpar:
    return gpar(
        col=paint(element.colour) or "black",
        fontsize=float(element.size or 11.0),
        fontfamily=element.family or "",
        font=_font_int(element.face),
        lineheight=float(element.lineheight or 1.2),
    )


# ---------------------------------------------------------------------------
# 轴
# ---------------------------------------------------------------------------


def secondary_axis_guide(build: PlotBuild, aesthetic: str, scale: Any) -> Any:
    """次轴（top / right）的轴 guide。

    与 R 的优先级一致：`guides(<aes>.sec = guide_axis(...))` 最高，其次是
    `dup_axis(guide = guide_axis(...))` / `sec_axis(guide = ...)` 上的那份；
    都没有时返回 `None`（`axis_guide_ticks()` 按缺省 `guide_axis()` 处理）。
    """
    from ggcore.axis_guide import axis_guide_from_component

    guides = getattr(build, "guides", None) or {}
    key = f"{aesthetic}.sec"
    for name, component in guides.items():
        owner = getattr(component, "aesthetic", None)
        if owner == key or (owner is None and name == key):
            return axis_guide_from_component(component)
    secondary = getattr(scale, "secondary_axis", None) if scale is not None else None
    guide = getattr(secondary, "guide", None) if secondary is not None else None
    if guide is not None:
        return axis_guide_from_component(guide)
    return None


def has_secondary_axis(build: PlotBuild, aesthetic: str, scale: Any) -> bool:
    """top / right 是否画一条次轴。

    R 4.0.3 有两条来路：`sec_axis()` / `dup_axis()` 挂在标度上，或者只在
    `guides(<aes>.sec = ...)` 里给一份轴 guide —— 后者会画一条**恒等的**次轴
    （没有标题），`axis-guides-with-capped-ends` / `stacked-axes` 走的就是这条路。
    """
    if scale is None:
        return False
    if getattr(scale, "secondary_axis", None) is not None:
        return True
    guides = getattr(build, "guides", None) or {}
    key = f"{aesthetic}.sec"
    return any(
        getattr(component, "aesthetic", None) == key
        or (getattr(component, "aesthetic", None) is None and name == key)
        for name, component in guides.items()
    )


def _secondary_ticks(build: PlotBuild, scale: Any, params: Any, side: str, aesthetic: str):
    """次轴刻度：有 `sec_axis()` 走变换，只有 guide 时沿用主轴断点（恒等）。"""
    secondary = getattr(scale, "secondary_axis", None) is not None
    return axis_ticks(scale, params, side, secondary=secondary)


def _draw_axes(build: PlotBuild) -> tuple[bool, bool]:
    """`facet_*(axes=)` 的 `(x, y)`（R 的 `draw_axes`）；无分面时全 False。"""
    facet = getattr(build, "facet", None)
    if facet is None or getattr(facet, "kind", "null") == "null":
        return (False, False)
    return tuple(getattr(facet, "draw_axes", (False, False)))  # type: ignore[return-value]


def _axis_visible(build: PlotBuild, panel: int, side: str) -> tuple[bool, bool]:
    """`(画这条轴, 画它的标签)`。

    口径照 R 4.0.3 的 `attach_axes()` + `censor_labels()`：

    - `axes = "margins"`：只有外边缘面板画轴（每列最底 / 最顶的 x 轴，每行最左 /
      最右的 y 轴）；
    - `axes = "all_x" / "all"`：所有面板都画轴；`axis.labels = "margins"` 时只有
      边缘面板带标签（内面板只留刻度），否则内面板也带标签。
    """
    facet = getattr(build, "facet", None)
    layout = getattr(build, "layout", None)
    if facet is None or layout is None or getattr(facet, "kind", "null") == "null":
        return True, True
    draw = _draw_axes(build)
    labels = tuple(getattr(facet, "draw_axis_labels", (True, True)))
    row, col = int(layout.row_of(panel)), int(layout.col_of(panel))
    if side in ("bottom", "top"):
        rows = [int(layout.row_of(item)) for item in layout.panels_in_col(col)] or [row]
        margin = row == (max(rows) if side == "bottom" else min(rows))
        if not draw[0]:
            return margin, margin
        return True, True if labels[0] else margin
    cols = [int(layout.col_of(item)) for item in layout.panels_in_row(row)] or [col]
    margin = col == (min(cols) if side == "left" else max(cols))
    if not draw[1]:
        return margin, margin
    return True, True if labels[1] else margin


def _radial_axis_theme(theme: Any, params: Any) -> Any:
    """`coord_radial()` 的 r 轴读 `axis.*.r` 元素（上游 `theme_suffix = "r"`）。

    上游 `CoordRadial$train_panel_guides()` 对 `r` / `r.sec` 一律设
    `theme_suffix <- "r"`（`guide-axis-theta with angle adapting` 是全圆、
    `r.axis.inside = FALSE`，仍读 `axis.text.r`：标签 `hjust = 0.5` 居中、
    两侧各 2.2pt margin）。
    """
    from ggcore.axis_guide import AxisSuffixTheme

    polar = getattr(params, "polar", None)
    if polar is None or not polar.radial:
        return theme
    return AxisSuffixTheme(theme, "r")


def _axis_guide_theme(theme: Any, params: Any, guide: Any) -> Any:
    """一条轴 guide 的主题：`plot_theme %+% guide$theme`，再套 radial 的 `.r` 后缀。

    顺序照上游 `GuideAxis$setup_elements()`：先拼 `theme_suffix`，再由
    `Guide$setup_elements()` 把 guide 自己的 `theme=` 合进用户主题（`add_theme()`
    的 override 优先）。所以逐 guide 的 `element_line(colour = "orchid")` 能盖住
    `axis.line.r`（SIL-844 的 inner-radius 快照）。
    """
    from ggcore.guide import guide_theme

    if guide is not None and getattr(guide, "theme", None) is not None:
        theme = guide_theme(theme, guide)
    return _radial_axis_theme(theme, params)


def _scale_side(scale: Any, default: str) -> str:
    """`scale_*_continuous(position = ...)`：主轴画在哪一边（缺省 bottom / left）。

    R 4.0.3 把主轴侧记录在 scale 的 `position` 上（`axis_order()` 由它推），
    `Coord$render_axis_*()` 只画该侧；另一侧留给次轴或留白。
    """
    if scale is None:
        return default
    getter = getattr(scale, "_param", None)
    value = getter("position") if getter is not None else None
    if value in ("top", "bottom", "left", "right"):
        return str(value)
    return default


def _axis_grobs(
    build: PlotBuild,
    theme: ResolvedTheme,
    layout: PlotLayout,
    metrics: Any,
    *,
    table: Any = None,
) -> list[Any]:
    grobs: list[Any] = []
    guide_x = guide_for(build, "x")
    guide_y = guide_for(build, "y")
    for panel, params in _panels(build):
        box = layout.panel_boxes.get(panel)
        if box is None:  # pragma: no cover
            continue
        radial = params.polar is not None and bool(getattr(params.polar, "radial", False))
        if radial:
            # 与 `plot_layout()` 同一口径：radial 的主 r 轴读 `guides(r = ...)`。
            guide_y = guide_for(build, "r")
        x_title = _guide_title(guide_x, _axis_title_text(build, "x"))
        y_title = _guide_title(guide_y, _axis_title_text(build, "y"))
        guide_rsec = guide_for(build, "r.sec") if radial else None
        if guide_rsec is not None:
            rsec_title = _guide_title(guide_rsec, None)
        else:
            rsec_title = None
        # `switch = "both"` / `strip.position`：换到面板下方的 strip 与轴之间、
        # 换到左侧的 strip 与轴之间都还隔着 strip 行 / 列（R 把轴 seam 在 strip
        # 之外）。轴带贴着**整张分面表**的外沿，不贴面板本身。
        #
        # 两个方向各自让位：R 的 axis-b 只跨 panel 列、axis-l 只跨 panel 行，
        # 拿同一个格子同时往左 / 往下撑会把 x 刻度整体挪一个 strip 宽（SIL-871）。
        cell_x, cell_w = box.x_cm, box.width_cm
        cell_y, cell_h = box.y_cm, box.height_cm
        inside_sides = getattr(table, "inside_strip_sides", ())
        cell = CellBox(1, 1, 1, 1, cell_x, cell_y, cell_w, cell_h)
        x_cell = cell
        if "bottom" in inside_sides:
            x_cell = CellBox(
                1, 1, 1, 1, cell_x, layout.panel_area.y_cm, cell_w, box.top - layout.panel_area.y_cm
            )
        y_cell = cell
        if "left" in inside_sides:
            y_cell = CellBox(
                1,
                1,
                1,
                1,
                layout.panel_area.x_cm,
                cell_y,
                box.right - layout.panel_area.x_cm,
                cell_h,
            )
        # `axes = "all"` 的顶部 / 右侧轴标签在 strip 之外（R 把 strip 行先
        # seam 进面板表，轴再 seam 在它外侧）。
        top_cell = cell
        if "top" in inside_sides and getattr(table, "strip_height_cm", 0.0):
            top_cell = CellBox(
                1, 1, 1, 1, cell_x, cell_y, cell_w, cell_h + float(table.strip_height_cm)
            )
        right_cell = cell
        if "right" in inside_sides and getattr(table, "strip_width_cm", 0.0):
            right_cell = CellBox(
                1, 1, 1, 1, cell_x, cell_y, cell_w + float(table.strip_width_cm), cell_h
            )
        scale_bottom = _panel_scale(build, panel, params.scale_key("bottom"))
        scale_left = _panel_scale(build, panel, params.scale_key("left"))
        scale_top = _panel_scale(build, panel, params.scale_key("top"))
        scale_right = _panel_scale(build, panel, params.scale_key("right"))
        x_side = _scale_side(scale_bottom, "bottom")
        y_side = _scale_side(scale_left, "left")
        ticks_x = axis_ticks(scale_bottom, params, x_side)
        ticks_y = axis_ticks(scale_left, params, y_side)
        draw_bottom, label_bottom = _axis_visible(build, panel, x_side)
        draw_left, label_left = _axis_visible(build, panel, y_side)
        gx = None
        gy = None
        if draw_bottom:
            gx = axis_guide_ticks(scale_bottom, params, x_side, guide_x, theme, base=ticks_x)
            grobs.extend(
                axis_guide_grobs(
                    theme,
                    gx,
                    top_cell if x_side == "top" else x_cell,
                    guide_x,
                    metrics=metrics,
                    name=f"axis-x-{panel}",
                    draw_labels=label_bottom,
                    degree_labels=params.sf is not None,
                )
            )
        inside_r_axes = radial and bool(params.polar.r_axis_inside)
        if draw_left and not inside_r_axes:
            axis_theme = _axis_guide_theme(theme, params, guide_y)
            gy = axis_guide_ticks(scale_left, params, y_side, guide_y, axis_theme, base=ticks_y)
            grobs.extend(
                axis_guide_grobs(
                    axis_theme,
                    gy,
                    right_cell if y_side == "right" else y_cell,
                    guide_y,
                    metrics=metrics,
                    name=f"axis-y-{panel}",
                    draw_labels=label_left,
                    degree_labels=params.sf is not None,
                )
            )
        if inside_r_axes:
            # `r.axis.inside` 为真（或给了 theta 角度）：r / r.sec 两条轴都画在
            # 面板里，绕面板中心转到 `axis_rotation` 的角度（上游
            # `CoordRadial$render_fg()` 的 `rotate_r_axis()`）。
            rotation = params.polar.axis_rotation
            # `guides(r = ...)` 缺省时 R 仍画默认 r 轴（`guide_axis()`）；
            # `guide_for()` 返回 None 只是「没有显式登记」，不是「没有轴」。
            for axis_guide_obj, axis_side, axis_angle, axis_name in (
                (guide_y or AxisGuide(), "left", rotation[0], f"axis-r-{panel}"),
                (guide_rsec or AxisGuide(), "right", rotation[1], f"axis-r-sec-{panel}"),
            ):
                if axis_guide_obj is None or axis_guide_obj.name == "none":
                    continue
                inside_theme = _axis_guide_theme(theme, params, axis_guide_obj)
                inside_ticks = axis_guide_ticks(
                    scale_left,
                    params,
                    axis_side,
                    axis_guide_obj,
                    inside_theme,
                    base=polar_r_ticks(scale_left, params, axis_side),
                )
                grobs.extend(
                    polar_r_axis_inside_grobs(
                        inside_theme,
                        inside_ticks,
                        cell,
                        axis_guide_obj,
                        angle=float(axis_angle),
                        position=axis_side,
                        bbox=params.polar.bbox,
                        name=axis_name,
                        metrics=metrics,
                    )
                )
        # 次轴（top / right）：断点 / 标签 / 位置由 `secondary_ticks()` 推；
        # guide 优先级与主轴一致：`guides(x.sec = ...)` → `dup_axis(guide = ...)`
        # → 默认 `guide_axis()`（R 的 `scale$secondary.axis$guide`）。
        guide_top = secondary_axis_guide(build, "x", scale_top)
        guide_right = secondary_axis_guide(build, "y", scale_right)
        draw_top, label_top = _axis_visible(build, panel, "top")
        draw_right, label_right = _axis_visible(build, panel, "right")
        gx_top = None
        gy_right = None
        if has_secondary_axis(build, "x", scale_top) and draw_top:
            gx_top = axis_guide_ticks(
                scale_top,
                params,
                "top",
                guide_top,
                theme,
                secondary=getattr(scale_top, "secondary_axis", None) is not None,
                base=_secondary_ticks(build, scale_top, params, "top", "x"),
            )
            grobs.extend(
                axis_guide_grobs(
                    theme,
                    gx_top,
                    top_cell,
                    guide_top,
                    metrics=metrics,
                    name=f"axis-x-sec-{panel}",
                    draw_labels=label_top,
                    degree_labels=params.sf is not None,
                )
            )
        if has_secondary_axis(build, "y", scale_right) and draw_right:
            gy_right = axis_guide_ticks(
                scale_right,
                params,
                "right",
                guide_right,
                theme,
                secondary=getattr(scale_right, "secondary_axis", None) is not None,
                base=_secondary_ticks(build, scale_right, params, "right", "y"),
            )
            grobs.extend(
                axis_guide_grobs(
                    theme,
                    gy_right,
                    right_cell,
                    guide_right,
                    metrics=metrics,
                    name=f"axis-y-sec-{panel}",
                    draw_labels=label_right,
                    degree_labels=params.sf is not None,
                )
            )
        # `guides(r.sec = ...)`：径向的次 r 轴画进 axis-r 槽（`right_cell`），
        # 断点与主 r 轴同源（上游 `panel_params$r.sec` 是同一个 r 标度的次视图），
        # 轴线 / 刻度 / 文字都读 `axis.*.r`，再叠 guide 自己的 `theme=`。
        gy_rsec = None
        if radial and guide_rsec is not None and not params.polar.r_axis_inside:
            rsec_theme = _axis_guide_theme(theme, params, guide_rsec)
            gy_rsec = axis_guide_ticks(
                scale_left, params, "right", guide_rsec, rsec_theme, base=ticks_y
            )
            grobs.extend(
                axis_guide_grobs(
                    rsec_theme,
                    gy_rsec,
                    right_cell,
                    guide_rsec,
                    metrics=metrics,
                    name=f"axis-r-sec-{panel}",
                )
            )
            grobs.extend(
                axis_line_grobs(
                    rsec_theme,
                    cell,
                    name=f"axis-line-r-sec-{panel}",
                    ranges={"right": axis_line_range(guide_rsec, gy_rsec)},
                    sides=("right",),
                )
            )
        line_sides = (
            # `coord_radial()`：x / y 两条轴都不画（上游 `render_axis_h/v()` 在这
            # 种面板里给的是一对 zeroGrob，轴线只由 r / theta 的 guide 自带）。
            *((x_side,) if draw_bottom and not radial else ()),
            *((y_side,) if draw_left and not inside_r_axes else ()),
            *(("top",) if gx_top is not None else ()),
            *(("right",) if gy_right is not None else ()),
        )
        if line_sides:
            ranges = {
                x_side: axis_line_range(guide_x, gx) if gx is not None else None,
                y_side: axis_line_range(guide_y, gy) if gy is not None else None,
                "top": axis_line_range(guide_top, gx_top) if gx_top is not None else None,
                "right": axis_line_range(guide_right, gy_right) if gy_right is not None else None,
            }
            # 水平轴（bottom / top）只受上下 strip 影响，垂直轴（left / right）只受
            # 左右 strip 影响：轴线跟着各自的格子走，不能跨维借位（SIL-871）。
            horizontal_sides = tuple(side for side in line_sides if side in ("bottom", "top"))
            vertical_sides = tuple(side for side in line_sides if side in ("left", "right"))
            if horizontal_sides:
                grobs.extend(
                    axis_line_grobs(
                        _axis_guide_theme(theme, params, guide_y),
                        top_cell if "top" in horizontal_sides else x_cell,
                        name=f"axis-line-{panel}",
                        ranges=ranges,
                        sides=horizontal_sides,
                    )
                )
            if vertical_sides:
                grobs.extend(
                    axis_line_grobs(
                        _axis_guide_theme(theme, params, guide_y),
                        right_cell if "right" in vertical_sides else y_cell,
                        name=f"axis-line-{panel}",
                        ranges=ranges,
                        sides=vertical_sides,
                    )
                )
        for annotation in getattr(build, "annotations", ()) or ():
            from ggcore.annotations import logticks_grobs

            grobs.extend(
                logticks_grobs(
                    annotation,
                    params,
                    cell,
                    name=f"annotation-logticks-{panel}",
                )
            )
        if params.polar is not None:
            from ggcore.axis_guide import guide_for as _guide_for

            theta_scale = _panel_scale(build, panel, params.polar.theta_axis)
            grobs.extend(
                polar_axis_grobs(
                    theta_scale,
                    params,
                    theme,
                    cell,
                    _guide_for(build, "theta"),
                    metrics=metrics,
                    name=f"axis-theta-{panel}",
                )
            )
            # `CoordRadial$render_fg()` 还会画 `theta.sec`（key 落在内半径、角度 +π）。
            # 没有 `guides(theta.sec = ...)` 时上游画的是空 guide，这里同样跳过。
            theta_sec = _guide_for(build, "theta.sec")
            if theta_sec is not None:
                grobs.extend(
                    polar_axis_grobs(
                        theta_scale,
                        params,
                        theme,
                        cell,
                        theta_sec,
                        metrics=metrics,
                        name=f"axis-theta-sec-{panel}",
                        secondary=True,
                    )
                )
    area = axis_title_area(layout)
    inside_sides = getattr(table, "inside_strip_sides", ())

    def _title_cell(side: str) -> CellBox:
        """轴标题的容器：strip 落在面板与轴**之间**时，标题要再让出一格。

        R 的 `attach_strips()` 把换边的 strip seam 在面板与轴带之间，所以
        `xlab` / `ylab` 在 strip 之外（`facet_grid(switch=)` 与
        `facet_wrap(strip.position=)` 同一口径）。水平标题只受上下 strip 影响，
        垂直标题只受左右 strip 影响——另一维保持 panel 并集，标题中心才不会
        被 strip 拽偏（SIL-817）。
        """
        x, y, w, h = area.x_cm, area.y_cm, area.width_cm, area.height_cm
        strip_h = float(getattr(table, "strip_height_cm", 0.0))
        strip_w = float(getattr(table, "strip_width_cm", 0.0))
        if side in ("top", "bottom") and side in inside_sides:
            if side == "bottom":
                y -= strip_h
            h += strip_h
        elif side in ("left", "right") and side in inside_sides:
            if side == "left":
                x -= strip_w
            w += strip_w
        return CellBox(1, 1, 1, 1, x, y, w, h)

    panels_for_side = list(_panels(build))
    x_title_side = "bottom"
    y_title_side = "left"
    if panels_for_side:
        _, first_params = panels_for_side[0]
        x_title_side = _scale_side(
            _panel_scale(build, panels_for_side[0][0], first_params.scale_key("bottom")), "bottom"
        )
        y_title_side = _scale_side(
            _panel_scale(build, panels_for_side[0][0], first_params.scale_key("left")), "left"
        )
    if x_title:
        fake = _title_cell(x_title_side)
        grob = axis_title_grob(
            theme,
            x_title_side,
            x_title,
            fake,
            labels_extent_cm=layout.x_axis_top_cm if x_title_side == "top" else layout.x_axis_cm,
            metrics=metrics,
            name="axis-title-x",
        )
        if grob is not None:
            grobs.append(grob)
    if y_title:
        fake = _title_cell(y_title_side)
        grob = axis_title_grob(
            theme,
            y_title_side,
            y_title,
            fake,
            labels_extent_cm=layout.y_axis_right_cm
            if y_title_side == "right"
            else layout.y_axis_cm,
            metrics=metrics,
            name="axis-title-y",
        )
        if grob is not None:
            grobs.append(grob)
    if rsec_title:
        # `guides(r.sec = guide_axis(title = "right"))`：右轴标题（`axis.title.y.right`）。
        fake = _title_cell("right")
        grob = axis_title_grob(
            theme,
            "right",
            rsec_title,
            fake,
            labels_extent_cm=layout.y_axis_right_cm,
            metrics=metrics,
            name="axis-title-r-sec",
        )
        if grob is not None:
            grobs.append(grob)
    if layout.secondary_x or layout.secondary_y:
        for panel, params in _panels(build):
            box = layout.panel_boxes.get(panel)
            if box is None:
                continue
            fake = CellBox(1, 1, 1, 1, box.x_cm, box.y_cm, box.width_cm, box.height_cm)
            if layout.secondary_x:
                scale = _panel_scale(build, panel, params.scale_key("top"))
                guide = secondary_axis_guide(build, "x", scale)
                title = _guide_title(guide, _secondary_title(build, params.scale_key("top"), scale))
                grob = axis_title_grob(
                    theme,
                    "top",
                    title,
                    fake,
                    labels_extent_cm=layout.x_axis_top_cm,
                    metrics=metrics,
                    name="axis-title-x-sec",
                )
                if grob is not None:
                    grobs.append(grob)
            if layout.secondary_y:
                scale = _panel_scale(build, panel, params.scale_key("right"))
                guide = secondary_axis_guide(build, "y", scale)
                title = _guide_title(
                    guide, _secondary_title(build, params.scale_key("right"), scale)
                )
                grob = axis_title_grob(
                    theme,
                    "right",
                    title,
                    fake,
                    labels_extent_cm=layout.y_axis_right_cm,
                    metrics=metrics,
                    name="axis-title-y-sec",
                )
                if grob is not None:
                    grobs.append(grob)
    return grobs


# ---------------------------------------------------------------------------
# 图例
# ---------------------------------------------------------------------------


def _legend_grobs(
    build: PlotBuild,
    theme: ResolvedTheme,
    layout: PlotLayout,
    metrics: Any,
) -> list[Any]:
    grobs: list[Any] = []
    box_el = theme.get("legend.box.background")
    if layout.legend_boxes and isinstance(box_el, ElementRect) and paint(box_el.fill) is not None:
        # guide-box 的矩形含 `legend.box.margin`（R 的 `gtable_add_padding()` 之后
        # 才加 background，背景整块盖住 margin）。用摆放好的盒矩形，不用图例矩形
        # 的并集——后者会少掉四周的 box margin（stretched-vertical-legends）。
        union = _union(layout.legend_box_origins or layout.legend_boxes)
        grobs.append(
            rect_grob(
                union.x_cm,
                union.y_cm,
                union.width_cm,
                union.height_cm,
                just=("left", "bottom"),
                default_units="cm",
                gp=gpar(fill=paint(box_el.fill), col=paint(box_el.colour) or NA),
                name="legend.box.background",
            )
        )
    for index, (guide, legend, box) in enumerate(
        zip(layout.guides, layout.legend_layouts, layout.legend_boxes, strict=True)
    ):
        # 走 `Guide.gengrob()`：自定义 guide 覆盖它就能接管整张图例的绘制。
        # `theme=` 是逐 guide 覆盖，自定义 guide 的 `gengrob` 也要看得到它。
        children = guide.guide.gengrob(
            guide,
            build,
            guide_theme(theme, guide.guide),
            legend,
            metrics=metrics,
            name=f"guide-{index}",
        )
        if not children:
            continue
        grobs.append(
            g_tree(
                *children,
                name=f"guide-{index}",
                vp=viewport(
                    f"guide-{index}",
                    x=unit(box.x_cm, "cm"),
                    y=unit(box.y_cm, "cm"),
                    width=unit(box.width_cm, "cm"),
                    height=unit(box.height_cm, "cm"),
                    just=("left", "bottom"),
                    clip="off",
                    gp=gpar(fontsize=12.0, fontfamily=""),
                ),
            )
        )
    return grobs


def _union(boxes: tuple[Box, ...]) -> Box:
    x = min(box.x_cm for box in boxes)
    y = min(box.y_cm for box in boxes)
    right = max(box.right for box in boxes)
    top = max(box.top for box in boxes)
    return Box(x, y, right - x, top - y)


# ---------------------------------------------------------------------------
# theme 元素 → grob
# ---------------------------------------------------------------------------


def _rect_for(
    theme: ResolvedTheme,
    name: str,
    width_cm: float,
    height_cm: float,
    *,
    centre: bool,
) -> Any | None:
    element = theme.get(name)
    if not isinstance(element, ElementRect):
        return None
    fill = _paint(element.fill)
    if fill is None:
        return None
    del centre
    return rect_grob(
        x=unit(0.5, "npc"),
        y=unit(0.5, "npc"),
        width=unit(1.0, "npc"),
        height=unit(1.0, "npc"),
        just="centre",
        gp=gpar(fill=fill, col=NA),
        name=name,
    )


def _radial_panel_background(polar: Any, element: ElementRect, *, name: str) -> Any:
    """`coord_radial()` 的 `panel.background`：`guide_grid(square = FALSE)` 的圆环。

    上游把 `panel.background` 的矩形换成 `c(±Inf)` 的 polygon 再 `coord_munch`，
    满圆下得到的是「外圆（`inner_radius[1]`）− 内孔（`inner_radius[0]`）」的
    圆环（SIL-843 用上游 SVG 的 317 点 `#EBEBEB` 双环钉住）。用 `path_grob`
    的 `evenodd` 表示两段子路径，与 grid 的 nonzero 填充结果一致。
    """
    from ggcore.grobs import path_grob

    fill = _paint(getattr(element, "fill", None))
    colour = _paint(getattr(element, "colour", None))
    outer = float(polar.inner_radius[1])
    inner = float(polar.inner_radius[0])
    steps = 179  # R 的 `coord_munch()` 在满圆上的采样点数（外圆 179 段）
    arc = tuple(polar.arc)
    full = abs(arc[1] - arc[0]) >= 1.999 * math.pi
    angles = (
        np.linspace(arc[0], arc[1], steps) if not full else np.linspace(0.0, 2.0 * math.pi, steps)
    )
    xo, yo = polar.point(angles, np.full(angles.shape, outer))
    xs = [float(value) for value in np.asarray(xo)]
    ys = [float(value) for value in np.asarray(yo)]
    ids = [1] * len(xs)
    if inner > 0:
        xi, yi = polar.point(angles[::-1], np.full(angles.shape, inner))
        xs.extend(float(value) for value in np.asarray(xi))
        ys.extend(float(value) for value in np.asarray(yi))
        ids.extend([1 if not full else 2] * (len(xs) - len(ids)))
    return path_grob(
        xs,
        ys,
        id=ids,
        rule="evenodd",
        default_units="npc",
        gp=gpar(
            fill=fill if fill is not None else NA,
            col=colour if colour is not None else NA,
            lwd=_mm_to_pt(getattr(element, "linewidth", 0.0)),
            lty=getattr(element, "linetype", None) or 1,
        ),
        name=name,
    )


def _rect_from_element(element: ElementRect, *, border_only: bool, name: str) -> Any | None:
    fill = None if border_only else _paint(element.fill)
    colour = _paint(element.colour)
    if fill is None and colour is None:
        return None
    return rect_grob(
        x=0.5,
        y=0.5,
        width=1.0,
        height=1.0,
        just="centre",
        gp=gpar(
            fill=fill if fill is not None else NA,
            col=colour if colour is not None else NA,
            lwd=_mm_to_pt(element.linewidth),
            lty=element.linetype if element.linetype is not None else 1,
        ),
        name=name,
    )


def _paint(value: Any) -> str | None:
    return paint(value)


def _mm_to_pt(value: Any) -> float:
    """主题的 `linewidth`（mm）→ gpar 的 `lwd`（pt）。

    用 R 的 `.pt = 72.27/25.4`（`geom/base.POINT_PER_MM` 同一个常数），不是
    72/25.4：svglite 写进 SVG 的 `stroke-width` 是 `linewidth * .pt`，差 0.4%
    就够让 1 px 边框的覆盖率翻一档（SIL-820 的 `align-facet-labels`）。
    """
    if value is None:
        return 0.0
    try:
        return float(value) * POINT_PER_MM
    except (TypeError, ValueError):
        return 0.0


def _clip_state(value: str) -> str:
    return value if value in ("on", "off", "inherit") else "on"


# ---------------------------------------------------------------------------
# strip
# ---------------------------------------------------------------------------


def _strip_grobs(
    table: FacetTable,
    theme: ResolvedTheme,
    layout: PlotLayout,
    metrics: Any,
) -> list[Any]:
    if not table.strips:
        return []
    area = layout.panel_area
    sizes = table.gtable.resolve(area.width_cm, area.height_cm, ctx=UnitContext(metrics=metrics))
    grobs: list[Any] = []
    for strip in table.strips:
        grobs.extend(_one_strip(table, strip, theme, layout, area, sizes, metrics))
    return grobs


def _strip_box(
    table: FacetTable,
    strip: FacetStrip,
    layout: PlotLayout,
    area: Box,
    sizes: Any,
) -> Box | None:
    """strip 单元格的页面矩形：gtable 单元格，或 `outside` 时的轴带之外。"""
    if strip.outside:
        if strip.side == "top":
            return layout.top_strip_band
        band = layout.right_strip_band
        if band is None:
            return None
        # 右侧 strip 的竖向范围跟着该面板行（R 的 strip-r 与 panel 同高）。
        boxes = [
            box
            for panel, box in layout.panel_boxes.items()
            if _row_of(table.layout, panel) == strip.row
        ]
        if not boxes:
            return None
        y = min(box.y_cm for box in boxes)
        top = max(box.top for box in boxes)
        return Box(band.x_cm, y, band.width_cm, top - y)
    placement = next((row for row in table.gtable.layout if row.name == strip.name), None)
    if placement is None:  # pragma: no cover - 非 outside 的 strip 一定有 placement
        return None
    cell = table.gtable.region_box(
        placement.t,
        placement.l,
        placement.b,
        placement.r,
        width_cm=area.width_cm,
        height_cm=area.height_cm,
        sizes=sizes,
    )
    x = area.x_cm + cell.x_cm
    y = area.y_cm + cell.y_cm
    return Box(x, y, cell.width_cm, cell.height_cm)


def _row_of(layout: Any, panel: int) -> int:
    return int(layout.row_of(panel))


def _one_strip(
    table: FacetTable,
    strip: FacetStrip,
    theme: ResolvedTheme,
    layout: PlotLayout,
    area: Box,
    sizes: Any,
    metrics: Any = None,
) -> list[Any]:
    box = _strip_box(table, strip, layout, area, sizes)
    if box is None:
        return []
    background_name = (
        "strip.background.y" if strip.side in ("right", "left") else "strip.background.x"
    )
    background = theme.get(background_name)
    element = theme.get(
        {
            "left": "strip.text.y.left",
            "right": "strip.text.y",
            "bottom": "strip.text.x.bottom",
        }.get(strip.side, "strip.text.x")
    )
    angle = float(element.angle or 0.0) if isinstance(element, ElementText) else 0.0
    parts = strip.parts or (StripPart("", strip.text, strip.fill),)
    grobs: list[Any] = []
    count = len(parts)
    for index, part in enumerate(parts):
        if strip.side in ("top", "bottom"):
            # 顶部：parts 自上而下排列，**最后一个变量最靠近面板**
            # （R `weave_tables_row()`：`x + y ~ ...` 时 y 贴着面板、x 在最上）。
            # `switch = "both"` 换到底部同理：面板在上方，第一个变量贴着面板。
            slot_h = box.height_cm / count
            part_box = Box(box.x_cm, box.y_cm + (count - 1 - index) * slot_h, box.width_cm, slot_h)
        else:
            slot_w = box.width_cm / count
            part_box = Box(box.x_cm + index * slot_w, box.y_cm, slot_w, box.height_cm)
        name = strip.name if count == 1 else f"{strip.name}-{part.var}"
        if isinstance(background, ElementRect) and part.fill is not None:
            fill = _paint(part.fill)
            if fill is not None:
                # R 把 strip 的每个单元格当 gtable 视口画，`clip = "on"`：
                # `theme_classic()` 的 `strip.background(linewidth = rel(2))`
                # 有一半线宽落在单元格之外，会被裁掉；不裁就会压到图表区。
                grobs.append(
                    clip_path(
                        rect_grob(
                            x=unit(part_box.x_cm, "cm"),
                            y=unit(part_box.y_cm, "cm"),
                            width=unit(part_box.width_cm, "cm"),
                            height=unit(part_box.height_cm, "cm"),
                            hjust=0.0,
                            vjust=0.0,
                            gp=gpar(
                                fill=fill,
                                col=_paint(background.colour) or NA,
                                lwd=_mm_to_pt(background.linewidth),
                                lty=background.linetype if background.linetype is not None else 1,
                            ),
                            name=name,
                        ),
                        x=part_box.x_cm,
                        y=part_box.y_cm,
                        width=part_box.width_cm,
                        height=part_box.height_cm,
                        default_units="cm",
                        name=f"{name}-clip",
                    )
                )
        if isinstance(element, ElementText) and not callable(getattr(element, "grob", None)):
            if not part.text:
                continue
            hjust = float(element.hjust if element.hjust is not None else 0.5)
            vjust = float(element.vjust if element.vjust is not None else 0.5)
            if plotmath.is_math(part.text):
                # `labeller = label_parsed` 的 strip：plotmath 拆成多段 run（各自
                # 字号 / 基线抬升），每个 run 一个 text 节点（IR 没有「段」字段）。
                grobs.extend(
                    math_text_grobs(
                        part.text,
                        part_box.x_cm + part_box.width_cm / 2.0,
                        part_box.y_cm + part_box.height_cm / 2.0,
                        size=float(getattr(element, "size", 0.0) or 0.0),
                        metrics=metrics,
                        family=element.family or "",
                        hjust=hjust,
                        vjust=vjust,
                        rot=angle,
                        gp=_text_gpar(element),
                        name=f"{name}.text",
                    )
                )
                continue
            grobs.append(
                text_grob(
                    part.text,
                    unit(part_box.x_cm + part_box.width_cm / 2.0, "cm"),
                    unit(part_box.y_cm + part_box.height_cm / 2.0, "cm"),
                    hjust=hjust,
                    vjust=vjust,
                    rot=angle,
                    default_units="cm",
                    gp=_text_gpar(element),
                    name=f"{name}.text",
                )
            )
            continue
        if isinstance(element, ElementBlank):
            continue
        # 非文字 / 自定义元素：走 `element_grob()` 扩展协议（R 的 S7 泛型），
        # 元素自己决定画什么（`custom-strip-elements-can-render` 的 1cm 方块）。
        grobs.append(
            element_grob(
                element,
                label=part.text,
                x=unit(part_box.x_cm + part_box.width_cm / 2.0, "cm"),
                y=unit(part_box.y_cm + part_box.height_cm / 2.0, "cm"),
                default_units="cm",
                name=f"{name}.text",
            )
        )
    return grobs


def _font_int(face: Any) -> int:
    return {"bold": 2, "italic": 3, "oblique": 3, "bold.italic": 4, "bolditalic": 4}.get(
        str(face or "plain").lower(), 1
    )

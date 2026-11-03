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

from ggcore import ir
from ggcore.axis import (
    DERIVE,
    axis_extent,
    axis_grobs,
    axis_ticks,
    axis_title_extent,
    axis_title_grob,
    margin_sides_cm,
    paint,
    text_line_cm,
)
from ggcore.axis_guide import (
    axis_guide_extent,
    axis_guide_grobs,
    axis_guide_ticks,
    axis_line_range,
    guide_for,
    polar_axis_grobs,
)
from ggcore.build import LayerBuild, PlotBuild, build_plot
from ggcore.coord import CoordBase, PanelParams
from ggcore.data import ColumnTable
from ggcore.facet import FacetStrip, FacetTable, StripPart
from ggcore.grobs import (
    NullGrob,
    ZeroGrob,
    clip_path,
    g_tree,
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
    legend_box_layout,
    legend_layout,
)
from ggcore.theme import (
    ElementLine,
    ElementRect,
    ElementText,
    ResolvedTheme,
    Theme,
    resolve_theme,
)
from ggcore.units import BIGPOINTS_PER_INCH as PT_PER_INCH
from ggcore.units import CM_PER_INCH, UnitContext, unit
from ggcore.viewport import NA, Device, ViewportTree, gpar, viewport

__all__ = [
    "DEFAULT_HEIGHT_IN",
    "DEFAULT_WIDTH_IN",
    "Box",
    "PlotLayout",
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

    @property
    def legend_width_cm(self) -> float:
        return max((box.width_cm for box in self.legend_boxes), default=0.0)

    @property
    def legend_height_cm(self) -> float:
        return sum(box.height_cm for box in self.legend_boxes)


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
    for panel, params in _panels(prepared):
        box = layout.panel_boxes.get(panel)
        if box is None:  # pragma: no cover - FacetTable 一定覆盖每个 panel
            continue
        children = _panel_children(prepared, prepared_layers, panel, params, theme, metrics)
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
    grobs.extend(_axis_grobs(prepared, theme, layout, metrics))
    grobs.extend(_legend_grobs(prepared, theme, layout, metrics))
    return scene(grobs, tree).to_ir_scene()


# ---------------------------------------------------------------------------
# 版式：plot.margin / title / legend / axes / panel 区
# ---------------------------------------------------------------------------


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


def _axis_title_text(build: PlotBuild, aesthetic: str) -> str | None:
    labels = getattr(build, "labels", {}) or {}
    if aesthetic in labels:
        value = labels[aesthetic]
        return None if value is None else str(value)
    for mapping in getattr(build, "raw_mappings", ()):
        if aesthetic in mapping:
            return str(mapping[aesthetic])
    return None


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
    top, bottom, right, left = _plot_margin(theme)
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
    group_indices: dict[str, list[int]] = {}
    for index, side in enumerate(guide_sides):
        group_indices.setdefault(str(side), []).append(index)
    box_layouts = {
        side: legend_box_layout([legend_layouts[index] for index in indices], side, theme)
        for side, indices in group_indices.items()
    }

    x_axis = 0.0
    y_axis = 0.0
    x_axis_top = 0.0
    y_axis_right = 0.0
    x_title_top = 0.0
    y_title_right = 0.0
    secondary_x = False
    secondary_y = False
    for panel, params in _panels(build):
        ticks_x = axis_ticks(
            _panel_scale(build, panel, params.scale_key("bottom")), params, "bottom"
        )
        ticks_y = axis_ticks(_panel_scale(build, panel, params.scale_key("left")), params, "left")
        guide_x = guide_for(build, "x")
        guide_y = guide_for(build, "y")
        if params.polar is None:
            guide_ticks_x = axis_guide_ticks(
                _panel_scale(build, panel, params.scale_key("bottom")),
                params,
                "bottom",
                guide_x,
                theme,
                base=ticks_x,
            )
            x_axis = max(
                x_axis,
                axis_guide_extent(theme, guide_ticks_x, guide_x, side="bottom", metrics=metrics),
            )
        guide_ticks_y = axis_guide_ticks(
            _panel_scale(build, panel, params.scale_key("left")),
            params,
            "left",
            guide_y,
            theme,
            base=ticks_y,
        )
        y_axis = max(
            y_axis,
            axis_guide_extent(theme, guide_ticks_y, guide_y, side="left", metrics=metrics),
        )
        top_scale = _panel_scale(build, panel, params.scale_key("top"))
        right_scale = _panel_scale(build, panel, params.scale_key("right"))
        if top_scale is not None and getattr(top_scale, "secondary_axis", None) is not None:
            secondary_x = True
            ticks_top = axis_ticks(top_scale, params, "top", secondary=True)
            x_axis_top = max(x_axis_top, axis_extent(theme, ticks_top, metrics=metrics))
            x_title_top = max(
                x_title_top,
                axis_title_extent(
                    theme,
                    "top",
                    _secondary_title(build, params.scale_key("top"), top_scale),
                    metrics=metrics,
                ),
            )
        if right_scale is not None and getattr(right_scale, "secondary_axis", None) is not None:
            secondary_y = True
            ticks_right = axis_ticks(right_scale, params, "right", secondary=True)
            y_axis_right = max(y_axis_right, axis_extent(theme, ticks_right, metrics=metrics))
            y_title_right = max(
                y_title_right,
                axis_title_extent(
                    theme,
                    "right",
                    _secondary_title(build, params.scale_key("right"), right_scale),
                    metrics=metrics,
                ),
            )
    x_title = axis_title_extent(theme, "bottom", _axis_title_text(build, "x"), metrics=metrics)
    y_title = axis_title_extent(theme, "left", _axis_title_text(build, "y"), metrics=metrics)

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

    table = build.facet_table(metrics=metrics, right_inside=secondary_y)
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

    legend_boxes: list[Box | None] = [None] * len(guides)
    legend_box_origins: list[Box] = []
    legend_box_layouts: list[Any] = []
    for side in ("top", "right", "bottom", "left", "inside"):
        indices = group_indices.get(side)
        if not indices:
            continue
        box_layout = box_layouts[side]
        origin = _place_legend_box(
            box_layout,
            position=side,
            inner=inner,
            panel_area=panel_area,
            panel_rows=panel_rows,
            content_top=content_top,
            spacing=spacing,
            caption_cm=caption_cm,
            theme=theme,
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
    （`content_top` 已经扣掉了 `legend.box.spacing`），bottom 在注脚之上。
    inside 用 `legend.position.inside`（npc）+ `legend.justification.inside`
    锚在面板区内，不占版面。
    """
    width = float(box_layout.width_cm)
    height = float(box_layout.height_cm)
    if position == "right":
        x = inner.right - width
        y = panel_rows.y_cm + (panel_rows.height_cm - height) / 2.0
        return Box(x, y, width, height)
    if position == "left":
        x = inner.x_cm
        y = panel_rows.y_cm + (panel_rows.height_cm - height) / 2.0
        return Box(x, y, width, height)
    if position == "top":
        y = content_top + spacing
        x = panel_area.x_cm + (panel_area.width_cm - width) / 2.0
        return Box(x, y, width, height)
    if position == "bottom":
        y = inner.y_cm + caption_cm
        x = panel_area.x_cm + (panel_area.width_cm - width) / 2.0
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
) -> list[Any]:
    children: list[Any] = []
    for name, border_only in (("panel.background", False),):
        element = theme.get(name)
        if isinstance(element, ElementRect):
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
    for layer in layers:
        data = _panel_rows(layer.data, panel)
        if data is None or data.nrows == 0:
            continue
        geom = _geom_of(layer)
        panel_layer = replace(layer, data=data)
        grob = geom.draw(panel_layer, params, build.coord, theme, metrics)
        if isinstance(grob, (NullGrob, ZeroGrob)):
            continue
        layer_grobs.append(grob)
    if not layer_grobs:
        return children
    if _clip_state(params.clip) == "on":
        # 面板范围内的矩形裁剪（IR 里是 clip 节点；与视口裁剪取交）。
        children.append(
            clip_path(*layer_grobs, x=0.0, y=0.0, width=1.0, height=1.0, name="panel-clip")
        )
    else:
        children.extend(layer_grobs)
    return children


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
        values = theta_scale.minor_breaks() if kind == "minor" else theta_scale.breaks()
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
                    xs.tolist(),
                    ys.tolist(),
                    xs.tolist(),
                    ys.tolist(),
                    default_units="npc",
                    gp=_grid_gpar(theta_element, colour),
                    name=f"panel.grid.{kind}.{polar.theta_axis}",
                )
            )

    r_element = theme.get(f"panel.grid.{kind}.{polar.r_axis}")
    colour = paint(getattr(r_element, "colour", None))
    if isinstance(r_element, ElementLine) and colour is not None and r_scale is not None:
        values = r_scale.minor_breaks() if kind == "minor" else r_scale.breaks()
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


def _axis_grobs(
    build: PlotBuild,
    theme: ResolvedTheme,
    layout: PlotLayout,
    metrics: Any,
) -> list[Any]:
    grobs: list[Any] = []
    x_title = _axis_title_text(build, "x")
    y_title = _axis_title_text(build, "y")
    for panel, params in _panels(build):
        box = layout.panel_boxes.get(panel)
        if box is None:  # pragma: no cover
            continue
        cell = CellBox(1, 1, 1, 1, box.x_cm, box.y_cm, box.width_cm, box.height_cm)
        scale_bottom = _panel_scale(build, panel, params.scale_key("bottom"))
        scale_left = _panel_scale(build, panel, params.scale_key("left"))
        scale_top = _panel_scale(build, panel, params.scale_key("top"))
        scale_right = _panel_scale(build, panel, params.scale_key("right"))
        ticks_x = axis_ticks(scale_bottom, params, "bottom")
        ticks_y = axis_ticks(scale_left, params, "left")
        guide_x = guide_for(build, "x")
        guide_y = guide_for(build, "y")
        gx = axis_guide_ticks(scale_bottom, params, "bottom", guide_x, theme, base=ticks_x)
        gy = axis_guide_ticks(scale_left, params, "left", guide_y, theme, base=ticks_y)
        grobs.extend(
            axis_guide_grobs(theme, gx, cell, guide_x, metrics=metrics, name=f"axis-x-{panel}")
        )
        grobs.extend(
            axis_guide_grobs(theme, gy, cell, guide_y, metrics=metrics, name=f"axis-y-{panel}")
        )
        grobs.extend(
            _axis_line_grobs(
                theme,
                cell,
                name=f"axis-line-{panel}",
                ranges={
                    "bottom": axis_line_range(guide_x, gx),
                    "left": axis_line_range(guide_y, gy),
                },
            )
        )
        # 次轴（top / right）：断点 / 标签 / 位置由 `secondary_ticks()` 推。
        if scale_top is not None and getattr(scale_top, "secondary_axis", None) is not None:
            grobs.extend(
                axis_grobs(
                    theme,
                    axis_ticks(scale_top, params, "top", secondary=True),
                    cell,
                    metrics=metrics,
                    name=f"axis-x-sec-{panel}",
                )
            )
        if scale_right is not None and getattr(scale_right, "secondary_axis", None) is not None:
            grobs.extend(
                axis_grobs(
                    theme,
                    axis_ticks(scale_right, params, "right", secondary=True),
                    cell,
                    metrics=metrics,
                    name=f"axis-y-sec-{panel}",
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
    area = layout.panel_area
    if x_title:
        fake = CellBox(1, 1, 1, 1, area.x_cm, area.y_cm, area.width_cm, area.height_cm)
        grob = axis_title_grob(
            theme,
            "bottom",
            x_title,
            fake,
            labels_extent_cm=layout.x_axis_cm,
            metrics=metrics,
            name="axis-title-x",
        )
        if grob is not None:
            grobs.append(grob)
    if y_title:
        fake = CellBox(1, 1, 1, 1, area.x_cm, area.y_cm, area.width_cm, area.height_cm)
        grob = axis_title_grob(
            theme,
            "left",
            y_title,
            fake,
            labels_extent_cm=layout.y_axis_cm,
            metrics=metrics,
            name="axis-title-y",
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
                title = _secondary_title(build, params.scale_key("top"), scale)
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
                title = _secondary_title(build, params.scale_key("right"), scale)
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


def _axis_line_grobs(
    theme: ResolvedTheme,
    box: CellBox,
    *,
    name: str,
    ranges: Mapping[str, tuple[float, float] | None] | None = None,
) -> list[Any]:
    """`axis.line.x` / `axis.line.y`；`ranges` 给 `cap=` 裁出的端点（npc 0..1）。

    R 的轴线是 guide 的 decor（`GuideAxis$extract_decor()`），`cap=` 会把它收到
    最外一根刻度（`upper` / `lower` / `both`）；`None` = 整条边。
    """
    from ggcore.grobs import segments_grob

    ranges = ranges or {}
    grobs: list[Any] = []
    for side, element_name in (("bottom", "axis.line.x"), ("left", "axis.line.y")):
        element = theme.get(element_name)
        colour = paint(getattr(element, "colour", None))
        if colour is None:
            continue
        lwd = _mm_to_pt(getattr(element, "linewidth", None))
        low, high = ranges.get(side) or (0.0, 1.0)
        if high - low <= 1e-12:
            continue
        if side == "bottom":
            x0, y0 = box.x_cm + low * box.width_cm, box.y_cm
            x1, y1 = box.x_cm + high * box.width_cm, box.y_cm
        else:
            x0, y0 = box.x_cm, box.y_cm + low * box.height_cm
            x1, y1 = box.x_cm, box.y_cm + high * box.height_cm
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
        union = _union(layout.legend_boxes)
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
        children = guide.guide.gengrob(
            guide,
            build,
            theme,
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
    """主题的 `linewidth`（mm）→ gpar 的 `lwd`（pt）。"""
    if value is None:
        return 0.0
    try:
        return float(value) * PT_PER_INCH / 25.4
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
        grobs.extend(_one_strip(table, strip, theme, layout, area, sizes))
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
    return Box(area.x_cm + cell.x_cm, area.y_cm + cell.y_cm, cell.width_cm, cell.height_cm)


def _row_of(layout: Any, panel: int) -> int:
    return int(layout.row_of(panel))


def _one_strip(
    table: FacetTable,
    strip: FacetStrip,
    theme: ResolvedTheme,
    layout: PlotLayout,
    area: Box,
    sizes: Any,
) -> list[Any]:
    box = _strip_box(table, strip, layout, area, sizes)
    if box is None:
        return []
    background_name = "strip.background.y" if strip.side == "right" else "strip.background.x"
    background = theme.get(background_name)
    element = theme.get("strip.text.y" if strip.side == "right" else "strip.text.x")
    angle = float(element.angle or 0.0) if isinstance(element, ElementText) else 0.0
    parts = strip.parts or (StripPart("", strip.text, strip.fill),)
    grobs: list[Any] = []
    count = len(parts)
    for index, part in enumerate(parts):
        if strip.side == "top":
            # 顶部：parts 自上而下排列，**最后一个变量最靠近面板**
            # （R `weave_tables_row()`：`x + y ~ ...` 时 y 贴着面板、x 在最上）。
            slot_h = box.height_cm / count
            part_box = Box(box.x_cm, box.y_cm + (count - 1 - index) * slot_h, box.width_cm, slot_h)
        else:
            slot_w = box.width_cm / count
            part_box = Box(box.x_cm + index * slot_w, box.y_cm, slot_w, box.height_cm)
        name = strip.name if count == 1 else f"{strip.name}-{part.var}"
        if isinstance(background, ElementRect) and part.fill is not None:
            fill = _paint(part.fill)
            if fill is not None:
                grobs.append(
                    rect_grob(
                        x=unit(part_box.x_cm, "cm"),
                        y=unit(part_box.y_cm, "cm"),
                        width=unit(part_box.width_cm, "cm"),
                        height=unit(part_box.height_cm, "cm"),
                        hjust=0.0,
                        vjust=0.0,
                        gp=gpar(fill=fill, col=_paint(background.colour) or NA),
                        name=name,
                    )
                )
        if not isinstance(element, ElementText) or not part.text:
            continue
        grobs.append(
            text_grob(
                part.text,
                unit(part_box.x_cm + part_box.width_cm / 2.0, "cm"),
                unit(part_box.y_cm + part_box.height_cm / 2.0, "cm"),
                hjust=float(element.hjust if element.hjust is not None else 0.5),
                vjust=float(element.vjust if element.vjust is not None else 0.5),
                rot=angle,
                default_units="cm",
                gp=_text_gpar(element),
                name=f"{name}.text",
            )
        )
    return grobs


def _font_int(face: Any) -> int:
    return {"bold": 2, "italic": 3, "oblique": 3, "bold.italic": 4, "bolditalic": 4}.get(
        str(face or "plain").lower(), 1
    )

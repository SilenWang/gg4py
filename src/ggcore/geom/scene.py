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

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from ggcore import ir
from ggcore.axis import (
    axis_extent,
    axis_grobs,
    axis_ticks,
    axis_title_extent,
    axis_title_grob,
    break_positions,
    margin_sides_cm,
    minor_break_positions,
    paint,
    text_line_cm,
)
from ggcore.build import LayerBuild, PlotBuild, build_plot
from ggcore.coord import CoordBase, PanelParams
from ggcore.data import ColumnTable
from ggcore.facet import FacetStrip, FacetTable
from ggcore.grobs import (
    NullGrob,
    ZeroGrob,
    clip_path,
    g_tree,
    rect_grob,
    scene,
    text_grob,
)
from ggcore.gtable import CellBox
from ggcore.guide import (
    GuideBuild,
    GuideError,
    build_guides,
    legend_grob,
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


def _legend_position(theme: ResolvedTheme) -> str | None:
    value = theme.get("legend.position")
    if value is None:
        return "right"
    if isinstance(value, str):
        position = value
    elif isinstance(value, (int, float)):
        raise GuideError(
            f"legend.position = {value!r}（数值坐标）尚未实现；"
            "M1-11 只支持 'right' / 'left' / 'top' / 'bottom' / 'none'"
        )
    else:
        raise GuideError(f"legend.position 无法解析：{value!r}")
    if position == "inside":
        raise GuideError(
            'legend.position = "inside" 尚未实现（面板内图例需要 panel-relative 定位，'
            "见 docs/notes/guide.md「未实现」）"
        )
    if position not in ("right", "left", "top", "bottom", "none"):
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
    legend_layouts = tuple(
        legend_layout(guide, theme, position, metrics=metrics) for guide in guides
    )

    x_axis = 0.0
    y_axis = 0.0
    for panel, params in _panels(build):
        scale_x = _panel_scale(build, panel, "x")
        scale_y = _panel_scale(build, panel, "y")
        ticks_x = axis_ticks(scale_x, params, "bottom")
        ticks_y = axis_ticks(scale_y, params, "left")
        x_axis = max(x_axis, axis_extent(theme, ticks_x, metrics=metrics))
        y_axis = max(y_axis, axis_extent(theme, ticks_y, metrics=metrics))
    x_title = axis_title_extent(theme, "bottom", _axis_title_text(build, "x"), metrics=metrics)
    y_title = axis_title_extent(theme, "left", _axis_title_text(build, "y"), metrics=metrics)

    spacing = _box_spacing_cm(theme)
    conn_w, conn_h = 0.0, 0.0
    if legend_layouts:
        if position in ("right", "left"):
            conn_w = max(item.width_cm for item in legend_layouts)
            conn_h = sum(item.height_cm for item in legend_layouts) + _legend_gap(theme) * (
                len(legend_layouts) - 1
            )
            conn_w += _box_margin_width(theme)
            conn_h += _box_margin_height(theme)
        else:
            conn_w = sum(item.width_cm for item in legend_layouts) + _legend_gap(theme) * (
                len(legend_layouts) - 1
            )
            conn_h = max(item.height_cm for item in legend_layouts)
            conn_w += _box_margin_width(theme)
            conn_h += _box_margin_height(theme)

    content_top = inner.top - title_cm - subtitle_cm
    content_bottom = inner.y_cm + caption_cm
    content_left = inner.x_cm
    content_right = inner.right
    if legend_layouts and position == "right":
        content_right -= conn_w + spacing
    elif legend_layouts and position == "left":
        content_left += conn_w + spacing
    elif legend_layouts and position == "top":
        content_top -= conn_h + spacing
    elif legend_layouts and position == "bottom":
        content_bottom += conn_h + spacing

    panel_bottom = content_bottom + x_axis + x_title
    panel_left = content_left + y_axis + y_title
    panel_area = Box(
        panel_left,
        panel_bottom,
        content_right - panel_left,
        content_top - panel_bottom,
    )
    if panel_area.width_cm <= 0 or panel_area.height_cm <= 0:
        raise ValueError(
            "轴 / 图例 / 标题吃掉了整块面板区："
            f"面板区 {panel_area.width_cm:.3f}×{panel_area.height_cm:.3f}cm"
            "（页太小，或主题里的 spacing 过大）"
        )

    table = build.facet_table(metrics=metrics)
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

    legend_boxes: list[Box] = []
    if legend_layouts:
        legend_boxes = _place_legends(
            legend_layouts,
            position=position,
            inner=inner,
            panel_area=panel_area,
            content_top=content_top,
            spacing=spacing,
            caption_cm=caption_cm,
            conn_w=conn_w,
            conn_h=conn_h,
            theme=theme,
        )

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
        guides=guides,
    )


def _place_legends(
    layouts: tuple[Any, ...],
    *,
    position: str | None,
    inner: Box,
    panel_area: Box,
    content_top: float,
    spacing: float,
    caption_cm: float,
    conn_w: float,
    conn_h: float,
    theme: ResolvedTheme,
) -> list[Box]:
    """图例盒的页面矩形。

    竖向（right / left）在**面板区**里垂直居中（R 把 guide-box 挂在 panel 行上的
    0.5null 里）；横向（top / bottom）贴着内容区的上/下边缘：top 在副标题行之下
    （`content_top` 已经扣掉了 `legend.box.spacing`），bottom 在注脚之上。
    """
    gap = _legend_gap(theme)
    boxes: list[Box] = []
    if position in ("right", "left"):
        union_x = inner.right - conn_w if position == "right" else inner.x_cm
        top = panel_area.y_cm + (panel_area.height_cm + conn_h) / 2.0
        for index, item in enumerate(layouts):
            y = top - sum(previous.height_cm for previous in layouts[:index]) - gap * index
            y -= item.height_cm
            x = union_x + (conn_w - item.width_cm) / 2.0
            boxes.append(Box(x, y, item.width_cm, item.height_cm))
    else:
        if position == "bottom":
            union_y = inner.y_cm + caption_cm
        else:
            # content_top = 内区顶 - 标题/副标题 - conn_h - spacing
            union_y = content_top + spacing - conn_h
        left = panel_area.x_cm + (panel_area.width_cm - conn_w) / 2.0
        x = left
        for index, item in enumerate(layouts):
            x += sum(previous.width_cm for previous in layouts[:index]) + gap * index
            y = union_y + (conn_h - item.height_cm) / 2.0
            boxes.append(Box(x, y, item.width_cm, item.height_cm))
    return boxes


def _box_spacing_cm(theme: ResolvedTheme) -> float:
    from ggcore.units import convert_width

    value = theme.get("legend.box.spacing")
    if value is None:
        return 0.0
    return float(np.asarray(convert_width(value, "cm", ctx=UnitContext())).sum())


def _legend_gap(theme: ResolvedTheme) -> float:
    from ggcore.units import convert_width

    value = theme.get("legend.spacing")
    if value is None:
        return 0.0
    return float(np.asarray(convert_width(value, "cm", ctx=UnitContext())).sum())


def _box_margin_width(theme: ResolvedTheme) -> float:
    mt, mr, mb, ml = margin_sides_cm(theme.get("legend.box.margin"))
    del mt, mb
    return mr + ml


def _box_margin_height(theme: ResolvedTheme) -> float:
    mt, mr, mb, ml = margin_sides_cm(theme.get("legend.box.margin"))
    del mr, ml
    return mt + mb


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
    """一个面板的 z 序，照 R `Coord$draw_panel()`：bg（含网格）→ 图层 → fg。

    - `panel.background` / `panel.grid.*` 属于背景（`render_bg()`）；
    - `panel.border` 是前景（`render_fg()`，`fill = NA`），压在图层**之上**；
    - 网格线先次后主（`guide_grid()` 的 `y.minor, x.minor, y.major, x.major`）。
    """
    children: list[Any] = []
    background = theme.get("panel.background")
    if isinstance(background, ElementRect):
        grob = _rect_from_element(background, border_only=False, name="panel.background")
        if grob is not None:
            children.append(grob)
    children.extend(_panel_grid_grobs(build, panel, params, theme))

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
    if layer_grobs:
        if _clip_state(params.clip) == "on":
            # 面板范围内的矩形裁剪（IR 里是 clip 节点；与视口裁剪取交）。
            children.append(
                clip_path(*layer_grobs, x=0.0, y=0.0, width=1.0, height=1.0, name="panel-clip")
            )
        else:
            children.extend(layer_grobs)

    border = theme.get("panel.border")
    if isinstance(border, ElementRect):
        grob = _rect_from_element(border, border_only=True, name="panel.border")
        if grob is not None:
            children.append(grob)
    return children


#: 网格的绘制顺序：R `guide_grid()` 的 `y.minor, x.minor, y.major, x.major`。
_GRID_SIDES: tuple[tuple[str, str], ...] = (("left", "y"), ("bottom", "x"))


def _panel_grid_grobs(
    build: PlotBuild, panel: int, params: PanelParams, theme: ResolvedTheme
) -> list[Any]:
    """`panel.grid.major` / `panel.grid.minor`：在面板 npc 里按断点画直线。

    取值全部来自 `resolve_theme()` 的 `element_line`（colour / linewidth /
    linetype / lineend / linejoin），断点来自该面板自己的标度：

    - 主网格：`:func:`ggcore.axis.break_positions``（所有主断点，不看标签）；
    - 次网格：`:func:`ggcore.axis.minor_break_positions``（连续的次断点）；
    - `element_blank()` / `NA` 颜色不画，`None` 已在解析时回落到父元素。

    整组包在一个矩形裁剪节点里：R 的 `guide_grid()` 用 `±Inf` 端点、由面板
    视口裁到面板矩形；这里直接用 0..1 端点并再裁一次，线宽的半边也不会溢到
    面板外。
    """
    from ggcore.grobs import segments_grob

    grobs: list[Any] = []
    for grid, minor in (("panel.grid.minor", True), ("panel.grid.major", False)):
        for side, suffix in _GRID_SIDES:
            element = theme.get(f"{grid}.{suffix}")
            if not isinstance(element, ElementLine):
                continue
            colour = paint(element.colour)
            if colour is None:
                continue
            linetype = element.linetype if element.linetype is not None else 1
            if linetype == 0 or str(linetype).strip().lower() == "blank":
                continue
            scale = _panel_scale(build, panel, "x" if side == "bottom" else "y")
            if minor:
                positions = minor_break_positions(scale, params, side)
            else:
                positions = tuple(
                    position
                    for position in break_positions(scale, params, side)
                    if 0.0 <= position <= 1.0
                )
            if not positions:
                continue
            count = len(positions)
            gp = gpar(
                col=colour,
                lwd=_mm_to_pt(element.linewidth),
                lty=linetype,
                lineend=element.lineend or "round",
                linejoin=element.linejoin or "round",
            )
            name = f"{grid}.{suffix}"
            if side == "bottom":
                grobs.append(
                    segments_grob(
                        positions,
                        [0.0] * count,
                        positions,
                        [1.0] * count,
                        default_units="npc",
                        gp=gp,
                        name=name,
                    )
                )
            else:
                grobs.append(
                    segments_grob(
                        [0.0] * count,
                        positions,
                        [1.0] * count,
                        positions,
                        default_units="npc",
                        gp=gp,
                        name=name,
                    )
                )
    if not grobs:
        return []
    return [clip_path(*grobs, x=0.0, y=0.0, width=1.0, height=1.0, name="panel-grid-clip")]


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
        ticks_x = axis_ticks(_panel_scale(build, panel, "x"), params, "bottom")
        ticks_y = axis_ticks(_panel_scale(build, panel, "y"), params, "left")
        grobs.extend(axis_grobs(theme, ticks_x, cell, metrics=metrics, name=f"axis-x-{panel}"))
        grobs.extend(axis_grobs(theme, ticks_y, cell, metrics=metrics, name=f"axis-y-{panel}"))
        grobs.extend(_axis_line_grobs(theme, cell, name=f"axis-line-{panel}"))
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
    return grobs


def _axis_line_grobs(theme: ResolvedTheme, box: CellBox, *, name: str) -> list[Any]:
    from ggcore.grobs import segments_grob

    grobs: list[Any] = []
    for side, element_name in (("bottom", "axis.line.x"), ("left", "axis.line.y")):
        element = theme.get(element_name)
        colour = paint(getattr(element, "colour", None))
        if colour is None:
            continue
        lwd = _mm_to_pt(getattr(element, "linewidth", None))
        if side == "bottom":
            coords = (
                [box.x_cm, box.x_cm + box.width_cm],
                [box.y_cm, box.y_cm],
            )
        else:
            coords = (
                [box.x_cm, box.x_cm],
                [box.y_cm, box.y_cm + box.height_cm],
            )
        grobs.append(
            segments_grob(
                coords[0],
                coords[1],
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
        children = legend_grob(
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
        grobs.extend(_one_strip(table, strip, theme, area, sizes))
    return grobs


def _one_strip(
    table: FacetTable,
    strip: FacetStrip,
    theme: ResolvedTheme,
    area: Box,
    sizes: Any,
) -> list[Any]:
    placement = next((row for row in table.gtable.layout if row.name == strip.name), None)
    if placement is None:  # pragma: no cover - facet_table 保证有
        return []
    cell = table.gtable.region_box(
        placement.t,
        placement.l,
        placement.b,
        placement.r,
        width_cm=area.width_cm,
        height_cm=area.height_cm,
        sizes=sizes,
    )
    box = Box(area.x_cm + cell.x_cm, area.y_cm + cell.y_cm, cell.width_cm, cell.height_cm)
    grobs: list[Any] = []
    background_name = "strip.background.y" if strip.side == "right" else "strip.background.x"
    background = theme.get(background_name)
    if isinstance(background, ElementRect):
        fill = _paint(background.fill)
        if fill is not None:
            grobs.append(
                rect_grob(
                    x=unit(box.x_cm, "cm"),
                    y=unit(box.y_cm, "cm"),
                    width=unit(box.width_cm, "cm"),
                    height=unit(box.height_cm, "cm"),
                    hjust=0.0,
                    vjust=0.0,
                    gp=gpar(fill=fill, col=_paint(background.colour) or NA),
                    name=strip.name,
                )
            )
    element = theme.get("strip.text.y" if strip.side == "right" else "strip.text.x")
    if not isinstance(element, ElementText) or not strip.text:
        return grobs
    angle = float(element.angle or 0.0) if strip.side != "right" else float(element.angle or -90.0)
    grobs.append(
        text_grob(
            strip.text,
            unit(box.x_cm + box.width_cm / 2.0, "cm"),
            unit(box.y_cm + box.height_cm / 2.0, "cm"),
            hjust=float(element.hjust if element.hjust is not None else 0.5),
            vjust=float(element.vjust if element.vjust is not None else 0.5),
            rot=angle,
            default_units="cm",
            gp=_text_gpar(element),
            name=f"{strip.name}.text",
        )
    )
    return grobs


def _font_int(face: Any) -> int:
    return {"bold": 2, "italic": 3, "oblique": 3, "bold.italic": 4, "bolditalic": 4}.get(
        str(face or "plain").lower(), 1
    )

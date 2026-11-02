"""面板场景装配：`PlotBuild` + `FacetTable` → `ir.Scene`（M1-7）。

结构照 ggplot2 的 `ggplot_gtable()` + `Layer$draw_geom()`：

```
page viewport（整页）
├── plot.background
├── panel viewport ×N（xscale/yscale = 0..1，clip = panel_params$clip）
│   ├── panel.background / panel.border
│   ├── clipPath（clip = "on"：矩形裁剪节点，不是画完再裁）
│   └── 每层 → Geom.draw()（grob / gTree）
└── strip（strip.background.x/.y + strip.text.x/.y）
```

口径：

- 面板矩形来自 M1-6 的 `FacetTable.panel_boxes()`（gtable 的行列解析），strip 的
  尺寸 / 间距 / 文字都取 `resolve_theme()` 的解析值，**不硬编码 cm / pt**；
- 图层按层序绘进各自面板；空层（0 行）不产生 grob；
- 单面板（`facet_null`）走同一条路径：`FacetTable` 仍是 1×1 表，面板就是整页
  （theme_void 坐标轴留白为 0 时与 M0-9 的整页场景一致）；
- 轴、图例、标题是 M1-11 的事；本任务只画面板 + strip（`docs/notes/geom.md`）。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np

from ggcore import ir
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
from ggcore.theme import (
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
    "scene_from_build",
    "scene_from_plot",
]

DEFAULT_WIDTH_IN = 7.0
DEFAULT_HEIGHT_IN = 7.0


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
    """`PlotBuild` + `facet_table()` → `ir.Scene`（pt、y 向下）。"""
    del dpi  # 设备分辨率不属于场景；`Scene.dpi` 由 `ir.Scene` 的默认值给出
    theme = resolve_theme(build.theme if isinstance(build.theme, Theme) else Theme(), metrics)
    table = build.facet_table(metrics=metrics)
    width_cm = float(width_in) * CM_PER_INCH
    height_cm = float(height_in) * CM_PER_INCH
    ctx = UnitContext(metrics=metrics)

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
    background = _rect_for(theme, "plot.background", width_cm, height_cm, centre=True)
    if background is not None:
        grobs.append(background)

    prepared = [_prepare_layer(layer) for layer in build.layers]
    boxes = table.panel_boxes(width_cm, height_cm, ctx=ctx)
    for panel, params in _panels(build):
        box = boxes.get(panel)
        if box is None:  # pragma: no cover - FacetTable 一定覆盖每个 panel
            continue
        children = _panel_children(build, prepared, panel, params, theme, metrics)
        if not children:
            continue
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

    grobs.extend(_strip_grobs(table, theme, width_cm, height_cm, ctx))
    return scene(grobs, tree).to_ir_scene()


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
    for name, border_only in (("panel.background", False), ("panel.border", True)):
        element = theme.get(name)
        if isinstance(element, ElementRect):
            grob = _rect_from_element(element, border_only=border_only, name=name)
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
    """主题颜色 → 可绘制的颜色；`NA` / `transparent` / 缺失 → None。"""
    if value is None or value is NA or not isinstance(value, str):
        return None
    text = value.strip()
    if text.lower() == "transparent":
        return None
    if text.startswith("#") and len(text) == 9 and text[7:9].lower() == "00":
        return None  # theme_void 的 paper（#00000000）不画
    return value


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
    width_cm: float,
    height_cm: float,
    ctx: UnitContext,
) -> list[Any]:
    if not table.strips:
        return []
    sizes = table.gtable.resolve(width_cm, height_cm, ctx=ctx)
    grobs: list[Any] = []
    for strip in table.strips:
        grobs.extend(_one_strip(table, strip, theme, width_cm, height_cm, sizes, ctx))
    return grobs


def _one_strip(
    table: FacetTable,
    strip: FacetStrip,
    theme: ResolvedTheme,
    width_cm: float,
    height_cm: float,
    sizes: Any,
    ctx: UnitContext,
) -> list[Any]:
    placement = next((row for row in table.gtable.layout if row.name == strip.name), None)
    if placement is None:  # pragma: no cover - facet_table 保证有
        return []
    box = table.gtable.region_box(
        placement.t,
        placement.l,
        placement.b,
        placement.r,
        width_cm=width_cm,
        height_cm=height_cm,
        sizes=sizes,
        ctx=ctx,
    )
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
            gp=gpar(
                col=_paint(element.colour) or "black",
                fontsize=float(element.size or 11.0),
                fontfamily=element.family or "",
                font=_font_int(element.face),
                lineheight=float(element.lineheight or 1.2),
            ),
            name=f"{strip.name}.text",
        )
    )
    return grobs


def _font_int(face: Any) -> int:
    return {"bold": 2, "italic": 3, "oblique": 3, "bold.italic": 4, "bolditalic": 4}.get(
        str(face or "plain").lower(), 1
    )

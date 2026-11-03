"""geom 绘制实现注册表（M1-7 / M2-S2）。

M1-7 的 9 个 + M2-S2 的 20 个长尾 geom，各有一个
:class:`~ggcore.geom.base.GeomRenderer` 实现；绘制入口挂在
:class:`ggcore.layer.Geom` 上（`Geom.draw()` / `Geom.setup_data()` /
`Geom.handle_na()` / `Geom.setup_params()`），**构造函数路径不变**：`as_geom()` /
`geom_*()` 仍然只产生 `Geom(name=…)` 数据对象。

```python
from ggcore import geom
geom.renderer_for("point").draw(geom_obj, build, panel, coord, theme, metrics)
```

`renderer_for()` 对未实现的 geom 名报 :class:`GeomError`（消息里列出已实现的名字），
不会静默降级。
"""

from __future__ import annotations

from ggcore.geom.annotation import BlankRenderer, MapRenderer, RugRenderer
from ggcore.geom.bar import AreaRenderer, BarRenderer, HistogramRenderer
from ggcore.geom.base import (
    GeomError,
    GeomRenderer,
    flip_data,
    table_numeric,
    table_strings,
)
from ggcore.geom.boxplot import BoxplotRenderer
from ggcore.geom.dist import (
    Bin2dRenderer,
    ContourFilledRenderer,
    ContourRenderer,
    CountRenderer,
    Density2dFilledRenderer,
    Density2dRenderer,
    DensityRenderer,
    DotplotRenderer,
    FunctionRenderer,
    HexRenderer,
    JitterRenderer,
    QqLineRenderer,
    QqRenderer,
    QuantileRenderer,
    ViolinRenderer,
)
from ggcore.geom.interval import (
    CrossbarRenderer,
    ErrorbarhRenderer,
    ErrorbarRenderer,
    LinerangeRenderer,
    PointrangeRenderer,
)
from ggcore.geom.line import LineRenderer, PathRenderer
from ggcore.geom.point import PointRenderer
from ggcore.geom.polygon import PolygonRenderer, RibbonRenderer, StepRenderer
from ggcore.geom.rect import RasterRenderer, RectRenderer, TileRenderer
from ggcore.geom.segment import (
    AblineRenderer,
    CurveRenderer,
    HlineRenderer,
    SegmentRenderer,
    SpokeRenderer,
    VlineRenderer,
)
from ggcore.geom.smooth import SmoothRenderer
from ggcore.geom.stat2d import BUILD_ONLY_RENDERERS
from ggcore.geom.text import LabelRenderer, TextRenderer

__all__ = [
    "GEOM_RENDERERS",
    "AblineRenderer",
    "AreaRenderer",
    "BarRenderer",
    "Bin2dRenderer",
    "BlankRenderer",
    "BoxplotRenderer",
    "ColRenderer",
    "ContourFilledRenderer",
    "ContourRenderer",
    "CountRenderer",
    "CrossbarRenderer",
    "CurveRenderer",
    "Density2dFilledRenderer",
    "Density2dRenderer",
    "DensityRenderer",
    "DotplotRenderer",
    "ErrorbarRenderer",
    "ErrorbarhRenderer",
    "FunctionRenderer",
    "GeomError",
    "GeomRenderer",
    "HexRenderer",
    "HistogramRenderer",
    "HlineRenderer",
    "JitterRenderer",
    "LabelRenderer",
    "LineRenderer",
    "LinerangeRenderer",
    "MapRenderer",
    "PathRenderer",
    "PointRenderer",
    "PointrangeRenderer",
    "PolygonRenderer",
    "QqLineRenderer",
    "QqRenderer",
    "QuantileRenderer",
    "RasterRenderer",
    "RectRenderer",
    "RibbonRenderer",
    "RugRenderer",
    "SegmentRenderer",
    "SmoothRenderer",
    "SpokeRenderer",
    "StepRenderer",
    "TextRenderer",
    "TileRenderer",
    "ViolinRenderer",
    "VlineRenderer",
    "flip_data",
    "registered_renderers",
    "renderer_for",
    "table_numeric",
    "table_strings",
]


class ColRenderer(BarRenderer):
    """`geom_col`：绘制与 `geom_bar` 相同（只是默认 stat 不同）。"""

    name = "col"


#: geom 名 → 绘制实现（单例；无状态）。
GEOM_RENDERERS: dict[str, GeomRenderer] = {
    "point": PointRenderer(),
    "line": LineRenderer(),
    "path": PathRenderer(),
    "bar": BarRenderer(),
    "col": ColRenderer(),
    "area": AreaRenderer(),
    "histogram": HistogramRenderer(),
    "boxplot": BoxplotRenderer(),
    "smooth": SmoothRenderer(),
    # M2-S2：线段 / 矩形 / 区间 / 标注族（20 个导出）
    "abline": AblineRenderer(),
    "hline": HlineRenderer(),
    "vline": VlineRenderer(),
    "segment": SegmentRenderer(),
    "curve": CurveRenderer(),
    "spoke": SpokeRenderer(),
    "rect": RectRenderer(),
    "tile": TileRenderer(),
    "raster": RasterRenderer(),
    "polygon": PolygonRenderer(),
    "ribbon": RibbonRenderer(),
    "step": StepRenderer(),
    "errorbar": ErrorbarRenderer(),
    "errorbarh": ErrorbarhRenderer(),
    "linerange": LinerangeRenderer(),
    "pointrange": PointrangeRenderer(),
    "crossbar": CrossbarRenderer(),
    "blank": BlankRenderer(),
    "rug": RugRenderer(),
    "map": MapRenderer(),
    # M2-7 长尾 B：文本 / 点 / 分布 / 2D 族（20 个注册名）
    "text": TextRenderer(),
    "label": LabelRenderer(),
    "jitter": JitterRenderer(),
    "count": CountRenderer(),
    "bin2d": Bin2dRenderer(),
    "bin_2d": Bin2dRenderer(),
    "hex": HexRenderer(),
    "density": DensityRenderer(),
    "density_2d": Density2dRenderer(),
    "density2d": Density2dRenderer(),
    "density_2d_filled": Density2dFilledRenderer(),
    "density2d_filled": Density2dFilledRenderer(),
    "contour": ContourRenderer(),
    "contour_filled": ContourFilledRenderer(),
    "dotplot": DotplotRenderer(),
    "violin": ViolinRenderer(),
    "qq": QqRenderer(),
    "qq_line": QqLineRenderer(),
    "quantile": QuantileRenderer(),
    "function": FunctionRenderer(),
}


def registered_renderers() -> tuple[str, ...]:
    """已实现绘制的 geom 名，按登记顺序。"""
    return tuple(GEOM_RENDERERS)


def renderer_for(name: str) -> GeomRenderer:
    """按 geom 名取绘制实现；没有实现时点名。

    先查可绘制的 `GEOM_RENDERERS`，再查只有 build 级实现的
    `BUILD_ONLY_RENDERERS`（M2-6 的 2D 族：`setup_data()` 有了，`draw()` 归
    SIL-737（`tile`）与 SIL-735（其余 5 个））。
    """
    try:
        return GEOM_RENDERERS[name]
    except KeyError:
        pass
    try:
        return BUILD_ONLY_RENDERERS[name]
    except KeyError:
        raise GeomError(
            f"geom_{name} 没有绘制实现；已实现：{', '.join(registered_renderers())}"
            "（见 docs/notes/geom.md）"
        ) from None


def build_only_renderers() -> tuple[str, ...]:
    """只有 build 级实现（没有 `draw()`）的 geom 名。

    `GEOM_RENDERERS` 里已经能画的名字不算——M2-S2 之后 `tile` / `hex` / `contour` /
    `contour_filled` / `density_2d` / `density_2d_filled` 都由 geom 层接管绘制，
    `BUILD_ONLY_RENDERERS` 只剩仍未落地绘制的名字。
    """
    return tuple(name for name in BUILD_ONLY_RENDERERS if name not in GEOM_RENDERERS)


def has_renderer(name: str) -> bool:
    return name in GEOM_RENDERERS or name in BUILD_ONLY_RENDERERS


def __getattr__(name: str) -> object:  # pragma: no cover - 兼容旧导入路径
    raise AttributeError(f"module 'ggcore.geom' has no attribute {name!r}")

"""geom 绘制实现注册表（M1-7）。

9 个 geom 各有一个 :class:`~ggcore.geom.base.GeomRenderer` 实现；绘制入口挂在
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

from ggcore.geom.bar import AreaRenderer, BarRenderer, HistogramRenderer
from ggcore.geom.base import (
    GeomError,
    GeomRenderer,
    flip_data,
    table_numeric,
    table_strings,
)
from ggcore.geom.boxplot import BoxplotRenderer
from ggcore.geom.line import LineRenderer, PathRenderer
from ggcore.geom.point import PointRenderer
from ggcore.geom.smooth import SmoothRenderer
from ggcore.geom.stat2d import BUILD_ONLY_RENDERERS

__all__ = [
    "GEOM_RENDERERS",
    "AreaRenderer",
    "BarRenderer",
    "BoxplotRenderer",
    "ColRenderer",
    "GeomError",
    "GeomRenderer",
    "HistogramRenderer",
    "LineRenderer",
    "PathRenderer",
    "PointRenderer",
    "SmoothRenderer",
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
}


def registered_renderers() -> tuple[str, ...]:
    """已实现绘制的 geom 名，按登记顺序。"""
    return tuple(GEOM_RENDERERS)


def renderer_for(name: str) -> GeomRenderer:
    """按 geom 名取绘制实现；没有实现时点名。

    先查可绘制的 `GEOM_RENDERERS`，再查只有 build 级实现的
    `BUILD_ONLY_RENDERERS`（M2-6 的 2D 族：`setup_data()` 有了，`draw()` 归
    SIL-735）。
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
    """只有 build 级实现（没有 `draw()`）的 geom 名。"""
    return tuple(BUILD_ONLY_RENDERERS)


def has_renderer(name: str) -> bool:
    return name in GEOM_RENDERERS or name in BUILD_ONLY_RENDERERS


def __getattr__(name: str) -> object:  # pragma: no cover - 兼容旧导入路径
    raise AttributeError(f"module 'ggcore.geom' has no attribute {name!r}")

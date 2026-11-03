"""`ggplot()` 对象、`+` 组合（`gg_add`）与克隆语义。

    p = ggplot(mpg, aes(x="displ", y="hwy"))
    p + geom_point()                 # 新对象；p 的 layers 仍是空
    p.geom_point()                   # 同一个注册表项的别名

三件事在这里落地：

1. **字段对齐 ggplot2 4.0.3 的 ggplot 对象**：`data / mapping / layers / scales /
   guides / theme / coordinates / facet / labels`（另加 `position`，见下）。构造
   时不认识的 kwarg 直接报错，避免拼错字段名后带着空字段一路走到深层。
2. **`gg_add(plot, component)` 双参数分派**：`functools.singledispatch` 只按第一
   个参数分派，所以这里叠了两层——外层按 plot（`gg_add.register(ggplot)`），内层
   按 component（layer / scale / theme / coord / facet / guide / labels 各一格，
   未登记的类型落到 `object` 的报错分支）。`ggplot.__add__` 只是它的糖。
3. **克隆语义**：`p + x` 永远返回新对象，可变容器（list / dict）复制，不可变值
   （data 引用、`Aes`、各组件对象）共享。

`position` 字段是 gg4py 保留的 plot 级默认位置调整（上游把 position 放在 layer
上）；M1-1 只保存它，语义由后续任务使用。
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import singledispatch
from typing import Any

from ggcore import registry
from ggcore.aes import Aes, as_aes, frozen_mapping
from ggcore.aes import aes as aes
from ggcore.aes import after_stat as after_stat
from ggcore.axis import dup_axis as dup_axis
from ggcore.axis import sec_axis as sec_axis
from ggcore.components import Coord, Facet, Guide, Labels, Scale, Theme
from ggcore.coord import coord_munch as coord_munch
from ggcore.layer import Layer, Position
from ggcore.scales import scale_type as scale_type
from ggcore.theme import merge_theme, theme_grey

__all__: list[str] = []


class ggplot:
    """一张图的语法对象：数据 + 映射 + 组件列表。

    所有字段都可以直接读；改动走 `+`（返回克隆）而不是原地写入。
    """

    def __init__(
        self,
        data: Any = None,
        mapping: Aes | Mapping[str, Any] | None = None,
        *,
        layers: list[Layer] | None = None,
        scales: Mapping[str, Scale] | None = None,
        guides: Mapping[str, Guide] | None = None,
        theme: Theme | None = None,
        coordinates: Coord | None = None,
        facet: Facet | None = None,
        labels: Mapping[str, Any] | None = None,
        position: Position | None = None,
        **kwargs: Any,
    ) -> None:
        if kwargs:
            unknown = ", ".join(sorted(kwargs))
            known = (
                "data, mapping, layers, scales, guides, theme, coordinates, facet, labels, position"
            )
            raise TypeError(f"ggplot() 不认识这些参数：{unknown}；可用字段：{known}")
        self.data = data
        self.mapping = as_aes(mapping)
        self.layers: list[Layer] = list(layers) if layers is not None else []
        self.scales: dict[str, Scale] = dict(scales) if scales is not None else {}
        self.guides: dict[str, Guide] = dict(guides) if guides is not None else {}
        # ggplot2 的默认主题是 theme_grey()；`p + theme_void()` 这类完整主题
        # 整份替换它（merge_theme 的语义），局部 theme() 只合并元素。
        self.theme: Theme = theme if theme is not None else theme_grey()
        self.coordinates: Coord = coordinates if coordinates is not None else Coord("cartesian")
        self.facet: Facet = facet if facet is not None else Facet("null")
        self.labels: dict[str, Any] = dict(frozen_mapping(labels)) if labels is not None else {}
        self.position: Position | None = position

    # -- 克隆 ---------------------------------------------------------------

    def clone(self) -> ggplot:
        """复制一份：可变容器新开，不可变值原样共享。"""
        clone = type(self).__new__(type(self))
        clone.data = self.data
        clone.mapping = self.mapping
        clone.layers = list(self.layers)
        clone.scales = dict(self.scales)
        clone.guides = dict(self.guides)
        clone.theme = self.theme
        clone.coordinates = self.coordinates
        clone.facet = self.facet
        clone.labels = dict(self.labels)
        clone.position = self.position
        return clone

    def __add__(self, component: Any) -> ggplot:
        return gg_add(self, component)

    # -- 调试摘要 -----------------------------------------------------------

    def __repr__(self) -> str:
        rows_cols = _data_shape(self.data)
        if self.data is None:
            data = "None"
        elif rows_cols is None:
            data = "?"
        else:
            data = f"{rows_cols[0]}×{rows_cols[1]}"
        keys = ", ".join(self.mapping)
        return f"<ggplot: data={data}, layers={len(self.layers)}, mapping=[{keys}]>"


def _data_shape(data: Any) -> tuple[int, int] | None:
    """data 的 (行数, 列数)。认 DataFrame 的 `shape`、`nrows`+`columns()`、dict。"""
    if data is None or isinstance(data, (str, bytes)):
        return None

    nrows = getattr(data, "nrows", None)
    columns = getattr(data, "columns", None)
    if isinstance(nrows, int) and columns is not None:
        try:
            names = columns() if callable(columns) else columns
            return (nrows, len(names))
        except TypeError:
            return None

    shape = getattr(data, "shape", None)
    if isinstance(shape, tuple) and len(shape) == 2 and all(isinstance(v, int) for v in shape):
        return (shape[0], shape[1])

    if isinstance(data, Mapping):
        count = len(data)
        if count == 0:
            return (0, 0)
        first = next(iter(data.values()), None)
        try:
            rows = len(first)
        except TypeError:
            rows = 1
        return (rows, count)

    return None


@singledispatch
def gg_add(plot: Any, component: Any) -> Any:
    """把 `component` 加到 `plot` 上，返回新对象。

    外层按 plot 类型分派；目前只有 `ggplot` 一格，其它类型直接报错。
    """
    raise TypeError(
        f"gg_add() 不支持 {type(plot).__name__} 作为 plot；第一个参数必须是 ggplot() 对象"
    )


@gg_add.register(ggplot)
def _gg_add_ggplot(plot: ggplot, component: Any) -> ggplot:
    if component is None:
        # ggplot2 的 `p + NULL` 是空操作；这里同样不改变 p，但仍返回新对象。
        return plot.clone()
    return _add_component(component, plot)


@singledispatch
def _add_component(component: Any, plot: ggplot) -> ggplot:
    """内层按 component 类型分派（双参数分派的第二半）。"""
    raise TypeError(
        f"不能把 {type(component).__name__} 加到 ggplot 上；"
        "可加的类型：Layer / Scale / Theme / Coord / Facet / Guide / Labels / Position"
    )


@_add_component.register(Layer)
def _add_layer(component: Layer, plot: ggplot) -> ggplot:
    new = plot.clone()
    new.layers.append(component)
    return new


@_add_component.register(Scale)
def _add_scale(component: Scale, plot: ggplot) -> ggplot:
    new = plot.clone()
    new.scales[component.key] = component
    return new


@_add_component.register(Theme)
def _add_theme(component: Theme, plot: ggplot) -> ggplot:
    new = plot.clone()
    new.theme = merge_theme(plot.theme, component)
    return new


@_add_component.register(Coord)
def _add_coord(component: Coord, plot: ggplot) -> ggplot:
    new = plot.clone()
    new.coordinates = component
    return new


@_add_component.register(Facet)
def _add_facet(component: Facet, plot: ggplot) -> ggplot:
    new = plot.clone()
    new.facet = component
    return new


@_add_component.register(Guide)
def _add_guide(component: Guide, plot: ggplot) -> ggplot:
    new = plot.clone()
    new.guides[component.key] = component
    return new


@_add_component.register(Labels)
def _add_labels(component: Labels, plot: ggplot) -> ggplot:
    new = plot.clone()
    new.labels.update(component.values)
    return new


@_add_component.register(Position)
def _add_position(component: Position, plot: ggplot) -> ggplot:
    """`p + position_dodge()`：记成 plot 级默认位置调整。

    上游 4.0.3 会直接报「Can't add `position_dodge()` to a <ggplot> object」；
    gg4py 的 ggplot 对象保留了 `position` 字段（M1-1），注册表的「两个入口」
    因此对 position 也成立。图层自己的 `Layer.position` 仍是流水线真正读取的
    那一份（见 docs/notes/position.md「差异面」）。
    """
    new = plot.clone()
    new.position = component
    return new


# 注册表 → ggplot 的方法（`p.geom_point()` 与 `p + geom_point()` 同一实现）。
registry.bind_plot(ggplot)


# 模块级函数与 registry 里的**同一个函数对象**（两个入口，一条注册表）。
# label 的入口叫 `labs`，没有前缀，其余形如 `geom_point` / `scale_x_log10`。
def _export_registry_entries() -> list[str]:
    # `sec_axis` / `dup_axis` 不是注册表项（没有 coord_/scale_ 前缀），
    # 但用户从 `ggcore.plot` 取它们最顺手，与 ggplot2 的用法一致（M2-1）。
    names = ["aes", "after_stat", "ggplot", "gg_add", "coord_munch", "sec_axis", "dup_axis"]
    for kind in registry.KINDS:
        for name in registry.registered(kind):
            entry = registry.entry_name(kind, name)
            globals()[entry] = getattr(registry, entry)
            names.append(entry)
    return names


__all__ = _export_registry_entries()

"""组件注册表：名字 → 构造器。**一条注册表，两个入口。**

ggplot2 的 `geom_point()` / `theme_grey()` / `scale_x_log10()` 这类函数在这里
登记一次，然后同时得到：

1. 模块级函数：`ggcore.registry.geom_point(...)`（`ggcore.plot` 会再导出同一
   个函数对象）；
2. `ggplot` 的方法：`p.geom_point(...)`，它等价于 `p + geom_point(...)`。

两个入口都**不缓存构造器**——调用时按名字回注册表查。所以测试里把某个注册项
换掉，`p.geom_point()` 的行为立刻跟着变（这是 M1-1 验收要求「同源」的证据）。

遍历顺序：`KINDS` 是固定元组，每个种类内部用 dict 的插入序（不是 set），
默认登记顺序写在 `_register_defaults()` 里，可复现。

## 参数路由（M1-3 的约定，别让它变成隐性坑）

- `geom_*(...)` 的 `**params` 只进 `Layer.params`（几何参数）；
- `stat_*(...)` 的 `**params` 只进 `Stat.params`（统计参数）；
- 两边都不互传。`geom_histogram(bins=30)` 的 `bins` 落在 `Layer.params`，
  `Stat("bin").params` 为空；M1-3 需要 stat 参数时显式构造
  `stat=Stat("bin", {"bins": 30})`（或由 stat 层自己从 `Layer.params` 取）。
  当前 `_stat_layer_factory` / `_geom_layer_factory` 的行为与这条一致，有
  `tests/test_registry.py` 的 `test_params_route_to_layer_or_stat_only` 守着。

跨模块依赖只有 ggcore 自身（X1 白名单）：`aes` / `components` / `layer`。
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from ggcore.aes import as_aes, frozen_mapping
from ggcore.components import Coord, Facet, Guide, Labels, Scale, Theme
from ggcore.layer import Geom, Layer, Position, Stat, as_geom, as_position, as_stat

#: 组件种类，顺序即遍历顺序（不要改成 set）。
KINDS: tuple[str, ...] = ("geom", "stat", "scale", "coord", "facet", "guide", "theme", "label")

#: 每种组件生成入口函数 / 方法时用的前缀。label 是 `labs()`，没有前缀。
PREFIXES: Mapping[str, str] = MappingProxyType(
    {
        "geom": "geom_",
        "stat": "stat_",
        "scale": "scale_",
        "coord": "coord_",
        "facet": "facet_",
        "guide": "guide_",
        "theme": "theme_",
        "label": "",
    }
)

#: 公开 API 的静态部分；`geom_*` / `stat_*` … 这些入口由 `_refresh_entry` 在
#: 登记时追加、`unregister` 时移除，所以 `from ggcore.registry import *` 始终
#: 与当前注册表一致（不会出现 `__all__` 里留着已删除名字的 AttributeError）。
__all__: list[str] = [
    "GEOM_SPECS",
    "KINDS",
    "PREFIXES",
    "SCALE_SPECS",
    "STAT_GEOMS",
    "STAT_NAMES",
    "GeomSpec",
    "bind_plot",
    "construct",
    "entry_name",
    "register",
    "register_coord",
    "register_facet",
    "register_geom",
    "register_guide",
    "register_label",
    "register_scale",
    "register_stat",
    "register_theme",
    "registered",
    "required_aes_groups",
    "unregister",
]

#: 每个种类的有序注册表。用 dict 的插入序，保证遍历稳定。
_REGISTRY: dict[str, dict[str, Callable[..., Any]]] = {kind: {} for kind in KINDS}

#: `ggplot` 类在 `ggcore.plot` 导入时注册进来（避免 registry ↔ plot 循环导入）。
_PLOT_CLASS: type[Any] | None = None
#: `ggplot` 所在的模块（`ggcore.plot`），用来把新登记的名字也挂成模块级函数。
_PLOT_MODULE: Any = None


@dataclass(frozen=True, slots=True)
class GeomSpec:
    """geom 的静态契约（对齐 ggplot2 4.0.3）。

    - `required_aes` 是 **stat 之后**的必需列：`bar` / `histogram` 的 `y` 由
      `stat_count` / `stat_bin` 产出，数据里可以没有；M1-3 的流水线按这个顺序
      （先 stat、再校验）使用。
    - 名字里出现 `|` 的是上游的备选写法（如 boxplot 的 `"x|y"`），用
      :func:`required_aes_groups` 拆开判断。
    - `default_aes` 是「按 theme_grey 解析后」的静态值（上游写的是
      `from_theme(...)` 表达式）；M1-10 做主题元素树时再按需重新解析，之前
      别把它当成会随主题变化的动态值。
    - `stat` / `position` 是这个 geom 的默认构造；`geom_*(position=...)` 可覆盖。
      bar / col / histogram / area 默认 `stack`，boxplot 默认 `dodge2`，其余
      `identity`（与 ggplot2 4.0.3 一致）。
    """

    required_aes: tuple[str, ...]
    default_aes: dict[str, Any]
    stat: str = "identity"
    position: str = "identity"


def required_aes_groups(required_aes: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    """把上游的 `"x|y"` 备选写法拆成名字组。

    M1-3 的校验口径：每一组里至少有一个名字在（stat 之后的）数据里存在。
    例：boxplot 的 `("x|y", "lower|xlower", ...)` → `(("x", "y"), ("lower",
    "xlower"), ...)`。
    """
    return tuple(tuple(name.split("|")) for name in required_aes)


def entry_name(kind: str, name: str) -> str:
    """注册名 → 入口名（`("geom", "point")` → `"geom_point"`）。"""
    _check_kind(kind)
    return f"{PREFIXES[kind]}{name}"


def _check_kind(kind: str) -> None:
    if kind not in _REGISTRY:
        raise ValueError(f"未知组件种类 {kind!r}；可用：{', '.join(KINDS)}")


def registered(kind: str) -> tuple[str, ...]:
    """某一类组件已注册的名字，按登记顺序。"""
    _check_kind(kind)
    return tuple(_REGISTRY[kind])


def register(kind: str, name: str, constructor: Callable[..., Any]) -> Callable[..., Any]:
    """登记一个组件构造器，并（重新）生成两个入口。

    - 同名重复登记是替换，不是追加（顺序保持第一次出现的位置）；
    - 名字必须能拼出合法标识符，否则入口函数没法用属性/方法的方式暴露。
    """
    _check_kind(kind)
    if not isinstance(name, str):
        raise TypeError(f"组件名必须是 str，得到 {type(name).__name__}")
    if not callable(constructor):
        raise TypeError(f"{entry_name(kind, name)} 的构造器必须可调用")
    entry = entry_name(kind, name)
    if not entry.isidentifier():
        raise ValueError(f"组件名 {name!r} 生成的入口 {entry!r} 不是合法标识符")
    _REGISTRY[kind][name] = constructor
    _refresh_entry(kind, name)
    return constructor


def unregister(kind: str, name: str) -> None:
    """撤销登记，并清掉两个入口（测试与后续任务的替换用）。"""
    _check_kind(kind)
    if name not in _REGISTRY[kind]:
        raise LookupError(f"{kind} {name!r} 未注册；已注册：{_available(kind)}")
    del _REGISTRY[kind][name]
    entry = entry_name(kind, name)
    globals().pop(entry, None)
    exports = globals().get("__all__")
    if isinstance(exports, list) and entry in exports:
        exports.remove(entry)
    if _PLOT_MODULE is not None and hasattr(_PLOT_MODULE, entry):
        delattr(_PLOT_MODULE, entry)
        _forget_export(_PLOT_MODULE, entry)
    if _PLOT_CLASS is not None and entry in vars(_PLOT_CLASS):
        delattr(_PLOT_CLASS, entry)


def construct(kind: str, name: str, *args: Any, **kwargs: Any) -> Any:
    """按名字构造组件；入口函数与方法都在调用时走这里。"""
    _check_kind(kind)
    try:
        factory = _REGISTRY[kind][name]
    except KeyError:
        raise LookupError(f"{kind} {name!r} 未注册；已注册：{_available(kind)}") from None
    return factory(*args, **kwargs)


def _available(kind: str) -> str:
    names = _REGISTRY[kind]
    return ", ".join(names) if names else "（空）"


def _entry_point(kind: str, name: str) -> Callable[..., Any]:
    """模块级入口：`geom_point(...)`。名字固定，行为跟着注册表走。"""

    def entry(*args: Any, **kwargs: Any) -> Any:
        return construct(kind, name, *args, **kwargs)

    entry.__name__ = entry_name(kind, name)
    entry.__qualname__ = entry.__name__
    entry.__doc__ = f"构造 {entry_name(kind, name)}（注册表入口；等价于 p.{entry.__name__}(…)）"
    return entry


def _plot_method(kind: str, name: str) -> Callable[..., Any]:
    """`ggplot` 上的方法：`p.geom_point(...)` ≡ `p + geom_point(...)`。"""

    def method(self: Any, *args: Any, **kwargs: Any) -> Any:
        return self + construct(kind, name, *args, **kwargs)

    method.__name__ = entry_name(kind, name)
    method.__qualname__ = f"ggplot.{method.__name__}"
    method.__doc__ = f"`p + {method.__name__}(…)` 的别名（同一个注册表项）。"
    return method


def _refresh_entry(kind: str, name: str) -> None:
    entry = entry_name(kind, name)
    function = _entry_point(kind, name)
    globals()[entry] = function
    exports = globals().get("__all__")
    if isinstance(exports, list) and entry not in exports:
        exports.append(entry)
    if _PLOT_MODULE is not None:
        setattr(_PLOT_MODULE, entry, function)
        plot_exports = getattr(_PLOT_MODULE, "__all__", None)
        if isinstance(plot_exports, list) and entry not in plot_exports:
            plot_exports.append(entry)
    if _PLOT_CLASS is not None:
        setattr(_PLOT_CLASS, entry, _plot_method(kind, name))


def _forget_export(module: Any, entry: str) -> None:
    exports = getattr(module, "__all__", None)
    if isinstance(exports, list) and entry in exports:
        exports.remove(entry)


def bind_plot(cls: type[Any]) -> type[Any]:
    """把注册表里的每个组件绑成 `cls` 的方法（`ggcore.plot` 导入时调用一次）。

    同时记住 `cls` 所在的模块：之后新登记 / 撤销的名字会同步出现在
    `ggcore.plot` 的模块级函数里，仍然是「一条注册表，两个入口」。
    """
    global _PLOT_CLASS, _PLOT_MODULE
    _PLOT_CLASS = cls
    _PLOT_MODULE = sys.modules.get(getattr(cls, "__module__", ""))
    for kind in KINDS:
        for name in _REGISTRY[kind]:
            _refresh_entry(kind, name)
    return cls


# ---------------------------------------------------------------------------
# 默认登记（M1 要用的名字；本任务只保证「在册 + 返回带参数的占位对象」）
# ---------------------------------------------------------------------------

#: 9 个 geom。`default_aes` 照 ggplot2 4.0.3 的静态默认值，后续任务按需精修。
#:
#: **键顺序是契约**：上游 `Geom$use_defaults()` 按 `default_aes` 的顺序把缺失的
#: 列追加到图层数据末尾，所以这里保持与 4.0.3 的 `aes(...)` 书写顺序一致，
#: M1-3 的 `finish` 阶段才能与 R 的 `ggplot_build()$data` 逐列（含列序）对拍。
_BAR_DEFAULTS = {
    "colour": None,
    "fill": "grey35",
    "linewidth": 0.5,
    "linetype": 1,
    "alpha": None,
    "width": 0.9,
}
_LINE_DEFAULTS = {"colour": "black", "linewidth": 0.5, "linetype": 1, "alpha": None}

GEOM_SPECS: Mapping[str, GeomSpec] = MappingProxyType(
    {
        "point": GeomSpec(
            ("x", "y"),
            {
                "shape": 19.0,
                "colour": "black",
                "fill": None,
                "size": 1.5,
                "alpha": None,
                "stroke": 0.5,
            },
        ),
        "line": GeomSpec(("x", "y"), _LINE_DEFAULTS),
        "path": GeomSpec(("x", "y"), _LINE_DEFAULTS),
        "bar": GeomSpec(("x", "y"), _BAR_DEFAULTS, "count", "stack"),
        "col": GeomSpec(("x", "y"), _BAR_DEFAULTS, position="stack"),
        "area": GeomSpec(
            ("x", "y"),
            {
                "fill": "grey20",
                "colour": None,
                "linewidth": 0.5,
                "linetype": 1,
                "alpha": None,
            },
            "align",
            "stack",
        ),
        "histogram": GeomSpec(("x", "y"), _BAR_DEFAULTS, "bin", "stack"),
        "boxplot": GeomSpec(
            (
                "x|y",
                "lower|xlower",
                "upper|xupper",
                "middle|xmiddle",
                "ymin|xmin",
                "ymax|xmax",
            ),
            {
                "weight": 1.0,
                "colour": "grey20",
                "fill": "white",
                "size": 1.5,
                "alpha": None,
                "shape": 19.0,
                "linetype": 1,
                "linewidth": 0.5,
                "width": 0.9,
            },
            "boxplot",
            "dodge2",
        ),
        "smooth": GeomSpec(
            ("x", "y"),
            {
                "colour": "#3366FF",
                "fill": "grey60",
                "linewidth": 1,
                "linetype": 1,
                "alpha": 0.4,
                "weight": 1.0,
            },
            "smooth",
            "identity",
        ),
    }
)

#: 6 个 stat（M1-1 只登记名字；`align` 是 4.0.3 里 area 的默认 stat）。
STAT_NAMES: tuple[str, ...] = ("identity", "bin", "count", "boxplot", "smooth", "align")

#: `stat_*()` 的默认 geom（照 ggplot2：identity→point、count/bin→bar、align→area …）。
STAT_GEOMS: Mapping[str, str] = MappingProxyType(
    {
        "identity": "point",
        "bin": "bar",
        "count": "bar",
        "boxplot": "boxplot",
        "smooth": "smooth",
        "align": "area",
    }
)

#: 6 组 scale：position（x/y 连续与离散）+ colour / fill / size / shape / alpha。
SCALE_SPECS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("x_continuous", "x", {"type": "continuous"}),
    ("y_continuous", "y", {"type": "continuous"}),
    ("x_discrete", "x", {"type": "discrete"}),
    ("y_discrete", "y", {"type": "discrete"}),
    ("x_log10", "x", {"trans": "log10"}),
    ("y_log10", "y", {"trans": "log10"}),
    ("colour_continuous", "colour", {"type": "continuous"}),
    ("colour_discrete", "colour", {"type": "discrete"}),
    ("fill_continuous", "fill", {"type": "continuous"}),
    ("fill_discrete", "fill", {"type": "discrete"}),
    ("size_continuous", "size", {"type": "continuous"}),
    ("shape_discrete", "shape", {"type": "discrete"}),
    ("alpha_continuous", "alpha", {"type": "continuous"}),
)

THEME_NAMES: tuple[str, ...] = ("grey", "minimal", "void")
COORD_NAMES: tuple[str, ...] = ("cartesian", "fixed")
FACET_NAMES: tuple[str, ...] = ("null", "wrap", "grid")
GUIDE_NAMES: tuple[str, ...] = ("legend", "colourbar", "none")


def _geom_layer_factory(name: str, spec: GeomSpec) -> Callable[..., Layer]:
    """`geom_<name>(...)` → `Layer`（不画图）。

    参数路由（M1-3 的约定）：`**params` 只进 `Layer.params`，不往 stat 传。
    """

    def factory(
        mapping: Any = None,
        data: Any = None,
        *,
        stat: Stat | str | None = None,
        position: Position | str | None = None,
        inherit_aes: bool = True,
        show_legend: bool | None = None,
        **params: Any,
    ) -> Layer:
        return Layer(
            geom=Geom(name=name, required_aes=spec.required_aes, default_aes=spec.default_aes),
            stat=as_stat(stat, spec.stat),
            position=as_position(position, spec.position),
            mapping=as_aes(mapping),
            data=data,
            params=params,
            inherit_aes=inherit_aes,
            show_legend=show_legend,
        )

    return factory


def _stat_layer_factory(name: str) -> Callable[..., Layer]:
    """`stat_<name>(...)` 在 ggplot2 里同样是图层快捷方式。

    参数路由（M1-3 的约定）：`**params` 只进 `Stat.params`；geom 需要的参数
    （例如 `width`）不在这里，走 geom 的缺省值或 `geom=` 显式传入。
    """

    geom_name = STAT_GEOMS[name]
    spec = GEOM_SPECS[geom_name]

    def factory(
        mapping: Any = None,
        data: Any = None,
        *,
        geom: Geom | str | None = None,
        position: Position | str | None = None,
        inherit_aes: bool = True,
        show_legend: bool | None = None,
        **params: Any,
    ) -> Layer:
        return Layer(
            geom=as_geom(geom, geom_name, spec.required_aes, spec.default_aes),
            stat=Stat(name, params),
            position=as_position(position, spec.position),
            mapping=as_aes(mapping),
            data=data,
            inherit_aes=inherit_aes,
            show_legend=show_legend,
        )

    return factory


def _scale_factory(name: str, aesthetic: str, defaults: Mapping[str, Any]) -> Callable[..., Scale]:
    def factory(**params: Any) -> Scale:
        return Scale(name=name, aesthetic=aesthetic, params={**defaults, **params})

    return factory


def _coord_factory(name: str, defaults: Mapping[str, Any] | None = None) -> Callable[..., Coord]:
    def factory(**params: Any) -> Coord:
        return Coord(name=name, params={**(defaults or {}), **params})

    return factory


def _facet_factory(name: str) -> Callable[..., Facet]:
    def factory(facets: Any = None, **params: Any) -> Facet:
        if facets is not None:
            params = {"facets": facets, **params}
        return Facet(name=name, params=params)

    return factory


def _guide_factory(name: str) -> Callable[..., Guide]:
    def factory(aesthetic: str | None = None, **params: Any) -> Guide:
        return Guide(name=name, aesthetic=aesthetic, params=params)

    return factory


def _theme_factory(name: str) -> Callable[..., Theme]:
    def factory(**elements: Any) -> Theme:
        return Theme(name=name, elements=elements, complete=True)

    return factory


def _labels_factory(**values: Any) -> Labels:
    return Labels(frozen_mapping(values))


def register_geom(name: str, constructor: Callable[..., Any]) -> Callable[..., Any]:
    return register("geom", name, constructor)


def register_stat(name: str, constructor: Callable[..., Any]) -> Callable[..., Any]:
    return register("stat", name, constructor)


def register_scale(name: str, constructor: Callable[..., Any]) -> Callable[..., Any]:
    return register("scale", name, constructor)


def register_coord(name: str, constructor: Callable[..., Any]) -> Callable[..., Any]:
    return register("coord", name, constructor)


def register_facet(name: str, constructor: Callable[..., Any]) -> Callable[..., Any]:
    return register("facet", name, constructor)


def register_guide(name: str, constructor: Callable[..., Any]) -> Callable[..., Any]:
    return register("guide", name, constructor)


def register_theme(name: str, constructor: Callable[..., Any]) -> Callable[..., Any]:
    return register("theme", name, constructor)


def register_label(name: str, constructor: Callable[..., Any]) -> Callable[..., Any]:
    return register("label", name, constructor)


def _register_defaults() -> None:
    for name, spec in GEOM_SPECS.items():
        register_geom(name, _geom_layer_factory(name, spec))
    for name in STAT_NAMES:
        register_stat(name, _stat_layer_factory(name))
    for name, aesthetic, defaults in SCALE_SPECS:
        register_scale(name, _scale_factory(name, aesthetic, defaults))
    for name in COORD_NAMES:
        register_coord(name, _coord_factory(name, {"default": True} if name == "cartesian" else {}))
    for name in FACET_NAMES:
        register_facet(name, _facet_factory(name))
    for name in GUIDE_NAMES:
        register_guide(name, _guide_factory(name))
    for name in THEME_NAMES:
        register_theme(name, _theme_factory(name))
    register_label("labs", _labels_factory)


_register_defaults()

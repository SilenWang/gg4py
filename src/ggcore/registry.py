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

跨模块依赖只有 ggcore 自身（X1 白名单）：`aes` / `components` / `layer` /
`position` / `theme`。
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

import numpy as np

from ggcore.aes import as_aes, frozen_mapping
from ggcore.components import Coord, Facet, Guide, Labels, Scale, Theme
from ggcore.data import Column, ColumnTable
from ggcore.layer import Geom, Layer, Position, Stat, as_geom, as_position, as_stat
from ggcore.position import POSITION_FACTORIES, POSITION_NAMES
from ggcore.scale_specs import SCALE_SPECS as _SCALE_SPECS
from ggcore.theme import (
    theme_bw,
    theme_classic,
    theme_dark,
    theme_gray,
    theme_grey,
    theme_light,
    theme_linedraw,
    theme_minimal,
    theme_test,
    theme_void,
)

#: 组件种类，顺序即遍历顺序（不要改成 set）。`position` 紧跟 `stat`：
#: 它作用在 stat 之后、标度映射之前（就是流水线第 4 阶段）。
KINDS: tuple[str, ...] = (
    "geom",
    "stat",
    "position",
    "scale",
    "coord",
    "facet",
    "guide",
    "theme",
    "label",
)

#: 每种组件生成入口函数 / 方法时用的前缀。label 是 `labs()`，没有前缀。
PREFIXES: Mapping[str, str] = MappingProxyType(
    {
        "geom": "geom_",
        "stat": "stat_",
        "position": "position_",
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
    "POSITION_NAMES",
    "PREFIXES",
    "SCALE_SPECS",
    "STAT_GEOMS",
    "STAT_NAMES",
    "STAT_POSITIONS",
    "THEME_NAMES",
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
    "register_position",
    "register_scale",
    "register_stat",
    "register_theme",
    "registered",
    "required_aes_groups",
    "unregister",
]

#: 每个种类的有序注册表。用 dict 的插入序，保证遍历稳定。
_REGISTRY: dict[str, dict[str, Callable[..., Any]]] = {kind: {} for kind in KINDS}

#: 组件种类 → 扩展基类。`register_*()` 收到这些类的子类时，会把它包成
#: 两个入口都能用的构造器（geom / stat 包成图层工厂，其余包成组件实例）。
_BASES: Mapping[str, type[Any]] = MappingProxyType(
    {
        "geom": Geom,
        "stat": Stat,
        "position": Position,
        "scale": Scale,
        "coord": Coord,
        "facet": Facet,
        "guide": Guide,
        "theme": Theme,
    }
)

#: 内置名字的快照（`_register_defaults()` 之后填）。第三方登记同名组件默认
#: 被拒绝；显式 `allow_override=True` 才能替换，`unregister()` 会恢复原件。
_BUILTIN: dict[str, frozenset[str]] = {}
_ORIGINAL: dict[str, dict[str, Callable[..., Any]]] = {}

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
    #: `Geom$non_missing_aes`：`handle_na()` 也按这些列删缺失行（M1-7）。
    non_missing_aes: tuple[str, ...] = ()
    #: `Geom$optional_aes`：可以映射但不必需的美学（M1-7）。
    optional_aes: tuple[str, ...] = ()


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


def _sync_theme_names() -> None:
    """重算 `THEME_NAMES`：它是注册表的快照，不手写清单（SIL-671）。"""
    globals()["THEME_NAMES"] = registered("theme")


def register(
    kind: str,
    name: str,
    constructor: Callable[..., Any],
    *,
    allow_override: bool = False,
) -> Callable[..., Any]:
    """登记一个组件构造器，并（重新）生成两个入口。

    - 同名重复登记是替换，不是追加（顺序保持第一次出现的位置）；
    - 名字必须能拼出合法标识符，否则入口函数没法用属性/方法的方式暴露。
    - 内置名字默认不能被第三方覆盖（要替换必须显式 ``allow_override=True``）；
      被替换的内置项在 `unregister()` 时恢复原件。
    - 传进来的是组件基类的子类时，自动包成构造器：``Geom`` / ``Stat`` 包装成
      图层工厂，其余组件包装成组件实例。这样自定义组件只需要"实现一个类"。
    """
    _check_kind(kind)
    if not isinstance(name, str):
        raise TypeError(f"组件名必须是 str，得到 {type(name).__name__}")
    if not callable(constructor):
        raise TypeError(f"{entry_name(kind, name)} 的构造器必须可调用")
    if name in _BUILTIN.get(kind, frozenset()) and not allow_override:
        raise ValueError(
            f"{kind} {name!r} 是内置名字；第三方登记不能覆盖它"
            "（确实要替换时传 allow_override=True，unregister() 会恢复原件）"
        )
    entry = entry_name(kind, name)
    if not entry.isidentifier():
        raise ValueError(f"组件名 {name!r} 生成的入口 {entry!r} 不是合法标识符")
    _REGISTRY[kind][name] = _adapt_constructor(kind, name, constructor)
    _refresh_entry(kind, name)
    if kind == "theme":
        _sync_theme_names()
    return constructor


def unregister(kind: str, name: str) -> None:
    """撤销登记，并清掉两个入口（测试与后续任务的替换用）。

    内置名字如果被 `allow_override=True` 替换过，这里恢复原件而不是删除；
    内置组件本身不能注销（否则 `unregister("geom", "point")` 会永久破坏它）。
    """
    _check_kind(kind)
    if name not in _REGISTRY[kind]:
        raise LookupError(f"{kind} {name!r} 未注册；已注册：{_available(kind)}")
    if name in _BUILTIN.get(kind, frozenset()):
        original = _ORIGINAL[kind][name]
        if _REGISTRY[kind][name] is original:
            raise ValueError(f"{kind} {name!r} 是内置组件，不能注销")
        _REGISTRY[kind][name] = original
        _refresh_entry(kind, name)
        if kind == "theme":
            _sync_theme_names()
        return
    del _REGISTRY[kind][name]
    if kind == "theme":
        _sync_theme_names()
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


def _component_class(kind: str, constructor: Callable[..., Any]) -> type[Any] | None:
    """`constructor` 是某一类组件基类的子类时返回它，否则 None。"""
    base = _BASES.get(kind)
    if base is None or not isinstance(constructor, type):
        return None
    try:
        return constructor if issubclass(constructor, base) else None
    except TypeError:  # pragma: no cover - 非类的 callable 已在 register() 里排除
        return None


def _set_component_name(kind: str, name: str, cls: type[Any]) -> None:
    declared = cls.__dict__.get("name")
    if declared is None or not isinstance(declared, str) or not declared:
        cls.name = name  # type: ignore[attr-defined]
    elif declared != name:
        raise ValueError(
            f"register_{kind}({name!r}, {cls.__name__})：类里的 name={declared!r} 与登记名不一致"
        )


def _geom_from_name(name: str) -> Geom:
    """已注册的 geom 名 → 带契约的 `Geom` 实例（用于 stat 的缺省 geom）。"""
    spec = GEOM_SPECS.get(name)
    if spec is None:
        raise ValueError(f"geom {name!r} 没有静态契约，请传 Geom 实例（如 MyGeom()）")
    return Geom(
        name=name,
        required_aes=spec.required_aes,
        default_aes=spec.default_aes,
        non_missing_aes=spec.non_missing_aes,
        optional_aes=spec.optional_aes,
    )


def _geom_class_factory(name: str, cls: type[Geom]) -> Callable[..., Layer]:
    """`register_geom(name, MyGeom)` → 与内置 `geom_*()` 同形的图层工厂。"""

    _set_component_name("geom", name, cls)

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
        geom = cls()
        return Layer(
            geom=geom,
            stat=as_stat(stat, getattr(cls, "stat", "identity")),
            position=as_position(position, getattr(cls, "position", "identity")),
            mapping=as_aes(mapping),
            data=data,
            params=params,
            inherit_aes=inherit_aes,
            show_legend=show_legend,
        )

    return factory


def _stat_class_factory(name: str, cls: type[Stat]) -> Callable[..., Layer]:
    """`register_stat(name, MyStat)` → `stat_*()` 图层快捷方式。"""

    _set_component_name("stat", name, cls)
    default_geom = getattr(cls, "geom", "point")

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
        selected = geom if geom is not None else default_geom
        geom_object = selected if isinstance(selected, Geom) else _geom_from_name(str(selected))
        return Layer(
            geom=geom_object,
            stat=cls(params=params),
            position=as_position(position, getattr(cls, "position", "identity")),
            mapping=as_aes(mapping),
            data=data,
            inherit_aes=inherit_aes,
            show_legend=show_legend,
        )

    return factory


def _position_class_factory(name: str, cls: type[Position]) -> Callable[..., Position]:
    _set_component_name("position", name, cls)

    def factory(**params: Any) -> Position:
        return cls(params=params)

    return factory


def _scale_class_factory(name: str, cls: type[Scale]) -> Callable[..., Scale]:
    _set_component_name("scale", name, cls)
    declared_aesthetic = cls.__dict__.get("aesthetic", "")
    aesthetic = declared_aesthetic if isinstance(declared_aesthetic, str) else ""

    def factory(**params: Any) -> Scale:
        return cls(name=name, aesthetic=aesthetic, params=params)

    return factory


def _coord_class_factory(name: str, cls: type[Coord]) -> Callable[..., Coord]:
    _set_component_name("coord", name, cls)

    def factory(*args: Any, **params: Any) -> Coord:
        if args:
            raise TypeError(
                f"自定义 coord_{name}() 只接受关键字参数（规范见 docs/notes/extension.md）"
            )
        return cls(params=params)

    return factory


def _guide_class_factory(name: str, cls: type[Guide]) -> Callable[..., Guide]:
    _set_component_name("guide", name, cls)

    def factory(aesthetic: str | None = None, **params: Any) -> Guide:
        return cls(name=name, aesthetic=aesthetic, params=params)

    return factory


def _theme_class_factory(name: str, cls: type[Theme]) -> Callable[..., Theme]:
    _set_component_name("theme", name, cls)

    def factory(**params: Any) -> Theme:
        return cls(**params)

    return factory


def _adapt_constructor(kind: str, name: str, constructor: Callable[..., Any]) -> Callable[..., Any]:
    """把"组件类"包成构造器；普通 callable 原样返回（M1 的工厂路径不变）。"""
    cls = _component_class(kind, constructor)
    if cls is None:
        return constructor
    if kind == "geom":
        return _geom_class_factory(name, cls)
    if kind == "stat":
        return _stat_class_factory(name, cls)
    if kind == "position":
        return _position_class_factory(name, cls)
    if kind == "scale":
        return _scale_class_factory(name, cls)
    if kind == "coord":
        return _coord_class_factory(name, cls)
    if kind == "guide":
        return _guide_class_factory(name, cls)
    if kind == "theme":
        return _theme_class_factory(name, cls)
    # facet 等其余种类：统一按 `cls(params=...)` 构造。
    _set_component_name(kind, name, cls)
    return lambda **params: cls(params=params)


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
#: `geom_rect` / `polygon` / `ribbon` 一族：`colour = NA`、`fill = col_mix(ink, paper, 0.35)`
#: 在 theme_grey 下是 `grey35`；tile / raster / map 用 0.2 的混合（`grey20`）。
_RECT_DEFAULTS = {
    "colour": None,
    "fill": "grey35",
    "linewidth": 0.5,
    "linetype": 1,
    "alpha": None,
}

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
            non_missing_aes=("size", "shape", "colour"),
        ),
        "line": GeomSpec(
            ("x", "y"), _LINE_DEFAULTS, non_missing_aes=("linewidth", "colour", "linetype")
        ),
        "path": GeomSpec(
            ("x", "y"), _LINE_DEFAULTS, non_missing_aes=("linewidth", "colour", "linetype")
        ),
        "bar": GeomSpec(
            ("x", "y"),
            _BAR_DEFAULTS,
            "count",
            "stack",
            non_missing_aes=("xmin", "xmax", "ymin", "ymax"),
        ),
        "col": GeomSpec(
            ("x", "y"),
            _BAR_DEFAULTS,
            position="stack",
            non_missing_aes=("xmin", "xmax", "ymin", "ymax"),
        ),
        "area": GeomSpec(
            ("x", "y"),
            {
                "colour": None,
                "fill": "grey20",
                "linewidth": 0.5,
                "linetype": 1,
                "alpha": None,
            },
            "align",
            "stack",
        ),
        "histogram": GeomSpec(
            ("x", "y"),
            _BAR_DEFAULTS,
            "bin",
            "stack",
            non_missing_aes=("xmin", "xmax", "ymin", "ymax"),
        ),
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
                "linewidth": 1.0,
                "linetype": 1,
                "weight": 1.0,
                "alpha": 0.4,
            },
            "smooth",
            "identity",
            optional_aes=("ymin", "ymax"),
        ),
        # --- M2-S2 长尾 A：线段 / 矩形 / 区间 / 标注族 -----------------------
        # default_aes 的值是 theme_grey 解析后的静态结果（颜色写成语义名，
        # 绘制期按 col2rgb 折算；与上游 `from_theme(...)` 的取值一致）。
        "abline": GeomSpec(("slope", "intercept"), _LINE_DEFAULTS),
        "hline": GeomSpec(("yintercept",), _LINE_DEFAULTS),
        "vline": GeomSpec(("xintercept",), _LINE_DEFAULTS),
        "segment": GeomSpec(
            ("x", "y", "xend|yend"),
            _LINE_DEFAULTS,
            non_missing_aes=("linetype", "linewidth"),
        ),
        "curve": GeomSpec(
            ("x", "y", "xend|yend"),
            _LINE_DEFAULTS,
            non_missing_aes=("linetype", "linewidth"),
        ),
        "spoke": GeomSpec(
            ("x", "y", "angle", "radius"),
            _LINE_DEFAULTS,
            non_missing_aes=("linetype", "linewidth"),
        ),
        "rect": GeomSpec(
            ("x|width|xmin|xmax", "y|height|ymin|ymax"),
            _RECT_DEFAULTS,
        ),
        # `geom_tile` 的绘制由 SIL-737 落地。上游 `GeomTile$default_aes` 是
        # `fill = col_mix(ink, paper, 0.2)`（grey20）、`linewidth = 0.4 * borderwidth`
        # （0.2），与 M2-6 的 build-only 桩（SIL-735 口径、grey92）不同：绘制实现
        # 以本条为准，桩由它取代。
        "tile": GeomSpec(
            ("x", "y"),
            {
                "fill": "grey20",
                "colour": None,
                "linewidth": 0.2,
                "linetype": 1,
                "alpha": None,
                "width": 1.0,
                "height": 1.0,
            },
            non_missing_aes=("xmin", "xmax", "ymin", "ymax"),
        ),
        "raster": GeomSpec(
            ("x", "y"),
            {"fill": "grey20", "alpha": None},
            non_missing_aes=("fill", "xmin", "xmax", "ymin", "ymax"),
        ),
        "polygon": GeomSpec(("x", "y"), {**_RECT_DEFAULTS, "fill": "grey20"}),
        "ribbon": GeomSpec(
            ("x|y", "ymin|xmin", "ymax|xmax"),
            {**_RECT_DEFAULTS, "fill": "grey20"},
        ),
        "step": GeomSpec(
            ("x", "y"),
            _LINE_DEFAULTS,
            non_missing_aes=("linewidth", "colour", "linetype"),
        ),
        "errorbar": GeomSpec(
            ("x|y", "ymin|xmin", "ymax|xmax"),
            {
                "colour": "black",
                "linewidth": 0.5,
                "linetype": 1,
                "width": 0.9,
                "alpha": None,
            },
        ),
        "errorbarh": GeomSpec(
            ("x|y", "ymin|xmin", "ymax|xmax"),
            {
                "colour": "black",
                "linewidth": 0.5,
                "linetype": 1,
                "width": 0.9,
                "alpha": None,
            },
        ),
        "linerange": GeomSpec(("x|y", "ymin|xmin", "ymax|xmax"), _LINE_DEFAULTS),
        "pointrange": GeomSpec(
            ("x", "y", "ymin|xmin", "ymax|xmax"),
            {
                "colour": "black",
                "size": 0.5,
                "linewidth": 0.5,
                "linetype": 1,
                "shape": 19.0,
                "fill": None,
                "alpha": None,
                "stroke": 1.0,
            },
        ),
        "crossbar": GeomSpec(
            ("x", "y", "ymin|xmin", "ymax|xmax"),
            {"colour": "black", "fill": None, "linewidth": 0.5, "linetype": 1, "alpha": None},
        ),
        "blank": GeomSpec((), {}),
        "rug": GeomSpec((), _LINE_DEFAULTS),
        "map": GeomSpec(("map_id",), {**_RECT_DEFAULTS, "fill": "grey20"}),
        # -- M2-7 长尾 B：文本 / 点 / 分布 / 2D 族 ---------------------------------
        # 默认美学照 4.0.3 的 `from_theme(...)`：`theme_grey()$geom` 解析后
        # ink = black、paper = white、accent = #3366FF、fontsize = 3.87mm；
        # `col_mix(ink, paper, 0.2 / 0.35 / 0.5)` = grey20 / grey35 / #808080。
        "text": GeomSpec(
            ("x", "y", "label"),
            {
                "colour": "black",
                "family": "",
                "size": 3.87,
                "angle": 0.0,
                "hjust": 0.5,
                "vjust": 0.5,
                "alpha": None,
                "fontface": 1,
                "lineheight": 1.2,
            },
            "identity",
            "nudge",
            non_missing_aes=("angle",),
        ),
        "label": GeomSpec(
            ("x", "y", "label"),
            {
                "colour": "black",
                "fill": "white",
                "family": "",
                "size": 3.87,
                "angle": 0.0,
                "hjust": 0.5,
                "vjust": 0.5,
                "alpha": None,
                "fontface": 1,
                "lineheight": 1.2,
                "linewidth": 0.25,
                "linetype": 1,
            },
            "identity",
            "nudge",
        ),
        "jitter": GeomSpec(
            ("x", "y"),
            {
                "shape": 19.0,
                "colour": "black",
                "fill": None,
                "size": 1.5,
                "alpha": None,
                "stroke": 0.5,
            },
            "identity",
            "jitter",
            non_missing_aes=("size", "shape", "colour"),
        ),
        "count": GeomSpec(
            ("x", "y"),
            {
                "shape": 19.0,
                "colour": "black",
                "fill": None,
                "size": 1.5,
                "alpha": None,
                "stroke": 0.5,
            },
            "sum",
            non_missing_aes=("size", "shape", "colour"),
        ),
        "bin2d": GeomSpec(
            ("x", "y"),
            {
                "fill": "#333333",
                "colour": None,
                "linewidth": 0.2,
                "linetype": 1,
                "alpha": None,
                "width": 1.0,
                "height": 1.0,
            },
            "bin2d",
            non_missing_aes=("xmin", "xmax", "ymin", "ymax"),
        ),
        "bin_2d": GeomSpec(
            ("x", "y"),
            {
                "fill": "#333333",
                "colour": None,
                "linewidth": 0.2,
                "linetype": 1,
                "alpha": None,
                "width": 1.0,
                "height": 1.0,
            },
            "bin2d",
            non_missing_aes=("xmin", "xmax", "ymin", "ymax"),
        ),
        "hex": GeomSpec(
            ("x", "y"),
            {
                "colour": None,
                "fill": "#808080",
                "linewidth": 0.5,
                "linetype": 1,
                "alpha": None,
            },
            "binhex",
        ),
        "density": GeomSpec(
            ("x", "y"),
            {
                "colour": "black",
                "fill": None,
                "weight": 1.0,
                "alpha": None,
                "linewidth": 0.5,
                "linetype": 1,
            },
            "density",
        ),
        "density_2d": GeomSpec(
            ("x", "y"),
            {
                "colour": "#3366FF",
                "linewidth": 0.5,
                "linetype": 1,
                "alpha": None,
            },
            "density_2d",
            non_missing_aes=("linewidth", "colour", "linetype"),
        ),
        "density2d": GeomSpec(
            ("x", "y"),
            {
                "colour": "#3366FF",
                "linewidth": 0.5,
                "linetype": 1,
                "alpha": None,
            },
            "density_2d",
            non_missing_aes=("linewidth", "colour", "linetype"),
        ),
        "density_2d_filled": GeomSpec(
            ("x", "y"),
            {
                "colour": None,
                "fill": "#333333",
                "linewidth": 0.5,
                "linetype": 1,
                "alpha": None,
            },
            "density_2d_filled",
        ),
        "density2d_filled": GeomSpec(
            ("x", "y"),
            {
                "colour": None,
                "fill": "#333333",
                "linewidth": 0.5,
                "linetype": 1,
                "alpha": None,
            },
            "density_2d_filled",
        ),
        "contour": GeomSpec(
            ("x", "y"),
            {
                "weight": 1.0,
                "colour": "#3366FF",
                "linewidth": 0.5,
                "linetype": 1,
                "alpha": None,
            },
            "contour",
            non_missing_aes=("linewidth", "colour", "linetype"),
        ),
        "contour_filled": GeomSpec(
            ("x", "y"),
            {
                "colour": None,
                "fill": "#333333",
                "linewidth": 0.5,
                "linetype": 1,
                "alpha": None,
            },
            "contour_filled",
        ),
        "dotplot": GeomSpec(
            ("x", "y"),
            {
                "colour": "black",
                "fill": "black",
                "alpha": None,
                "stroke": 1.0,
                "linetype": 1,
                "weight": 1.0,
                "width": 0.9,
            },
            "bindot",
            non_missing_aes=("size", "shape"),
        ),
        "violin": GeomSpec(
            ("x", "y"),
            {
                "weight": 1.0,
                "colour": "#333333",
                "fill": "white",
                "linewidth": 0.5,
                "linetype": 1,
                "alpha": None,
                "width": 0.9,
            },
            "ydensity",
            "dodge",
        ),
        "qq": GeomSpec(
            ("x", "y"),
            {
                "shape": 19.0,
                "colour": "black",
                "fill": None,
                "size": 1.5,
                "alpha": None,
                "stroke": 0.5,
            },
            "qq",
            non_missing_aes=("size", "shape", "colour"),
        ),
        "qq_line": GeomSpec(
            ("x", "y"),
            {"colour": "black", "linewidth": 0.5, "linetype": 1, "alpha": None},
            "qq_line",
            non_missing_aes=("linewidth", "colour", "linetype"),
        ),
        "quantile": GeomSpec(
            ("x", "y"),
            {
                "weight": 1.0,
                "colour": "#3366FF",
                "linewidth": 0.5,
                "linetype": 1,
                "alpha": None,
            },
            "quantile",
            non_missing_aes=("linewidth", "colour", "linetype"),
        ),
        "function": GeomSpec(
            ("x", "y"),
            {"colour": "black", "linewidth": 0.5, "linetype": 1, "alpha": None},
            "function",
            non_missing_aes=("linewidth", "colour", "linetype"),
        ),
    }
)

#: 6 个 stat（M1-1 只登记名字；`align` 是 4.0.3 里 area 的默认 stat）。
STAT_NAMES: tuple[str, ...] = (
    "identity",
    "bin",
    "count",
    "boxplot",
    "smooth",
    "align",
    "bin_2d",
    "bin_hex",
    "summary_2d",
    "summary_hex",
    "contour",
    "contour_filled",
    "density_2d",
    "density_2d_filled",
    "bin2d",
    "binhex",
    "summary2d",
    "density2d",
    "qq",
    "qq_line",
    "ecdf",
    "ellipse",
    "quantile",
    "summary",
    "summary_bin",
    "sum",
    "unique",
    "density",
    "function",
    "connect",
    "manual",
    "spoke",
    "ydensity",
    "bin2d",
    "binhex",
    "summary2d",
    "density2d",
)

#: 2D 族的旧别名 → 正名。
STAT_ALIASES: Mapping[str, str] = MappingProxyType(
    {
        "bin2d": "bin_2d",
        "binhex": "bin_hex",
        "summary2d": "summary_2d",
        "density2d": "density_2d",
    }
)

#: `stat_*()` 的默认 geom（照 4.0.3 的 `stat_*` 构造器；`spoke` 已 `deprecate_stop`，
#: 不给默认 geom）。
STAT_GEOMS: Mapping[str, str] = MappingProxyType(
    {
        "identity": "point",
        "bin": "bar",
        "count": "bar",
        "boxplot": "boxplot",
        "smooth": "smooth",
        "align": "area",
        "bin_2d": "tile",
        "bin_hex": "hex",
        "summary_2d": "tile",
        "summary_hex": "hex",
        "contour": "contour",
        "contour_filled": "contour_filled",
        "density_2d": "density_2d",
        "density_2d_filled": "density_2d_filled",
        "qq": "point",
        "qq_line": "abline",
        "ecdf": "step",
        "ellipse": "path",
        "quantile": "quantile",
        "summary": "pointrange",
        "summary_bin": "pointrange",
        "sum": "point",
        "unique": "point",
        "density": "area",
        "function": "function",
        "connect": "path",
        "manual": "point",
        "ydensity": "violin",
    }
)

#: `stat_*()` 的默认 position（照 4.0.3 各构造器的形参缺省；统计层自己决定，
#: 不跟 geom 走——例如 `stat_density(geom="line")` 仍是 stack）。
STAT_POSITIONS: Mapping[str, str] = MappingProxyType(
    {
        "identity": "identity",
        "bin": "stack",
        "count": "stack",
        "boxplot": "identity",
        "smooth": "identity",
        "align": "stack",
        "qq": "identity",
        "qq_line": "identity",
        "ecdf": "identity",
        "ellipse": "identity",
        "quantile": "identity",
        "summary": "identity",
        "summary_bin": "identity",
        "sum": "identity",
        "unique": "identity",
        "density": "stack",
        "function": "identity",
        "connect": "identity",
        "manual": "identity",
        "spoke": "identity",
        "ydensity": "dodge",
    }
)

#: 6 组 scale：position（x/y 连续与离散）+ colour / fill / size / shape / alpha。
#: M2-4 A 段起，名字与默认值由 `ggcore.scale_specs` 的声明表提供：NAMESPACE 的
#: 131 个 `scale_*` 导出分两段登记（A 段连续侧 70 个、B 段离散/色板 61 个）。
#: 这里只是同名导出，注册表的遍历顺序 = 表的顺序。
SCALE_SPECS: tuple[tuple[str, str, dict[str, Any]], ...] = _SCALE_SPECS

#: M2-1：覆盖 4.0.3 NAMESPACE 的全部 coord_* 导出。`trans` 与 `transform` 是
#: 同一实现的两个入口（`coord_trans()` 在 4.0.3 被 `coord_transform()` 取代，
#: 仍然导出）；参数语义在 `ggcore.coord`。
COORD_NAMES: tuple[str, ...] = (
    "cartesian",
    "fixed",
    "equal",
    "flip",
    "trans",
    "transform",
    "polar",
    "radial",
    "sf",
    "map",
    "quickmap",
)

#: 每个 coord 的**位置参数**顺序（照 ggplot2 4.0.3 的函数签名）。
#: 构造器统一收 `*args, **params`，所以 `coord_polar("y")` 与
#: `coord_polar(theta="y")` 落到同一个 `Coord` 组件上。
COORD_POSITIONAL: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "cartesian": ("xlim", "ylim", "expand", "default", "clip", "reverse", "ratio"),
        "fixed": ("ratio",),
        "equal": ("ratio",),
        "flip": ("xlim", "ylim", "expand", "default", "clip", "reverse", "ratio"),
        "trans": ("x", "y", "xlim", "ylim", "expand", "reverse", "clip"),
        "transform": ("x", "y", "xlim", "ylim", "expand", "reverse", "clip"),
        "polar": ("theta", "start", "direction", "clip"),
        "radial": (
            "theta",
            "start",
            "end",
            "thetalim",
            "rlim",
            "expand",
            "direction",
            "clip",
            "r.axis.inside",
            "rotate.angle",
            "inner.radius",
            "reverse",
        ),
        "sf": (
            "xlim",
            "ylim",
            "expand",
            "crs",
            "default_crs",
            "datum",
            "label_graticule",
            "label_axes",
            "lims_method",
            "ndiscr",
            "default",
            "clip",
            "reverse",
        ),
        "map": ("projection",),
        "quickmap": ("xlim", "ylim", "expand", "clip"),
    }
)

FACET_NAMES: tuple[str, ...] = ("null", "wrap", "grid")
GUIDE_NAMES: tuple[str, ...] = (
    "legend",
    "colourbar",
    "bins",
    "coloursteps",
    "colorsteps",
    "none",
    # 轴 guide（M2-S2）：`guides(x = guide_axis(angle = 45))` 的注册名。
    "axis",
    "axis_logticks",
    "axis_stack",
    "axis_theta",
    # SIL-745：NAMESPACE 里还有两个构造器没登记 —— `guide_colorbar`（
    # `guide_colourbar` 的别名）与 `guide_custom()`（任意 grob 进图例盒）。
    # `guide_from_component()` 早就认这两个名字，只是注册表漏了。
    "colorbar",
    "custom",
)


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
        if name == "jitter" and ("width" in params or "height" in params):
            # `geom_jitter(width=, height=)` 是 `position_jitter(width=, height=)`
            # 的简写；两者同时给是上游的显式错误。
            if position is not None:
                raise ValueError(
                    "geom_jitter() 的 position 与 width/height 不能同时给：选一种方式指定抖动"
                )
            position = POSITION_FACTORIES["jitter"](
                width=params.pop("width", None), height=params.pop("height", None)
            )
        resolved_position = as_position(position, spec.position)
        if name == "boxplot":
            resolved_position = _boxplot_position(resolved_position, position, params)
        return Layer(
            geom=Geom(
                name=name,
                required_aes=spec.required_aes,
                default_aes=spec.default_aes,
                non_missing_aes=spec.non_missing_aes,
                optional_aes=spec.optional_aes,
            ),
            stat=as_stat(stat, spec.stat),
            position=resolved_position,
            mapping=as_aes(mapping),
            data=data,
            params=params,
            inherit_aes=inherit_aes,
            show_legend=show_legend,
        )

    return factory


def _boxplot_position(
    resolved: Position, raw: Position | str | None, params: Mapping[str, Any]
) -> Position:
    """上游 `geom_boxplot()` 的 `varwidth` 规则（`R/geom-boxplot.R:162`）。

    `varwidth = TRUE` 与 `preserve = "total"` 不兼容：

    - `position` 是名字 / 缺省 → 换成 `position_dodge2(preserve = "single")`；
    - `position` 是显式对象且 `preserve = "total"` → 警告后改成 `"single"`。

    对位置层本身没有新语义（`preserve` 早已实现），但**组合**要靠这一条才能与
    R 对齐：箱宽按 `relvarwidth` 变化时，`total` 会把每个箱压成 `width / n`。
    """
    if not bool(params.get("varwidth", False)):
        return resolved
    if raw is None or isinstance(raw, str):
        return construct("position", "dodge2", preserve="single")
    if isinstance(raw, Position) and raw.name == "dodge2":
        if raw.params.get("preserve", "total") == "single":
            return resolved
        import warnings

        warnings.warn(
            "Can't preserve total widths when varwidth = TRUE.",
            RuntimeWarning,
            stacklevel=3,
        )
        return replace(raw, params={**raw.params, "preserve": "single"})
    return resolved


#: 参考线三兄弟的「参数即数据」工厂（上游 `geom_abline()` / `geom_hline()` /
#: `geom_vline()`）：给了截距参数时，它们把参数**做成图层数据**、映射指向同名列、
#: `inherit.aes = FALSE`、`show.legend = FALSE`——所以 `$data` 的列序是
#: `intercept, slope, PANEL, group, colour, …`，继承来的美学一律不进这一层。
_REFERENCE_DATA_AES: Mapping[str, tuple[tuple[str, float], ...]] = MappingProxyType(
    {
        "abline": (("intercept", 0.0), ("slope", 1.0)),
        "hline": (("yintercept", 0.0),),
        "vline": (("xintercept", 0.0),),
    }
)


def _float_sequence(value: Any) -> list[float]:
    """`slope = c(1, -1)` 这种向量参数：摊平成 float 列表（R 会按最长的一条回收）。"""
    if isinstance(value, (list, tuple, np.ndarray)):
        values = [float(item) for item in np.asarray(value, dtype=np.float64).ravel()]
        if not values:
            raise ValueError("geom_abline() 的 slope / intercept 不能是空序列")
        return values
    return [float(value)]


def _reference_layer_factory(
    name: str, spec: GeomSpec, defaults: tuple[tuple[str, float], ...]
) -> Callable[..., Layer]:
    """`geom_abline()` / `geom_hline()` / `geom_vline()` 的参数形态。

    给了截距参数：参数落成图层数据（`data_frame0(...)` 的等价物）并按同名映射，
    `inherit.aes = False`。没给：退回普通图层（允许 `mapping=aes(yintercept=...)`）。
    """
    generic = _geom_layer_factory(name, spec)

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
        given = [key for key, _ in defaults if params.get(key) is not None]
        if not given:
            return generic(
                mapping,
                data,
                stat=stat,
                position=position,
                inherit_aes=inherit_aes,
                show_legend=show_legend,
                **params,
            )
        sequences: list[tuple[str, list[float]]] = []
        for key, fallback in defaults:
            value = params.pop(key, None)
            sequences.append((key, [fallback] if value is None else _float_sequence(value)))
        nrows = max(len(values) for _, values in sequences)
        table = ColumnTable(
            [
                (
                    key,
                    Column(
                        "float",
                        np.array([values[index % len(values)] for index in range(nrows)]),
                    ),
                )
                for key, values in sequences
            ],
            nrows=nrows,
        )
        layer = Layer(
            geom=Geom(
                name=name,
                required_aes=spec.required_aes,
                default_aes=spec.default_aes,
                non_missing_aes=spec.non_missing_aes,
                optional_aes=spec.optional_aes,
            ),
            stat=as_stat(stat, spec.stat),
            position=as_position(position, spec.position),
            mapping=as_aes({key: key for key, _ in defaults}),
            data=table,
            params=params,
            inherit_aes=False,
            show_legend=False if show_legend is None else show_legend,
        )
        return layer

    return factory


def _stat_layer_factory(name: str) -> Callable[..., Layer]:
    """`stat_<name>(...)` 在 ggplot2 里同样是图层快捷方式。

    参数路由（M1-3 的约定）：`**params` 只进 `Stat.params`；geom 需要的参数
    （例如 `width`）不在这里，走 geom 的缺省值或 `geom=` 显式传入。
    别名（`stat_bin2d` 等）在图层里落成正名，默认 geom 与正名一致。

    4.0.3 里有几个 stat 的默认 geom 属于 M2-7（`step` / `violin` / `pointrange` /
    `quantile` / `function` / `abline`）。那一组落地之前，用这些默认值的
    `stat_*()` 在**构造时**报错并点名可用的 `geom=`，不拖到构建期才炸。
    """

    stat_name = STAT_ALIASES.get(name, name)
    geom_name = STAT_GEOMS.get(stat_name, "point")

    if stat_name == "spoke":
        # 4.0.3 的 `stat_spoke()` 本体是 `lifecycle::deprecate_stop()`：
        # 注册项保留（NAMESPACE 里仍然导出），调用即报错并指向 `geom_spoke()`。
        def deprecated(*args: Any, **params: Any) -> Layer:
            del args, params
            raise ValueError(
                "stat_spoke() 在 ggplot2 4.0.3 里已弃用（lifecycle::deprecate_stop），"
                "请改用 geom_spoke()（角度 / 半径是 geom 的参数，M2-7）"
            )

        return deprecated

    def _geom_spec(target: str) -> GeomSpec:
        spec = GEOM_SPECS.get(target)
        if spec is None:
            raise ValueError(
                f"stat_{name} 的 geom {target!r} 还没实现（M2-7 的另一组）；"
                f"先显式给 geom= 一个已注册的几何：{', '.join(GEOM_SPECS)}"
            )
        return spec

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
        if isinstance(geom, str):
            spec = _geom_spec(geom)
        elif geom is None:
            spec = _geom_spec(geom_name)
        else:
            spec = None
        return Layer(
            geom=as_geom(
                geom,
                geom_name,
                () if spec is None else spec.required_aes,
                {} if spec is None else spec.default_aes,
                () if spec is None else spec.non_missing_aes,
                () if spec is None else spec.optional_aes,
            ),
            stat=Stat(stat_name, params),
            # `STAT_POSITIONS` 是 M2-6 长尾 stat 的缺省表；2D 族沿用各自 geom
            # 的缺省 position（`GEOM_SPECS[...]`，M2-6 的另一半登记在那里）。
            position=as_position(
                position,
                STAT_POSITIONS.get(stat_name) or ("identity" if spec is None else spec.position),
            ),
            mapping=as_aes(mapping),
            data=data,
            inherit_aes=inherit_aes,
            show_legend=show_legend,
        )

    return factory


#: `scale_discrete_manual()` / `scale_discrete_identity()` / `scale_continuous_identity()`
#: 是**跨美学**的通用标度：美学由调用方的 `aesthetics =` 给（上游也没有缺省）。
_GENERIC_SCALE_NAMES = frozenset({"discrete_manual", "discrete_identity", "continuous_identity"})


def _scale_factory(name: str, aesthetic: str, defaults: Mapping[str, Any]) -> Callable[..., Scale]:
    def factory(**params: Any) -> Scale:
        # 未实现的标度参数 / R 里直接 abort 的名字在**构造时**就点名报错：
        # `p + scale_x_continuous(sec.axis=…)` 与 `p.scale_x_continuous(sec.axis=…)`
        # 走的是同一个工厂，两条路径一致。
        from ggcore.scales import (
            reject_unimplemented_scale_params,
            reject_unsupported_scale,
        )

        merged = {**defaults, **params}
        reject_unimplemented_scale_params(name, merged)
        reject_unsupported_scale(name)
        chosen: Any = aesthetic
        if name in _GENERIC_SCALE_NAMES:
            if "aesthetics" not in merged:
                raise ValueError(f"scale_{name}() 必须给 aesthetics = ...（上游同样没有缺省）")
            chosen = merged["aesthetics"]
        if isinstance(chosen, (list, tuple, set, frozenset)):
            items = list(chosen)
            if len(items) != 1:
                raise ValueError(
                    f"scale_{name}(aesthetics = ...) 一次只支持一个美学，收到 {chosen!r}"
                )
            chosen = items[0]
        return Scale(name=name, aesthetic=str(chosen), params=merged)

    return factory


def _coord_factory(name: str, defaults: Mapping[str, Any] | None = None) -> Callable[..., Coord]:
    """`coord_<name>(...)` → `Coord` 组件（只收集参数，语义在 `ggcore.coord`）。

    位置参数按 :data:`COORD_POSITIONAL` 的名字落位（`coord_polar("y")`、
    `coord_fixed(2)`、`coord_transform("log10")` 都能用），其余走 `**params`；
    参数名是否认识由 `ggcore.coord.coord_from_component()` 在构建期统一校验。
    """
    positional = COORD_POSITIONAL.get(name, ())

    def factory(*args: Any, **params: Any) -> Coord:
        if len(args) > len(positional):
            raise TypeError(
                f"coord_{name}() 最多接受 {len(positional)} 个位置参数"
                f"（{', '.join(positional)}），收到 {len(args)} 个"
            )
        bound = dict(zip(positional, args, strict=False))
        overlap = set(bound) & set(params)
        if overlap:
            raise TypeError(
                f"coord_{name}() 的参数重复给了位置与关键字：{', '.join(sorted(overlap))}"
            )
        return Coord(name=name, params={**(defaults or {}), **bound, **params})

    return factory


def _facet_factory(name: str) -> Callable[..., Facet]:
    """`facet_null()` / `facet_wrap(facets, ...)` / `facet_grid(rows, cols, ...)`。

    只做参数收集（M1-6 起语义在 `ggcore.facet`）；签名照上游，`facet_wrap`
    的第一个位置参数是分面变量，`facet_grid` 前两个是行 / 列变量。
    """

    if name == "grid":

        def grid_factory(
            rows: Any = None,
            cols: Any = None,
            **params: Any,
        ) -> Facet:
            return Facet(name=name, params={"rows": rows, "cols": cols, **params})

        return grid_factory

    if name == "wrap":

        def wrap_factory(facets: Any = None, **params: Any) -> Facet:
            return Facet(name=name, params={"facets": facets, **params})

        return wrap_factory

    def null_factory(**params: Any) -> Facet:
        return Facet(name=name, params=params)

    return null_factory


def _guide_factory(name: str) -> Callable[..., Guide]:
    def factory(aesthetic: str | None = None, **params: Any) -> Guide:
        return Guide(name=name, aesthetic=aesthetic, params=params)

    return factory


def _labels_factory(**values: Any) -> Labels:
    return Labels(frozen_mapping(values))


def register_geom(
    name: str, constructor: Callable[..., Any], *, allow_override: bool = False
) -> Callable[..., Any]:
    return register("geom", name, constructor, allow_override=allow_override)


def register_stat(
    name: str, constructor: Callable[..., Any], *, allow_override: bool = False
) -> Callable[..., Any]:
    return register("stat", name, constructor, allow_override=allow_override)


def register_position(
    name: str, constructor: Callable[..., Any], *, allow_override: bool = False
) -> Callable[..., Any]:
    return register("position", name, constructor, allow_override=allow_override)


def register_scale(
    name: str, constructor: Callable[..., Any], *, allow_override: bool = False
) -> Callable[..., Any]:
    return register("scale", name, constructor, allow_override=allow_override)


def register_coord(
    name: str, constructor: Callable[..., Any], *, allow_override: bool = False
) -> Callable[..., Any]:
    return register("coord", name, constructor, allow_override=allow_override)


def register_facet(
    name: str, constructor: Callable[..., Any], *, allow_override: bool = False
) -> Callable[..., Any]:
    return register("facet", name, constructor, allow_override=allow_override)


def register_guide(
    name: str, constructor: Callable[..., Any], *, allow_override: bool = False
) -> Callable[..., Any]:
    return register("guide", name, constructor, allow_override=allow_override)


def register_theme(
    name: str, constructor: Callable[..., Any], *, allow_override: bool = False
) -> Callable[..., Any]:
    return register("theme", name, constructor, allow_override=allow_override)


def register_label(
    name: str, constructor: Callable[..., Any], *, allow_override: bool = False
) -> Callable[..., Any]:
    return register("label", name, constructor, allow_override=allow_override)


def _register_defaults() -> None:
    for name, spec in GEOM_SPECS.items():
        defaults = _REFERENCE_DATA_AES.get(name)
        if defaults is None:
            register_geom(name, _geom_layer_factory(name, spec))
        else:
            register_geom(name, _reference_layer_factory(name, spec, defaults))
    for name in STAT_NAMES:
        register_stat(name, _stat_layer_factory(name))
    for name in POSITION_NAMES:
        register_position(name, POSITION_FACTORIES[name])
    for name, aesthetic, defaults in SCALE_SPECS:
        register_scale(name, _scale_factory(name, aesthetic, defaults))
    for name in COORD_NAMES:
        # M1-5 起 coord 的参数就是用户传入的那份；不再塞 `default` 占位。
        register_coord(name, _coord_factory(name))
    for name in FACET_NAMES:
        register_facet(name, _facet_factory(name))
    for name in GUIDE_NAMES:
        register_guide(name, _guide_factory(name))
    # 9 套完整主题（`gray` 是 `grey` 的美式拼写别名，上游两个都导出）。
    register_theme("grey", theme_grey)
    register_theme("gray", theme_gray)
    register_theme("bw", theme_bw)
    register_theme("classic", theme_classic)
    register_theme("light", theme_light)
    register_theme("dark", theme_dark)
    register_theme("linedraw", theme_linedraw)
    register_theme("minimal", theme_minimal)
    register_theme("test", theme_test)
    register_theme("void", theme_void)
    register_label("labs", _labels_factory)


_register_defaults()

#: 内置名单快照：第三方 `register_*()` 默认不能覆盖这些名字。
for _kind in KINDS:
    _BUILTIN[_kind] = frozenset(_REGISTRY[_kind])
    _ORIGINAL[_kind] = dict(_REGISTRY[_kind])

#: 已登记的主题名（按登记顺序）。由注册表派生：`register_theme()` /
#: `unregister()` 会同步刷新，避免像 SIL-671 之前那样手写清单漏掉 `bw`。
THEME_NAMES: tuple[str, ...] = registered("theme")

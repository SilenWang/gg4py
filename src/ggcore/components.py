"""`+` 可组合的非图层组件：scale / theme / coord / facet / guide / labels。

M1-1 只给它们**占位结构**：名字 + 参数（+ theme 的完整/局部标记）。构造器由
`ggcore.registry` 注册并生成（`scale_x_log10()`、`theme_grey()`、
`coord_fixed()` …），真正的语义在后续任务里补：

- scale → M1-4
- coord → M1-5
- facet → M1-6
- theme → M1-10
- guide → M1-11

所有对象不可变，`p + …` 的克隆可直接共享。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MemberDescriptorType
from typing import Any

from ggcore.aes import frozen_mapping

__all__ = ["Coord", "Facet", "Guide", "Labels", "Scale", "Theme"]

_MISSING = object()


def _declared_attr(obj: Any, name: str, base: type[Any]) -> Any:
    """在 `base` 的子类上找用户显式写的类属性（跳过 slots 描述符）。"""
    for cls in type(obj).__mro__:
        if cls is base:
            return _MISSING
        if name in cls.__dict__:
            value = cls.__dict__[name]
            if isinstance(value, MemberDescriptorType):
                continue
            return value
    return _MISSING


def _apply_declared(obj: Any, base: type[Any], *names: str) -> None:
    for name in names:
        value = _declared_attr(obj, name, base)
        if value is not _MISSING:
            object.__setattr__(obj, name, value)


@dataclass(frozen=True, slots=True)
class Scale:
    """一个标度：注册名 + 作用的 aes + 参数。

    `key` 是 `p.scales` 的键（按美学名去重，后加的替换先加的），与 ggplot2
    「同一美学只有一个位置标度」的口径一致。
    """

    name: str
    aesthetic: str
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _apply_declared(self, Scale, "name", "aesthetic")
        defaults = _declared_attr(self, "params", Scale)
        if defaults is not _MISSING and isinstance(defaults, Mapping):
            object.__setattr__(self, "params", {**defaults, **self.params})
        object.__setattr__(self, "params", frozen_mapping(self.params))

    @property
    def key(self) -> str:
        return self.aesthetic

    def build_scale(self) -> Any:
        """扩展点：子类覆写后返回 :class:`ggcore.scales.ScaleBase` 实例。"""
        raise NotImplementedError(
            f"scale_{self.name} 没有 build_scale()（自定义 Scale 子类需要覆写它）"
        )


@dataclass(frozen=True, slots=True)
class Coord:
    """坐标系占位（`cartesian` / `fixed`）。"""

    name: str = "cartesian"
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _apply_declared(self, Coord, "name")
        defaults = _declared_attr(self, "params", Coord)
        if defaults is not _MISSING and isinstance(defaults, Mapping):
            object.__setattr__(self, "params", {**defaults, **self.params})
        object.__setattr__(self, "params", frozen_mapping(self.params))

    def build_coord(self) -> Any:
        """扩展点：子类覆写后返回 :class:`ggcore.coord.CoordBase` 实例。"""
        raise NotImplementedError(
            f"coord_{self.name} 没有 build_coord()（自定义 Coord 子类需要覆写它）"
        )


@dataclass(frozen=True, slots=True)
class Facet:
    """分面占位（`null` / `wrap` / `grid`）。"""

    name: str = "null"
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", frozen_mapping(self.params))


@dataclass(frozen=True, slots=True)
class Guide:
    """图例占位；`aesthetic=None` 表示由后续任务决定作用对象。"""

    name: str
    aesthetic: str | None = None
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _apply_declared(self, Guide, "name", "aesthetic")
        defaults = _declared_attr(self, "params", Guide)
        if defaults is not _MISSING and isinstance(defaults, Mapping):
            object.__setattr__(self, "params", {**defaults, **self.params})
        object.__setattr__(self, "params", frozen_mapping(self.params))

    @property
    def key(self) -> str:
        return self.aesthetic or self.name

    def build_guide(self) -> Any:
        """扩展点：子类覆写后返回 :class:`ggcore.guide.Guide` 实例。"""
        raise NotImplementedError(
            f"guide_{self.name} 没有 build_guide()（自定义 Guide 子类需要覆写它）"
        )


@dataclass(frozen=True, slots=True)
class Theme:
    """主题：完整主题（`grey` / `minimal` / `void`）或局部元素集合。

    `complete=True` 的主题整份替换；`complete=False` 的只覆盖同名元素。
    元素树、继承与解析在 :mod:`ggcore.theme`（M1-10）。

    `base_size` 是该主题的基础字号（pt），用于把根元素上的 `rel()` 折成
    具体字号；`theme_grey(base_size=16)` 会把它带下去。
    """

    name: str = ""
    elements: dict[str, Any] = field(default_factory=dict)
    complete: bool = False
    base_size: float = 11.0

    def __post_init__(self) -> None:
        _apply_declared(self, Theme, "name", "complete", "base_size")
        defaults = _declared_attr(self, "elements", Theme)
        if defaults is not _MISSING and isinstance(defaults, Mapping):
            object.__setattr__(self, "elements", {**defaults, **self.elements})
        object.__setattr__(self, "elements", frozen_mapping(self.elements))


@dataclass(frozen=True, slots=True)
class Labels:
    """`labs()` / `ggtitle()` 产生的标签集合（`title` / `subtitle` / `x` …）。"""

    values: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", frozen_mapping(self.values))

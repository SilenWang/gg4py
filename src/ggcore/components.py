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

from dataclasses import dataclass, field
from typing import Any

from ggcore.aes import frozen_mapping

__all__ = ["Coord", "Facet", "Guide", "Labels", "Scale", "Theme"]


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
        object.__setattr__(self, "params", frozen_mapping(self.params))

    @property
    def key(self) -> str:
        return self.aesthetic


@dataclass(frozen=True, slots=True)
class Coord:
    """坐标系占位（`cartesian` / `fixed`）。"""

    name: str = "cartesian"
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", frozen_mapping(self.params))


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
        object.__setattr__(self, "params", frozen_mapping(self.params))

    @property
    def key(self) -> str:
        return self.aesthetic or self.name


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
        object.__setattr__(self, "elements", frozen_mapping(self.elements))


@dataclass(frozen=True, slots=True)
class Labels:
    """`labs()` / `ggtitle()` 产生的标签集合（`title` / `subtitle` / `x` …）。"""

    values: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", frozen_mapping(self.values))

"""图层对象：`Layer` 与 `Geom` / `Stat` / `Position` 的骨架。

M1-1 的图层只是**结构化数据**：`geom_point(...)` 这类构造器（由
`ggcore.registry` 生成）返回一个 :class:`Layer`，**不画图**。真正把它们变成
IR 的六阶段流水线是 M1-3，`Geom.draw()` 的实现是 M1-7。

约定：

- 所有对象都不可变（frozen dataclass + 冻结的映射），所以图层列表里的元素
  可以在 `p + q` 的克隆之间安全共享；
- `Layer.params` 存几何参数（`size=3`、`bins=30` 等）的原始值，交给后续阶段
  解释，这里不校验；
- `show_legend=None` 表示「自动」（对应 ggplot2 的 `NA`）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ggcore.aes import Aes, as_aes, frozen_mapping

__all__ = ["Geom", "Layer", "Position", "Stat", "as_geom", "as_position", "as_stat"]


@dataclass(frozen=True, slots=True)
class Stat:
    """统计变换的占位对象（`stat = "count"` 这类名字 + 参数）。"""

    name: str = "identity"
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", frozen_mapping(self.params))


@dataclass(frozen=True, slots=True)
class Position:
    """位置调整的占位对象（`identity` / `dodge` / `stack` / `jitter`）。"""

    name: str = "identity"
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", frozen_mapping(self.params))


@dataclass(frozen=True, slots=True)
class Geom:
    """几何对象基类：只承载名字与 aes 契约。

    `required_aes` / `default_aes` 照抄 ggplot2 4.0.3 的 geom 定义，供 M1-3 的
    流水线决定哪些列必须存在、缺省美学取什么值。`draw` 留给 M1-7（各 geom 的
    具体类）实现，在骨架阶段调用一律 `NotImplementedError`。
    """

    name: str
    required_aes: tuple[str, ...] = ()
    default_aes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "required_aes", tuple(self.required_aes))
        object.__setattr__(self, "default_aes", frozen_mapping(self.default_aes))

    def draw(self, *args: Any, **kwargs: Any) -> Any:
        """绘制当前图层（M1-7）。骨架阶段没有实现。"""
        raise NotImplementedError(f"geom_{self.name} 的绘制是 M1-7 的事；M1-1 只负责把图层构造出来")


@dataclass(frozen=True, slots=True)
class Layer:
    """一个图层：geom + stat + position + 映射 + 数据 + 参数。

    与 ggplot2 的 `layer()` 一一对应；`inherit_aes` / `show_legend` 的语义也照
    上游（`show_legend=None` 即 `NA`，表示按 geom 的默认规则决定）。
    """

    geom: Geom
    stat: Stat = field(default_factory=Stat)
    position: Position = field(default_factory=Position)
    mapping: Aes = field(default_factory=Aes)
    data: Any = None
    params: dict[str, Any] = field(default_factory=dict)
    inherit_aes: bool = True
    show_legend: bool | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "mapping", as_aes(self.mapping))
        object.__setattr__(self, "params", frozen_mapping(self.params))


def as_stat(value: Stat | str | None, default: str = "identity") -> Stat:
    """`None` / 名字 / `Stat` 统一成 `Stat`。"""
    if value is None:
        return Stat(default)
    if isinstance(value, Stat):
        return value
    if isinstance(value, str):
        return Stat(value)
    raise TypeError(f"stat 必须是 Stat 或名字，得到 {type(value).__name__}")


def as_position(value: Position | str | None, default: str = "identity") -> Position:
    """`None` / 名字 / `Position` 统一成 `Position`。"""
    if value is None:
        return Position(default)
    if isinstance(value, Position):
        return value
    if isinstance(value, str):
        return Position(value)
    raise TypeError(f"position 必须是 Position 或名字，得到 {type(value).__name__}")


def as_geom(
    value: Geom | str | None,
    default: str,
    required_aes: tuple[str, ...] = (),
    default_aes: dict[str, Any] | None = None,
) -> Geom:
    """`None` / 名字 / `Geom` 统一成 `Geom`；用名字时按给定契约补齐。"""
    if value is None:
        return Geom(name=default, required_aes=required_aes, default_aes=default_aes or {})
    if isinstance(value, Geom):
        return value
    if isinstance(value, str):
        return Geom(name=value, required_aes=required_aes, default_aes=default_aes or {})
    raise TypeError(f"geom 必须是 Geom 或名字，得到 {type(value).__name__}")

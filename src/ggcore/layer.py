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

from collections.abc import Mapping
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
    """几何对象：名字 + aes 契约 + 绘制入口。

    `required_aes` / `default_aes` 照抄 ggplot2 4.0.3 的 geom 定义，供 M1-3 的
    流水线决定哪些列必须存在、缺省美学取什么值。`non_missing_aes` /
    `optional_aes` 与上游同名（`docs/notes/build.md` §2、`Geom$handle_na()`）。

    绘制实现在 :mod:`ggcore.geom`（M1-7），这里只按名字转发——构造路径
    （`as_geom()` / `geom_*()` 注册表）不变，`Geom` 仍是不可变数据对象。
    """

    name: str
    required_aes: tuple[str, ...] = ()
    default_aes: dict[str, Any] = field(default_factory=dict)
    #: `Geom$non_missing_aes`：`handle_na()` 也看这些列（`NA` 值删行）。
    non_missing_aes: tuple[str, ...] = ()
    #: `Geom$optional_aes`：可以映射但不必需的美学（如 smooth 的 `ymin`/`ymax`）。
    optional_aes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "required_aes", tuple(self.required_aes))
        object.__setattr__(self, "default_aes", frozen_mapping(self.default_aes))
        object.__setattr__(self, "non_missing_aes", tuple(self.non_missing_aes))
        object.__setattr__(self, "optional_aes", tuple(self.optional_aes))

    # -- 绘制契约（M1-7）：按名字查 ggcore.geom 的实现 --------------------

    def _renderer(self) -> Any:
        from ggcore.geom import renderer_for

        return renderer_for(self.name)

    def setup_params(
        self, data: Any, params: Mapping[str, Any] | None = None, *, raw: Any = None
    ) -> dict[str, Any]:
        """`Geom$setup_params()`：解析 `flipped_aes`（横向 geom 的朝向）。"""
        return self._renderer().setup_params(data, params or {}, raw=raw)

    def setup_data(
        self, data: Any, params: Mapping[str, Any] | None = None, *, raw: Any = None
    ) -> Any:
        """`Geom$setup_data()`：派生坐标列与行序（列序与 R 一致）。

        `raw` 是位置标度映射前的美学表（R 的 `setup_data()` 跑在
        `map_position()` 之前），供默认尺寸 / 离散性判断使用。
        """
        return self._renderer().setup_data(data, params or {}, raw=raw)

    def handle_na(self, data: Any, na_rm: bool = False) -> Any:
        """`Geom$handle_na()`：绘制期删行并发出 "Removed N rows" 警告。"""
        return self._renderer().handle_na(self, data, bool(na_rm))

    def draw(
        self,
        build: Any,
        panel: Any,
        coord: Any,
        theme: Any,
        metrics: Any,
    ) -> Any:
        """绘制一个面板的图层数据，返回 grob / gTree（M1-7）。

        `build` 是这一面板的 :class:`ggcore.build.LayerBuild`（`data` 已按
        `PANEL` 切好、已过 `handle_na()`），`panel` 是该面板的
        :class:`ggcore.coord.PanelParams`。
        """
        return self._renderer().draw(self, build, panel, coord, theme, metrics)


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
    non_missing_aes: tuple[str, ...] = (),
    optional_aes: tuple[str, ...] = (),
) -> Geom:
    """`None` / 名字 / `Geom` 统一成 `Geom`；用名字时按给定契约补齐。"""

    def build(name: str) -> Geom:
        return Geom(
            name=name,
            required_aes=required_aes,
            default_aes=default_aes or {},
            non_missing_aes=non_missing_aes,
            optional_aes=optional_aes,
        )

    if value is None:
        return build(default)
    if isinstance(value, Geom):
        return value
    if isinstance(value, str):
        return build(value)
    raise TypeError(f"geom 必须是 Geom 或名字，得到 {type(value).__name__}")

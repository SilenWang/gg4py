"""`ggcore.coord` —— 坐标系（M1-5）：`coord_cartesian` / `coord_fixed`。

坐标回答三件事，全部在**设备单位**上可断言：

1. **面板范围**：每条轴的数据范围（含 expand）。范围来源是 M1-4 的
   :meth:`ggcore.scales.ScaleSet.limits`，`xlim` / `ylim` 覆盖它；expand 用
   上游唯一的 :func:`ggcore.scales.expand_range`，连续默认 `mult = 0.05`，
   离散默认 `add = 0.6`（即 n 个水平的范围是 `0.4 .. n + 0.6`）。
2. **数据 → 面板 npc**：:meth:`PanelParams.transform` 把（已过标度映射的）位置
   列线性换到 `0..1`，越界值留在 0..1 之外，裁剪由 geom / 设备负责。
3. **面板尺寸**：:meth:`PanelParams.panel_sizes` 在给定设备可用区域里算出
   panel 的宽高。`coord_fixed` 让**物理**高/宽 = `ratio × y 范围 / x 范围`
   （上游 `CoordFixed$aspect()`），x/y 范围等宽时就是 `ratio`。

与 ggplot2 4.0.3 逐条对齐的口径（`R/coord-cartesian-.R` / `R/coord-fixed.R`）：

- `expand = TRUE`（默认）用标度自己的 expansion（`scale_*_*(expand = ...)`
  仍然生效）；`expand = FALSE` 完全不扩；给数值序列时按上游 `expansion()`
  解释（标量 / 2 元 / 4 元）。
- `xlim` / `ylim` 是**数据空间**的值，替换标度范围之前要先过位置标度的
  transformation（上游 4.0.3 `expand_limits_scale()` 的
  `transformation$transform(coord_limits)`）：`scale_x_log10() +
  coord_cartesian(xlim = c(1, 100))` 的面板范围是 `-0.1 .. 2.1`（log10 的
  `0 .. 2` 再 expand），不是 `-3.95 .. 104.95`。之后才做 expand，所以
  `coord_cartesian(xlim = c(2, 5))` 与 `scale_x_continuous(limits = c(2, 5))`
  的面板范围相同（都是 `1.85 .. 5.15`）。区别在数据：标度 limits 把越界值变成
  NA（R 的 "Removed N rows" 警告），coord limits 只把点画到面板外/裁掉。
  两类越界点分别记在 :attr:`PanelParams.dropped`（按轴 NA 数）与
  :attr:`PanelParams.out_of_bounds`（仍有限、在 coord limits 外的）里，不静默；
  行级的 "Removed N rows" 口径单独记在 :attr:`PanelParams.rows_dropped`。
- `clip = "on"`（默认）/ `"off"`：本模块只解析并记进面板参数；真正的裁剪在
  geom 绘制期（M1-7）。
- `coord_fixed(ratio = 2)` 的 `aspect()` 是
  `ratio × diff(y.range) / diff(x.range)`，不是把物理高/宽直接写成 2——
  只有 x/y 数据范围等宽时两者才相等（验收用的 2×2 合成 panel 正是等宽）。

明确不做：`coord_polar` / `coord_flip` / `coord_trans` / `coord_sf`、facet free
scales、secondary axis。完整账本见 `docs/notes/coord.md`。
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any

import numpy as np

from ggcore.components import Coord
from ggcore.data import Column, ColumnTable
from ggcore.scales import (
    CONTINUOUS_EXPANSION,
    Expansion,
    ScaleBase,
    ScaleSet,
    expand_range,
)

__all__ = [
    "AXES",
    "CartesianCoord",
    "CoordBase",
    "CoordError",
    "FixedCoord",
    "PanelParams",
    "coord_from_component",
    "count_dropped",
    "count_out_of_bounds",
    "count_rows_dropped",
]

#: 坐标系处理的两条轴（与 `ScaleSet` 的规范化名一致）。
AXES: tuple[str, ...] = ("x", "y")

#: `PanelParams.transform` 接受的位置美学 → 轴。
_AXIS_OF = {
    "x": "x",
    "xmin": "x",
    "xmax": "x",
    "xend": "x",
    "y": "y",
    "ymin": "y",
    "ymax": "y",
    "yend": "y",
}

#: 数值列的类型（位置数据经过标度映射后都是 float，这里也接受整型 / 布尔）。
_NUMERIC_KINDS = frozenset({"float", "int", "bool", "datetime", "timedelta"})


class CoordError(ValueError):
    """坐标系参数无法解析，或面板范围/尺寸算不出来。"""


# ---------------------------------------------------------------------------
# 面板参数（已解析）
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PanelParams:
    """一次构建的面板参数：范围、clip、比例、越界计数。

    `x_range` / `y_range` 是**展开后**的面板范围（R
    `ggplot_build(p)$layout$panel_params[[1]]$x.range`）；`x_limits` /
    `y_limits` 是展开**前**的范围（coord limits 或标度 limits，离散已换成
    `1..n` 的数值）。

    越界点分三类，都不静默：

    - :attr:`dropped`：**按轴**统计的缺失位置数（标度的 `oob = censor` 把值
      变成 NA，原始数据里的 NA 也算）。同一行 x、y 都缺时会各记一次，所以
      `sum(dropped.values())` **不是** R 的 "Removed N rows"；
    - :attr:`rows_dropped`：**行级**计数（x / y 任一缺失即算一行），这才是
      R 的 "Removed N rows"；
    - :attr:`out_of_bounds`：仍是有限值、但落在 `x_limits` / `y_limits` 之外的
      行（`coord_cartesian(xlim=)` 的语义：R 不删数据，画到面板外再按 clip 处理）。
    """

    x_range: tuple[float, float]
    y_range: tuple[float, float]
    x_limits: tuple[float, float]
    y_limits: tuple[float, float]
    clip: str = "on"
    ratio: float | None = None
    out_of_bounds: Mapping[str, int] = field(default_factory=dict)
    dropped: Mapping[str, int] = field(default_factory=dict)
    rows_dropped: int = 0
    coord: str = "cartesian"
    discrete: Mapping[str, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("x_range", "y_range", "x_limits", "y_limits"):
            low, high = getattr(self, name)
            if not (math.isfinite(low) and math.isfinite(high)):
                raise CoordError(f"{name} 必须是有限数，收到 {(low, high)!r}")
        # `on` / `off` / `inherit` 都是 coord 的合法取值（R 4.0.3 原样透传；
        # `inherit` 让面板视口沿用父视口的裁剪，见 `geom/scene.py`）。
        if self.clip not in ("on", "off", "inherit"):
            raise CoordError(f"clip 只能是 'on' / 'off' / 'inherit'，收到 {self.clip!r}")

    # -- 范围 ---------------------------------------------------------------

    @property
    def ranges(self) -> Mapping[str, tuple[float, float]]:
        """`{"x": (low, high), "y": (low, high)}`（只读）。"""
        return MappingProxyType({"x": self.x_range, "y": self.y_range})

    @property
    def limits(self) -> Mapping[str, tuple[float, float]]:
        """展开前的范围（与 :attr:`ranges` 同构）。"""
        return MappingProxyType({"x": self.x_limits, "y": self.y_limits})

    @property
    def aspect_ratio(self) -> float | None:
        """物理高/宽（R `CoordFixed$aspect()`）；普通坐标系是 `None`。

        x / y 范围跨度为 0 时抛 :class:`CoordError`（R 那边是除零得到
        `Inf`/`NaN`，交给 grid 布局时报一句难懂的错误）。
        """
        if self.ratio is None:
            return None
        x_span = self.x_range[1] - self.x_range[0]
        y_span = self.y_range[1] - self.y_range[0]
        if x_span == 0:
            raise CoordError(
                f"x 面板范围跨度为 0（{self.x_range!r}）：xlim 退化成一个点或数据全相同，"
                "coord_fixed 无法计算物理高/宽"
            )
        if y_span == 0:
            raise CoordError(
                f"y 面板范围跨度为 0（{self.y_range!r}）：ylim 退化成一个点或数据全相同，"
                "coord_fixed 的面板高度会是 0"
            )
        return self.ratio * y_span / x_span

    # -- 数据 → npc ---------------------------------------------------------

    def transform(self, column: Column, aesthetic: str = "x") -> Column:
        """位置列 → 面板 `0..1`（npc，y 向上）；缺失保留在 `na_mask` 里。

        越界值**不**夹到 0..1：`coord_cartesian` 的语义是「画到面板外再裁」，
        夹死会把 `clip = "off"` 的点也丢掉。
        """
        axis = _AXIS_OF.get(aesthetic)
        if axis is None:
            raise CoordError(f"transform 只接受位置美学，收到 {aesthetic!r}")
        if not isinstance(column, Column):
            raise TypeError(f"transform 需要 ggcore.data.Column，收到 {type(column).__name__}")
        if column.kind not in _NUMERIC_KINDS:
            raise CoordError(
                f"{aesthetic} 是 {column.kind} 列；先经位置标度映射成数值（1..n）再做 coord 变换"
            )
        low, high = self._range_for(axis)
        span = high - low
        if span == 0:
            raise CoordError(f"{axis} 面板范围宽度为 0（{low!r} == {high!r}），无法映射到 0..1")
        values = np.asarray(column.values, dtype=np.float64)
        mask = np.asarray(column.na_mask, dtype=bool) | ~np.isfinite(values)
        npc = (values - low) / span
        npc[mask] = 0.0
        return Column("float", npc, na_mask=mask)

    # -- 面板尺寸 -----------------------------------------------------------

    def panel_sizes(self, device_w: float, device_h: float) -> tuple[float, float]:
        """在 `device_w × device_h` 的可用区域里算 panel 的 `(宽, 高)`。

        普通坐标系占满整块区域；`coord_fixed` 取满足 `高/宽 = aspect_ratio`
        的最大内接矩形。单位与入参一致（:class:`ggcore.viewport.Device` 用英寸）。
        调用方传的是**面板可用区域**：轴标签 / 标题的留白由布局负责（M1-11）。
        """
        width = float(device_w)
        height = float(device_h)
        if not (math.isfinite(width) and math.isfinite(height)) or width <= 0 or height <= 0:
            raise CoordError(f"panel_sizes 需要正的设备尺寸，收到 {device_w!r} × {device_h!r}")
        aspect = self.aspect_ratio
        if aspect is None:
            return (width, height)
        if not math.isfinite(aspect) or aspect <= 0:
            raise CoordError(f"aspect 必须是正有限数，算得 {aspect!r}")
        sized_width = min(width, height / aspect)
        return (sized_width, aspect * sized_width)

    def _range_for(self, axis: str) -> tuple[float, float]:
        return self.x_range if axis == "x" else self.y_range

    def _limits_for(self, axis: str) -> tuple[float, float]:
        return self.x_limits if axis == "x" else self.y_limits

    # -- 越界计数 -----------------------------------------------------------

    def with_counts(
        self,
        *,
        out_of_bounds: Mapping[str, int] | None = None,
        dropped: Mapping[str, int] | None = None,
        rows_dropped: int | None = None,
    ) -> PanelParams:
        """带上越界计数的新对象（`PanelParams` 不可变，构建期用完再替换）。"""
        updates: dict[str, Any] = {}
        for name, counts in (("out_of_bounds", out_of_bounds), ("dropped", dropped)):
            if counts is not None:
                updates[name] = MappingProxyType({axis: int(counts.get(axis, 0)) for axis in AXES})
        if rows_dropped is not None:
            updates["rows_dropped"] = int(rows_dropped)
        return replace(self, **updates) if updates else self

    def warnings(self) -> tuple[str, ...]:
        """越界点的人话提示（非空才发；R 侧是 "Removed N rows …"）。"""
        out: list[str] = []
        if self.rows_dropped:
            out.append(
                f"coord: 共 {self.rows_dropped} 行含缺失位置"
                f"（R: Removed {self.rows_dropped} rows containing missing values"
                " or values outside the scale range）"
            )
        for axis in AXES:
            dropped = int(self.dropped.get(axis, 0))
            if dropped:
                out.append(
                    f"coord: {axis} 轴有 {dropped} 个缺失值"
                    "（按轴计数：原始 NA 与 scale limits 丢弃的值都算，"
                    "同一行 x/y 都缺会计两次）"
                )
            count = int(self.out_of_bounds.get(axis, 0))
            if count:
                low, high = self._limits_for(axis)
                out.append(
                    f"coord: {axis} 轴有 {count} 个值超出范围 [{low:g}, {high:g}]"
                    f"（coord limits 不删数据）；clip = {self.clip!r}"
                )
        return tuple(out)


# ---------------------------------------------------------------------------
# 坐标系
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CoordBase:
    """坐标基类：解析参数、算面板范围。

    参数名与上游一致：`xlim` / `ylim` / `expand` / `clip`（`fixed` 另有 `ratio`）。
    """

    xlim: Any = None
    ylim: Any = None
    expand: Any = True
    clip: str = "on"
    name: str = "cartesian"

    def __post_init__(self) -> None:
        # R 4.0.3 的 `coord_*()` 原样接受 `clip`（`CoordCartesian$setup_params()` 不再
        # 校验），`"inherit"` 是 gtable 的第三态，构建期就合法、直接进 panel params。
        if self.clip not in ("on", "off", "inherit"):
            raise CoordError(f"clip 只能是 'on' / 'off' / 'inherit'，收到 {self.clip!r}")
        if not _valid_expand(self.expand):
            raise CoordError(
                "expand 只接受 True / False / Expansion / 标量或 1–4 元数值序列"
                f"（形式同 expansion()），收到 {self.expand!r}"
            )
        for axis in AXES:
            value = getattr(self, f"{axis}lim")
            if value is not None:
                # 只校验长度；数值/名称的解析要等标度类型（discrete?）确定。
                if isinstance(value, (str, bytes)) or len(tuple(value)) != 2:
                    raise CoordError(f"{axis}lim 必须是 2 元序列，收到 {value!r}")

    # -- 范围 ---------------------------------------------------------------

    def panel_ranges(self, scales: ScaleSet) -> Mapping[str, tuple[float, float]]:
        """两条轴展开后的面板范围（只读映射）。"""
        if not isinstance(scales, ScaleSet):
            raise TypeError(
                f"panel_ranges 需要 ggcore.scales.ScaleSet，收到 {type(scales).__name__}"
            )
        return MappingProxyType({axis: self._axis_panel(scales, axis).range for axis in AXES})

    def panel_params(self, scales: ScaleSet) -> PanelParams:
        """解析后的完整面板参数（范围 / limits / clip / ratio）。"""
        resolved = {axis: self._axis_panel(scales, axis) for axis in AXES}
        return PanelParams(
            x_range=resolved["x"].range,
            y_range=resolved["y"].range,
            x_limits=resolved["x"].limits,
            y_limits=resolved["y"].limits,
            clip=self.clip,
            ratio=self._ratio(),
            coord=self.name,
            discrete=MappingProxyType({axis: resolved[axis].discrete for axis in AXES}),
        )

    def _ratio(self) -> float | None:
        return None

    def _axis_panel(self, scales: ScaleSet, axis: str) -> _AxisPanel:
        scale = scales.scale(axis)
        limits = scales.limits(axis)
        discrete = bool(scale is not None and getattr(scale, "discrete", False))
        base = _base_limits(limits, discrete) if scale is not None else (0.0, 1.0)
        coord_limit = getattr(self, f"{axis}lim")
        if coord_limit is not None:
            base = _coord_limits(coord_limit, limits, discrete, axis)
            base = _transform_coord_limits(base, coord_limit, scale, discrete, axis)
        expansion = self._expansion(scale)
        low, high = expand_range(base[0], base[1], expansion.mult, expansion.add)
        return _AxisPanel(limits=base, range=(low, high), discrete=discrete)

    def _expansion(self, scale: ScaleBase | None) -> Expansion:
        default = scale.expansion if scale is not None else CONTINUOUS_EXPANSION
        if self.expand is None or self.expand is True:
            return default
        if self.expand is False:
            return Expansion((0.0, 0.0), (0.0, 0.0))
        return Expansion.from_param(self.expand, default=default)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"{type(self).__name__}(clip={self.clip!r})"


@dataclass(frozen=True, slots=True)
class CartesianCoord(CoordBase):
    """`coord_cartesian()`：范围只影响显示，不删数据（越界点裁在面板外）。"""

    name: str = field(default="cartesian", init=False)


@dataclass(frozen=True, slots=True)
class FixedCoord(CoordBase):
    """`coord_fixed(ratio = 1)`：面板物理高/宽 = `ratio × y 范围 / x 范围`。"""

    ratio: float = 1.0
    name: str = field(default="fixed", init=False)

    def __post_init__(self) -> None:
        # dataclass(slots=True) 会重建类，零参 super() 在冻结 slots dataclass 里
        # 会拿到旧类；显式按基类调用。
        CoordBase.__post_init__(self)
        value = float(self.ratio)
        if not math.isfinite(value) or value <= 0:
            raise CoordError(f"coord_fixed 的 ratio 必须是正有限数，收到 {self.ratio!r}")
        object.__setattr__(self, "ratio", value)

    def _ratio(self) -> float | None:
        return self.ratio


@dataclass(frozen=True, slots=True)
class _AxisPanel:
    limits: tuple[float, float]
    range: tuple[float, float]
    discrete: bool


# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------

#: 每个坐标系认的参数（其余直接报错，与 R 的 unused argument 一致）。
_COORD_PARAMS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "cartesian": frozenset({"xlim", "ylim", "expand", "clip"}),
        "fixed": frozenset({"xlim", "ylim", "expand", "clip", "ratio"}),
    }
)


def coord_from_component(component: Any) -> CoordBase:
    """`ggcore.components.Coord` → 可用的坐标系实现。"""
    if component is None:
        return CartesianCoord()
    if isinstance(component, CoordBase):
        return component
    if not isinstance(component, Coord):
        raise TypeError(f"coord 需要 ggcore.components.Coord，收到 {type(component).__name__}")
    name = component.name
    if name not in _COORD_PARAMS:
        raise CoordError(
            f"坐标系 {name!r} 尚未实现（已实现：{', '.join(sorted(_COORD_PARAMS))}）；"
            "coord_polar / flip / trans / sf 见 docs/notes/coord.md 的「不支持」清单"
        )
    unknown = set(component.params) - _COORD_PARAMS[name]
    if unknown:
        raise CoordError(
            f"coord_{name}() 不认识参数：{', '.join(sorted(unknown))}；"
            f"可用：{', '.join(sorted(_COORD_PARAMS[name]))}"
        )
    params = dict(component.params)
    if name == "fixed":
        ratio = params.pop("ratio", 1.0)
        if ratio is None:
            ratio = 1.0
        return FixedCoord(**params, ratio=ratio)
    return CartesianCoord(**params)


def _valid_expand(value: Any) -> bool:
    if value is None or isinstance(value, (bool, Expansion, Mapping)):
        return True
    if isinstance(value, (int, float, np.integer, np.floating)):
        return True
    if isinstance(value, (str, bytes)):
        return False
    try:
        items = list(value)
    except TypeError:
        return False
    return 1 <= len(items) <= 4 and all(
        isinstance(item, (int, float, np.integer, np.floating)) and not isinstance(item, bool)
        for item in items
    )


def _base_limits(limits: Any, discrete: bool) -> tuple[float, float]:
    """标度 limits → 数值面板基准范围。

    离散标度在 R 里映射到 `1..n`（含 NA 水平），不是 `0.5..n+0.5`；
    expand 的 `add = 0.6` 才把它撑成 `0.4..n+0.6`（见 scales.md 口径 3）。
    """
    if discrete:
        count = len(tuple(limits))
        return (1.0, float(max(count, 1)))
    if limits is None:
        return (0.0, 1.0)
    items = tuple(limits)
    if len(items) != 2:
        raise CoordError(f"位置标度 limits 必须是 2 元序列，收到 {limits!r}")
    return (float(items[0]), float(items[1]))


def _coord_limits(
    value: Any,
    scale_limits: Any,
    discrete: bool,
    axis: str,
) -> tuple[float, float]:
    """`xlim` / `ylim` → 基准范围（expand 之前）。

    离散标度上允许给水平名：按标度水平序号解释，等价于
    `scale_x_discrete(limits = c(...))` 的面板范围（R 4.0.3 的
    `coord_cartesian(xlim = c("a", "b"))` 会直接报错，这里做了更友好的口径，
    见 docs/notes/coord.md）。
    """
    items = tuple(value)
    if len(items) != 2:
        raise CoordError(f"{axis}lim 必须是 2 元序列，收到 {value!r}")
    numeric = [isinstance(item, (int, float, np.integer, np.floating)) for item in items]
    if all(numeric):
        low, high = float(items[0]), float(items[1])
        return (min(low, high), max(low, high))
    if any(numeric):
        raise CoordError(f"{axis}lim 不能混用数值与水平名：{value!r}")
    if not discrete:
        raise CoordError(f"{axis}lim 在连续标度上必须是数值，收到 {value!r}")
    levels = [level for level in tuple(scale_limits) if level is not None]
    positions = {str(level): index + 1.0 for index, level in enumerate(levels)}
    missing = [str(item) for item in items if str(item) not in positions]
    if missing:
        raise CoordError(
            f"{axis}lim 里的水平 {', '.join(missing)} 不在标度水平里（可用：{', '.join(levels)}）"
        )
    low, high = positions[str(items[0])], positions[str(items[1])]
    return (min(low, high), max(low, high))


def _transform_coord_limits(
    base: tuple[float, float],
    raw: Any,
    scale: ScaleBase | None,
    discrete: bool,
    axis: str,
) -> tuple[float, float]:
    """coord limits → 标度空间（R 4.0.3 `expand_limits_scale()` 的第一步）。

    R 里 `coord$limits` 存的是**数据空间**的值，
    `expand_limits_scale()` 先 `transformation$transform(coord_limits)` 再
    expand；所以 `scale_x_log10() + coord_cartesian(xlim = c(1, 100))` 的 base
    是 `0 .. 2` 而不是 `1 .. 100`。离散标度不做变换（R 按水平序号处理）。
    """
    if scale is None or discrete:
        return base
    low, high = scale.transform_limits(base)
    if not (math.isfinite(low) and math.isfinite(high)):
        raise CoordError(
            f"{axis}lim = {tuple(raw)!r} 经位置标度变换后不是有限值"
            f"（{(low, high)!r}）：log10 标度上的 limits 必须 > 0"
        )
    return (min(low, high), max(low, high))


# ---------------------------------------------------------------------------
# 越界计数
# ---------------------------------------------------------------------------


def count_out_of_bounds(
    panel: PanelParams,
    tables: Iterable[ColumnTable],
) -> Mapping[str, int]:
    """按轴统计**有限值**落在 `x_limits` / `y_limits` 之外的行数。

    只数 `x` / `y` 两列：它们是位置的主通道（`xmin/xmax` 派生列不重复计数）。
    `coord_cartesian(xlim=)` 的越界点在这里计数（R 不删它们，只是画到面板外）；
    标度 limits 造成的 NA 归 :func:`count_dropped`，不与这里混算。
    """
    counts = {axis: 0 for axis in AXES}
    for table in tables:
        for axis in AXES:
            if axis not in table.names:
                continue
            column = table.column(axis)
            if column.kind not in _NUMERIC_KINDS:
                continue
            low, high = panel._limits_for(axis)
            values = np.asarray(column.values, dtype=np.float64)
            finite = np.isfinite(values) & ~np.asarray(column.na_mask, dtype=bool)
            outside = finite & ((values < low) | (values > high))
            counts[axis] += int(np.count_nonzero(outside))
    return MappingProxyType(counts)


def count_dropped(tables: Iterable[ColumnTable]) -> Mapping[str, int]:
    """按轴统计已经是 NA 的值数（原始 NA + 标度 `oob = censor` 丢掉的值）。

    这是**按轴**的口径；同一行 x、y 都缺会各记一次，所以
    `sum(count_dropped(...).values())` 不等于 R 的 "Removed N rows"——
    行级计数用 :func:`count_rows_dropped`。标度 `oob = censor` 把越界值变成
    NA，绘制期 R 会报 "Removed N rows containing missing values or values
    outside the scale range"。
    """
    counts = {axis: 0 for axis in AXES}
    for table in tables:
        for axis in AXES:
            if axis not in table.names:
                continue
            column = table.column(axis)
            if column.kind not in _NUMERIC_KINDS:
                continue
            values = np.asarray(column.values, dtype=np.float64)
            missing = np.asarray(column.na_mask, dtype=bool) | ~np.isfinite(values)
            counts[axis] += int(np.count_nonzero(missing))
    return MappingProxyType(counts)


def count_rows_dropped(tables: Iterable[ColumnTable]) -> int:
    """按**行**统计缺失位置数：x / y 任一缺失就算一行（= R 的 "Removed N rows"）。

    只数位置主通道 `x` / `y`；`xmin/xmax` 这类派生列不重复计数（它们缺失时
    `x` 通常也缺）。
    """
    total = 0
    for table in tables:
        missing: np.ndarray | None = None
        for axis in AXES:
            if axis not in table.names:
                continue
            column = table.column(axis)
            if column.kind not in _NUMERIC_KINDS:
                continue
            values = np.asarray(column.values, dtype=np.float64)
            axis_missing = np.asarray(column.na_mask, dtype=bool) | ~np.isfinite(values)
            missing = axis_missing if missing is None else missing | axis_missing
        if missing is not None:
            total += int(np.count_nonzero(missing))
    return total

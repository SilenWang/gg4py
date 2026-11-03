"""`ggcore.coord` —— 坐标系：`coord_cartesian` / `fixed` / `equal` / `flip` /
`trans` / `polar` / `radial` / `sf` / `map` / `quickmap`（M2-1）。

坐标回答三件事，全部在**设备单位**上可断言：

1. **面板范围**：每条轴的数据范围（含 expand）。范围来源是 M1-4 的
   :meth:`ggcore.scales.ScaleSet.limits`，`xlim` / `ylim` 覆盖它；expand 用
   上游唯一的 :func:`ggcore.scales.expand_range`，连续默认 `mult = 0.05`，
   离散默认 `add = 0.6`（即 n 个水平的范围是 `0.4 .. n + 0.6`）。
2. **数据 → 面板 npc**：:meth:`PanelParams.transform` 把（已过标度映射的）位置
   列换到 `0..1`，越界值留在 0..1 之外，裁剪由 geom / 设备负责。
3. **面板尺寸**：:meth:`PanelParams.panel_sizes` 在给定设备可用区域里算出
   panel 的宽高（`coord_fixed` / `equal` / `polar` / `radial` 的比例都在这里）。

与 ggplot2 4.0.3 逐条对齐的口径（`R/coord-*.R`，pin cc1444c1）：

- **线性族**（cartesian / fixed / equal）：范围 = base + expand；`xlim` / `ylim`
  是数据空间的值，先过位置标度变换再 expand。
- **`coord_flip`**：坐标轴互换，但**不是**交换 x / y 映射——上游的做法是
  `flip_axis_labels(data)` + 翻转整套 panel_params + 交换 SCALE_X / SCALE_Y。
  这里在同一处落实：:attr:`PanelParams.flipped` 让 `transform` 读对侧列、让
  轴取对侧标度；geom 里不判断 coord 名字。
- **`coord_trans` / `coord_transform`**：逐轴 `x` / `y` 变换（identity / log10 /
  log2 / log / log1p / exp / sqrt / reverse / reciprocal），在**标度空间之后**
  再作用一次（上游 `CoordTransform$transform()`）。面板范围 = 变换后空间的
  base 再 expand（上游 `expand_limits_continuous_trans()`），刻度位置 =
  `rescale(trans(break), range)`，标签仍是未变换的断点文本。
- **`coord_polar` / `coord_radial`**：theta / r 两条轴，`theta_rescale()` /
  `r_rescale()` 与上游同式；`start` / `direction` / `end` / `inner.radius` /
  `thetalim` / `rlim` 全部落地，partial arc 的 bbox 用上游 `polar_bbox()`。
- **`coord_sf` / `coord_map` / `coord_quickmap`**：只做注册与最小可用。真正的
  投影 / graticule / sf 几何归 M3-2；这里 identity 投影可用，要求真实投影时
  报 :class:`CoordError` 并点名 M3-2（不静默当 identity）。
- **`coord_equal`**：与 `coord_fixed(ratio = 1)` 同一口径（上游 4.0.3
  `coord_equal()` 就是 `coord_cartesian(ratio = 1)`）。
- `reverse`：`coord_cartesian(reverse = "x"/"y"/"xy")` 与 `coord_transform()`
  的同名参数——只翻转映射（`1 - t`），不改范围。

明确不做（见 `docs/notes/coord.md` 的「不支持清单」）：极坐标下的 `coord_munch`
逐边细分只覆盖 rect / polygon 图层，非矩形 clipPath 之外的极坐标阴影细节，
以及 sf 的真实投影。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, ClassVar

import numpy as np

from ggcore.aes import X_AES, Y_AES, flipped_names
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
    "COORD_IMPLEMENTATIONS",
    "CartesianCoord",
    "CoordBase",
    "CoordError",
    "CoordTransform",
    "EqualCoord",
    "FixedCoord",
    "FlipCoord",
    "MapCoord",
    "PanelParams",
    "PolarCoord",
    "PolarGeometry",
    "QuickmapCoord",
    "RadialCoord",
    "SfCoord",
    "TransCoord",
    "as_coord_transform",
    "coord_from_component",
    "coord_munch",
    "count_dropped",
    "count_out_of_bounds",
    "count_rows_dropped",
    "polar_bbox",
    "r_rescale",
    "theta_rescale",
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

_TWO_PI = 2.0 * math.pi


class CoordError(ValueError):
    """坐标系参数无法解析，或面板范围/尺寸算不出来。"""


# ---------------------------------------------------------------------------
# 逐轴变换（上游 `scales::transform_*()` 的最小集合）
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CoordTransform:
    """`coord_trans(x = "log10")` 用的单轴变换。

    `apply()` / `invert()` 都按 numpy 向量化；定义域外的值给 NaN（上游是 NaN /
    ±Inf，再在 `squish_infinite()` 里处理）。`reverse` 是负号，`sqrt` 的负值给
    NaN，与 R 的 `sqrt()` 一致。
    """

    name: str = "identity"

    def apply(self, values: Any) -> np.ndarray:
        return np.asarray(values, dtype=np.float64)

    def invert(self, values: Any) -> np.ndarray:
        return np.asarray(values, dtype=np.float64)

    def domain_error(self, values: np.ndarray) -> bool:
        """变换后是否出现非有限值（调用方据此报错，而不是静默画 NaN）。"""
        return bool(np.any(~np.isfinite(values)))


class _LogTransform(CoordTransform):
    """`log` / `log2` / `log10`。"""

    def apply(self, values: Any) -> np.ndarray:
        data = np.asarray(values, dtype=np.float64)
        out = np.full(data.shape, np.nan)
        valid = np.isfinite(data) & (data > 0)
        out[valid] = np.log(data[valid]) / math.log(self._BASE)
        return out

    def invert(self, values: Any) -> np.ndarray:
        return np.power(self._BASE, np.asarray(values, dtype=np.float64))

    _BASE: ClassVar[float] = 10.0


@dataclass(frozen=True, slots=True)
class _Log2(_LogTransform):
    name: str = field(default="log2", init=False)
    _BASE: ClassVar[float] = 2.0


@dataclass(frozen=True, slots=True)
class _Log10(_LogTransform):
    name: str = field(default="log10", init=False)
    _BASE: ClassVar[float] = 10.0


@dataclass(frozen=True, slots=True)
class _Log(_LogTransform):
    name: str = field(default="log", init=False)
    _BASE: ClassVar[float] = math.e


@dataclass(frozen=True, slots=True)
class _Log1p(CoordTransform):
    name: str = field(default="log1p", init=False)

    def apply(self, values: Any) -> np.ndarray:
        data = np.asarray(values, dtype=np.float64)
        out = np.full(data.shape, np.nan)
        valid = np.isfinite(data) & (data > -1)
        out[valid] = np.log1p(data[valid])
        return out

    def invert(self, values: Any) -> np.ndarray:
        return np.expm1(np.asarray(values, dtype=np.float64))


@dataclass(frozen=True, slots=True)
class _Exp(CoordTransform):
    name: str = field(default="exp", init=False)

    def apply(self, values: Any) -> np.ndarray:
        return np.exp(np.asarray(values, dtype=np.float64))

    def invert(self, values: Any) -> np.ndarray:
        return np.log(np.asarray(values, dtype=np.float64))


@dataclass(frozen=True, slots=True)
class _Sqrt(CoordTransform):
    name: str = field(default="sqrt", init=False)

    def apply(self, values: Any) -> np.ndarray:
        data = np.asarray(values, dtype=np.float64)
        out = np.full(data.shape, np.nan)
        valid = np.isfinite(data) & (data >= 0)
        out[valid] = np.sqrt(data[valid])
        return out

    def invert(self, values: Any) -> np.ndarray:
        return np.square(np.asarray(values, dtype=np.float64))


@dataclass(frozen=True, slots=True)
class _Reciprocal(CoordTransform):
    name: str = field(default="reciprocal", init=False)

    def apply(self, values: Any) -> np.ndarray:
        data = np.asarray(values, dtype=np.float64)
        out = np.full(data.shape, np.nan)
        valid = np.isfinite(data) & (data != 0)
        out[valid] = 1.0 / data[valid]
        return out

    def invert(self, values: Any) -> np.ndarray:
        data = np.asarray(values, dtype=np.float64)
        out = np.full(data.shape, np.nan)
        valid = np.isfinite(data) & (data != 0)
        out[valid] = 1.0 / data[valid]
        return out


@dataclass(frozen=True, slots=True)
class _Reverse(CoordTransform):
    name: str = field(default="reverse", init=False)

    def apply(self, values: Any) -> np.ndarray:
        return -np.asarray(values, dtype=np.float64)

    def invert(self, values: Any) -> np.ndarray:
        return -np.asarray(values, dtype=np.float64)


class _CallableTransform(CoordTransform):
    """用户给的函数（`coord_trans(x = lambda v: ...)`）。"""

    name = "function"

    def __init__(self, forward: Callable[[np.ndarray], Any], name: str = "function") -> None:
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "_forward", forward)

    def apply(self, values: Any) -> np.ndarray:
        return np.asarray(self._forward(np.asarray(values, dtype=np.float64)), dtype=np.float64)

    def invert(self, values: Any) -> np.ndarray:
        raise CoordError(
            "coord_trans 的自定义函数没有逆变换：反向需要它（`backtransform_range()` / "
            "secondary axis）。改用注册名（identity / log10 / sqrt …）或传入 "
            "`CoordTransform` 子类"
        )


_TRANSFORMS: Mapping[str, Callable[[], CoordTransform]] = MappingProxyType(
    {
        "identity": CoordTransform,
        "log": _Log,
        "log2": _Log2,
        "log10": _Log10,
        "log1p": _Log1p,
        "exp": _Exp,
        "sqrt": _Sqrt,
        "reciprocal": _Reciprocal,
        "reverse": _Reverse,
    }
)

_UNSUPPORTED_TRANSFORMS: Mapping[str, str] = MappingProxyType(
    {
        "asn": "M3-2（coord 变换长尾）",
        "atanh": "M3-2",
        "boxcox": "M3-2",
        "date": "M3-2",
        "hms": "M3-2",
        "logit": "M3-2",
        "probability": "M3-2",
        "probit": "M3-2",
        "pseudo_log": "M3-2",
        "time": "M3-2",
    }
)


def as_coord_transform(value: Any) -> CoordTransform:
    """`coord_trans(x = …)` 的取值 → :class:`CoordTransform`。"""
    if value is None:
        return CoordTransform()
    if isinstance(value, CoordTransform):
        return value
    if callable(value):
        return _CallableTransform(value, name=getattr(value, "__name__", "function"))
    key = str(value)
    if key in _TRANSFORMS:
        return _TRANSFORMS[key]()
    if key in _UNSUPPORTED_TRANSFORMS:
        raise CoordError(
            f"coord_trans 的变换 {key!r} 尚未实现（留给 {_UNSUPPORTED_TRANSFORMS[key]}）；"
            f"可用：{', '.join(sorted(_TRANSFORMS))}"
        )
    raise CoordError(f"未知的 coord 变换：{key!r}（可用：{', '.join(sorted(_TRANSFORMS))}）")


# ---------------------------------------------------------------------------
# 极坐标的几何（上游 theta_rescale / r_rescale / polar_bbox）
# ---------------------------------------------------------------------------


def _squish_infinite(values: np.ndarray, rng: tuple[float, float]) -> np.ndarray:
    """上游 `squish_infinite()`：只把 ±Inf 拉回范围端点，NA 原样保留。"""
    out = np.asarray(values, dtype=np.float64).copy()
    out[np.isposinf(out)] = rng[1]
    out[np.isneginf(out)] = rng[0]
    return out


def theta_rescale(
    values: Any,
    rng: tuple[float, float],
    arc: tuple[float, float] = (0.0, _TWO_PI),
    direction: float = 1.0,
) -> np.ndarray:
    """上游 `theta_rescale()`：数据 → 弧度（0 = 12 点方向，顺时针为正）。

    `rescale(x, to = arc, from = range) %% 2π * direction`；数值按弧度存，
    NaN 原样保留（调用方决定断线 / 跳过）。
    """
    data = _squish_infinite(np.asarray(values, dtype=np.float64), rng)
    span = float(rng[1]) - float(rng[0])
    if span == 0:
        raise CoordError(f"theta 轴范围跨度为 0（{rng!r}），无法映射到极角")
    ratio = (data - float(rng[0])) / span
    angle = float(arc[0]) + ratio * (float(arc[1]) - float(arc[0]))
    return np.mod(angle, _TWO_PI) * float(direction)


def r_rescale(
    values: Any,
    rng: tuple[float, float],
    donut: tuple[float, float] = (0.0, 0.4),
) -> np.ndarray:
    """上游 `r_rescale()`：数据 → 半径 `donut`（默认 0 .. 0.4，外圈留 0.1 放标签）。"""
    data = _squish_infinite(np.asarray(values, dtype=np.float64), rng)
    span = float(rng[1]) - float(rng[0])
    if span == 0:
        raise CoordError(f"r 轴范围跨度为 0（{rng!r}），无法映射到半径")
    ratio = (data - float(rng[0])) / span
    return float(donut[0]) + ratio * (float(donut[1]) - float(donut[0]))


def _in_arc(theta: np.ndarray, arc: tuple[float, float]) -> np.ndarray:
    """上游 `in_arc()`：点是否落在 `arc` 里（满圆恒真）。"""
    if abs(float(arc[1]) - float(arc[0])) > _TWO_PI - math.sqrt(np.finfo(np.float64).eps):
        return np.ones(np.shape(theta), dtype=bool)
    start = float(arc[0]) % _TWO_PI
    end = float(arc[1]) % _TWO_PI
    data = np.mod(np.asarray(theta, dtype=np.float64), _TWO_PI)
    if start < end:
        return (data >= start) & (data <= end)
    return ~((data < start) & (data > end))


def polar_bbox(
    arc: tuple[float, float],
    inner_radius: tuple[float, float] = (0.0, 0.4),
) -> tuple[tuple[float, float], tuple[float, float]]:
    """上游 `polar_bbox()`：partial arc 在 npc 里的外接框（含 5% 边距）。

    满圆（`abs(diff(arc)) >= 2π`）直接给 `0..1`；否则按弧端点与四个方向上的
    极值算包围盒，公式逐行照抄上游（`margin = c(0.05, 0.05, 0.05, 0.05)`）。
    """
    if abs(float(arc[1]) - float(arc[0])) >= _TWO_PI:
        return ((0.0, 1.0), (0.0, 1.0))
    start, end = sorted((float(arc[0]), float(arc[1])))
    inner = sorted((float(inner_radius[0]), float(inner_radius[1])))
    margin = 0.05
    arc_values = np.array([start, end], dtype=np.float64)
    xmax = 0.5 * np.sin(arc_values) + 0.5
    ymax = 0.5 * np.cos(arc_values) + 0.5
    xmin = inner[0] * np.sin(arc_values) + 0.5
    ymin = inner[0] * np.cos(arc_values) + 0.5
    top = float(np.max(ymin)) + margin
    right = float(np.max(xmin)) + margin
    bottom = float(np.min(ymin)) - margin
    left = float(np.min(xmin)) - margin
    probes = np.linspace(0.0, 1.5 * math.pi, 4)
    inside = _in_arc(probes, (start, end))
    bounds = np.where(
        inside,
        np.array([1.0, 1.0, 0.0, 0.0]),
        np.array(
            [
                max(float(np.max(ymax)), top),
                max(float(np.max(xmax)), right),
                min(float(np.min(ymax)), bottom),
                min(float(np.min(xmax)), left),
            ]
        ),
    )
    return ((float(bounds[3]), float(bounds[1])), (float(bounds[2]), float(bounds[0])))


@dataclass(frozen=True, slots=True)
class PolarGeometry:
    """极坐标 / 径向坐标的已解析几何（`PanelParams.polar`）。

    `theta_range` / `r_range` 是**数据空间**（标度变换后）的范围；`arc` 是弧度
    区间；`inner_radius` 是内部用的 `(0, 0.4·inner.radius)` 一对；`bbox` 是
    partial arc 在 npc 里的外接框（满圆是 `(0,1)×(0,1)`）。
    """

    theta_axis: str
    theta_range: tuple[float, float]
    r_range: tuple[float, float]
    start: float = 0.0
    direction: float = 1.0
    arc: tuple[float, float] = (0.0, _TWO_PI)
    inner_radius: tuple[float, float] = (0.0, 0.4)
    bbox: tuple[tuple[float, float], tuple[float, float]] = ((0.0, 1.0), (0.0, 1.0))
    axis_rotation: tuple[float, float] = (0.0, _TWO_PI)
    radial: bool = False
    r_axis_inside: bool = False

    def __post_init__(self) -> None:
        if self.theta_axis not in ("x", "y"):
            raise CoordError(f"theta 只能是 'x' / 'y'，收到 {self.theta_axis!r}")
        for name in ("theta_range", "r_range"):
            low, high = getattr(self, name)
            if not (math.isfinite(low) and math.isfinite(high)) or low == high:
                raise CoordError(f"极坐标的 {name} 必须是两个有限且不等的数，收到 {(low, high)!r}")

    @property
    def r_axis(self) -> str:
        return "y" if self.theta_axis == "x" else "x"

    def theta_angle(self, values: Any) -> np.ndarray:
        return theta_rescale(values, self.theta_range, self.arc, self.direction)

    def radius(self, values: Any) -> np.ndarray:
        return r_rescale(values, self.r_range, self.inner_radius)

    def point(self, angle: Any, radius: Any) -> tuple[np.ndarray, np.ndarray]:
        """`(弧度, 半径 0..0.45)` → 面板 npc（含 partial arc 的 bbox 缩放）。"""
        angles = np.asarray(angle, dtype=np.float64)
        radii = np.asarray(radius, dtype=np.float64)
        px = radii * np.sin(angles) + 0.5
        py = radii * np.cos(angles) + 0.5
        (x0, x1), (y0, y1) = self.bbox
        return (px - x0) / (x1 - x0), (py - y0) / (y1 - y0)

    def project(self, theta_values: Any, r_values: Any) -> tuple[np.ndarray, np.ndarray]:
        """`(theta, r)` 数据 → 面板 npc（0..1，y 向上；`CoordRadial$transform()` 同式）。"""
        return self.point(self.theta_angle(theta_values), self.radius(r_values))

    @property
    def bbox_ratio(self) -> float:
        (x0, x1), (y0, y1) = self.bbox
        return (y1 - y0) / (x1 - x0)


# ---------------------------------------------------------------------------
# 面板参数（已解析）
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PanelParams:
    """一次构建的面板参数：范围、clip、比例、越界计数、坐标变换。

    `x_range` / `y_range` 是**面板映射空间**的范围（R
    `ggplot_build(p)$layout$panel_params[[1]]$x.range`）；`x_limits` /
    `y_limits` 是**标度空间**的 base（coord limits 或标度 limits，离散已换成
    `1..n` 的数值）。线性坐标两者只差一次 expand；`coord_trans` 下前者是变换
    后的空间、后者是标度空间；`cont_ranges` 记录上游的 `continuous_range`
    （标度空间的 expand 结果，secondary axis / 断点用）。

    越界点分三类，都不静默：

    - :attr:`dropped`：**按轴**统计的缺失位置数（标度的 `oob = censor` 把值
      变成 NA，原始数据里的 NA 也算）；
    - :attr:`rows_dropped`：**行级**计数（x / y 任一缺失即算一行），对应 R 的
      "Removed N rows"；
    - :attr:`out_of_bounds`：仍是有限值、但落在 `x_limits` / `y_limits` 之外的
      行（`coord_cartesian(xlim=)` 的语义：R 不删数据，画到面板外再裁）。
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
    #: `coord_flip`：屏幕 x 来自原始 y 列（轴 / 标度也已对调）。
    flipped: bool = False
    #: `coord_*` 的 `reverse`：`{axis: bool}`；只翻转映射（`1 - t`），不改范围。
    reverse: Mapping[str, bool] = field(default_factory=dict)
    #: `coord_trans` 的逐轴变换；缺省 / identity 时为空。
    trans: Mapping[str, CoordTransform] = field(default_factory=dict)
    #: 标度空间的 expand 结果（上游 `continuous_range`）；线性坐标等于 `*_range`。
    cont_ranges: Mapping[str, tuple[float, float]] = field(default_factory=dict)
    #: 极坐标 / 径向坐标的几何（线性坐标为 None）。
    polar: PolarGeometry | None = None

    def __post_init__(self) -> None:
        for name in ("x_range", "y_range", "x_limits", "y_limits"):
            low, high = getattr(self, name)
            if not (math.isfinite(low) and math.isfinite(high)):
                raise CoordError(f"{name} 必须是有限数，收到 {(low, high)!r}")
        # `on` / `off` 是 coord 的取值（R 同）；`inherit` 是 gtable 的第三态，
        # 供场景装配直接构造 `PanelParams` 时使用（M1-7 的 clip 三态）。
        if self.clip not in ("on", "off", "inherit"):
            raise CoordError(f"clip 只能是 'on' / 'off' / 'inherit'，收到 {self.clip!r}")
        if self.polar is not None and self.flipped:
            raise CoordError("coord_flip 不能和极坐标 / 径向坐标叠加（一次只能有一个坐标系）")

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
    def continuous_ranges(self) -> Mapping[str, tuple[float, float]]:
        """上游 `continuous_range`（标度空间 + expand）；缺省回落到 `ranges`。"""
        if not self.cont_ranges:
            return self.ranges
        return MappingProxyType(
            {axis: tuple(self.cont_ranges.get(axis, self._range_for(axis))) for axis in AXES}
        )

    @property
    def is_linear(self) -> bool:
        """线性坐标（cartesian / fixed / equal / flip + identity 变换）。

        极坐标 / 径向坐标 / 非 identity 的 `coord_trans` 都是 `False`——geom
        据此决定是否走 `coord_munch()` 的逐边细分（R 的 `coord$is_linear()`）。
        """
        if self.polar is not None:
            return False
        return all(spec.name == "identity" for spec in self.trans.values())

    @property
    def aspect_ratio(self) -> float | None:
        """物理高/宽（R `Coord$aspect()`）；自由比例的坐标是 `None`。

        - `coord_fixed` / `coord_equal` / `coord_cartesian(ratio=)`：
          `ratio × diff(y.range) / diff(x.range)`；
        - `coord_polar`：1（正圆）；
        - `coord_radial`：`diff(bbox$y) / diff(bbox$x)`；
        - `coord_sf` / `coord_map` / `coord_quickmap`：投影空间的高宽比
          （quickmap 另有纬度 `1/cos(lat)` 因子）。

        x / y 范围跨度为 0 时抛 :class:`CoordError`（R 那边是除零得到
        `Inf`/`NaN`，交给 grid 布局时报一句难懂的错误）。
        """
        if self.polar is not None:
            return self.polar.bbox_ratio if self.polar.radial else 1.0
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

    def npc(self, axis: str, values: Any) -> np.ndarray:
        """一条轴上的数值（标度空间）→ 面板 npc（含 `reverse`，不含极坐标）。"""
        if self.polar is not None:
            raise CoordError("极坐标的映射是二维的：用 `transform_column()` / `project_xy()`")
        low, high = self._range_for(axis)
        span = float(high) - float(low)
        if span == 0:
            raise CoordError(f"{axis} 面板范围宽度为 0（{low!r} == {high!r}），无法映射到 0..1")
        data = np.asarray(values, dtype=np.float64)
        spec = self.trans.get(axis)
        if spec is not None and spec.name != "identity":
            data = spec.apply(data)
        out = (data - float(low)) / span
        if self.reverse.get(axis, False):
            out = 1.0 - out
        return out

    def position_of(self, axis: str, value: float) -> float:
        """单个数值 → npc（断点 / 网格线用；`value` 已在标度空间）。"""
        return float(self.npc(axis, np.array([value], dtype=np.float64))[0])

    def transform(self, column: Column, aesthetic: str = "x") -> Column:
        """位置列 → 面板 npc（一维坐标；极坐标请用 `transform_column()`）。

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
        values = np.asarray(column.values, dtype=np.float64)
        mask = np.asarray(column.na_mask, dtype=bool) | ~np.isfinite(values)
        npc = self.npc(axis, values)
        npc = np.where(mask, np.nan, npc)
        return Column("float", np.nan_to_num(npc, nan=0.0), na_mask=mask | np.isnan(npc))

    def project_xy(self, x_values: Any, y_values: Any) -> tuple[np.ndarray, np.ndarray]:
        """数据空间的一对 `(x, y)` → 屏幕 npc（0..1，y 向上）。

        这是 geom / `coord_munch()` 的统一入口：flip 在这里交换到对侧范围，
        极坐标在这里算 `r·sin(θ) / r·cos(θ)`；线性坐标就是两条轴的 `npc()`。
        """
        xs = np.asarray(x_values, dtype=np.float64)
        ys = np.asarray(y_values, dtype=np.float64)
        if self.polar is not None:
            theta = xs if self.polar.theta_axis == "x" else ys
            radius = ys if self.polar.theta_axis == "x" else xs
            return self.polar.project(theta, radius)
        if self.flipped:
            return self.npc("x", ys), self.npc("y", xs)
        return self.npc("x", xs), self.npc("y", ys)

    def transform_column(self, table: ColumnTable, name: str, axis: str) -> Column:
        """一列位置数据 → 屏幕 `axis` 的 npc（flip / 极坐标都在这里适配）。

        geom 只按**屏幕**轴（`x` / `y`）要坐标，不判断 coord 名字：flip 时这里
        读对侧列（R 的 `flip_axis_labels()`），极坐标时把该列与它的配对轴一起
        投到二维。缺失位保持 NaN，越界值不夹。
        """
        if name not in table:
            raise CoordError(f"数据里没有位置列 {name!r}")
        source = flipped_names(self.flipped).get(name, name)
        if source not in table:
            raise CoordError(f"coord_flip 需要对侧位置列 {source!r}，数据里没有")
        column = table.column(source)
        if self.polar is not None:
            theta_axis = self.polar.theta_axis
            theta_family = X_AES if theta_axis == "x" else Y_AES
            r_family = Y_AES if theta_axis == "x" else X_AES
            r_name = "y" if theta_axis == "x" else "x"
            theta_name = "x" if theta_axis == "x" else "y"
            if source in theta_family:
                theta_values = _values(column)
                radius_values = _values(table.column(r_name)) if r_name in table else theta_values
            elif source in r_family:
                radius_values = _values(column)
                theta_values = (
                    _values(table.column(theta_name)) if theta_name in table else radius_values
                )
            else:
                raise CoordError(f"{name!r} 不是位置列，极坐标无从映射")
            px, py = self.polar.project(theta_values, radius_values)
            out = px if axis == "x" else py
            mask = ~np.isfinite(out)
            return Column("float", np.nan_to_num(out, nan=0.0), na_mask=mask)
        return self.transform(column, axis)

    # -- 轴 ----------------------------------------------------------------

    def screen_axis(self, side: str) -> str:
        """`bottom` / `top` → `x`；`left` / `right` → `y`；屏幕轴名原样返回。"""
        if side in ("bottom", "top"):
            return "x"
        if side in ("left", "right"):
            return "y"
        if side in ("x", "y"):
            return side
        raise CoordError(f"未知的轴位置 {side!r}（bottom / top / left / right）")

    def scale_key(self, side: str) -> str:
        """该轴用哪条标度：flip 交换，极坐标的 r 轴用 r 侧标度。"""
        axis = self.screen_axis(side)
        if self.polar is not None:
            if axis == "x":
                return self.polar.theta_axis
            return self.polar.r_axis
        if self.flipped:
            return "y" if axis == "x" else "x"
        return axis

    def data_range(self, side: str) -> tuple[float, float]:
        """该轴的映射范围（`screen_axis` 的那一条）。"""
        return self._range_for(self.screen_axis(side))

    # -- 面板尺寸 -----------------------------------------------------------

    def panel_sizes(self, device_w: float, device_h: float) -> tuple[float, float]:
        """在 `device_w × device_h` 的可用区域里算 panel 的 `(宽, 高)`。

        普通坐标系占满整块区域；有 `aspect_ratio` 的坐标取满足
        `高/宽 = aspect_ratio` 的最大内接矩形。单位与入参一致
        （:class:`ggcore.viewport.Device` 用英寸）。调用方传的是**面板可用区域**：
        轴标签 / 标题的留白由布局负责（M1-11）。
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


def _values(column: Column) -> np.ndarray:
    """列 → float64 数组；缺失位是 NaN。"""
    data = np.asarray(column.values, dtype=np.float64).copy()
    data[np.asarray(column.na_mask, dtype=bool)] = np.nan
    return data


# ---------------------------------------------------------------------------
# 坐标系
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CoordBase:
    """坐标基类：解析参数、算面板范围。

    参数名与上游一致：`xlim` / `ylim` / `expand` / `clip` / `reverse`。
    """

    xlim: Any = None
    ylim: Any = None
    expand: Any = True
    clip: str = "on"
    reverse: Any = "none"
    name: str = "cartesian"

    #: `reverse` 的合法取值（`coord_radial` 用 theta / thetar / r）。
    _REVERSE_VALUES: ClassVar[tuple[str, ...]] = ("none", "x", "y", "xy", "yx")

    def __post_init__(self) -> None:
        # 三态都收：`coord_cartesian(clip = "inherit")` 在 R 4.0.3 是合法入口
        # （grid 的 viewport clip 也是三态，`inherit` 沿用父视口 = 页面）。
        if self.clip not in ("on", "off", "inherit"):
            raise CoordError(f"clip 只能是 'on' / 'off' / 'inherit'，收到 {self.clip!r}")
        if not _valid_expand(self.expand):
            raise CoordError(
                "expand 只接受 True / False / Expansion / 标量或 1–4 元数值序列"
                f"（形式同 expansion()），收到 {self.expand!r}"
            )
        if not _valid_reverse(self.reverse, self._REVERSE_VALUES):
            raise CoordError(
                f"{type(self).__name__} 的 reverse 只能是 "
                f"{' / '.join(repr(item) for item in self._REVERSE_VALUES)}，收到 {self.reverse!r}"
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
        """解析后的完整面板参数（范围 / limits / clip / ratio / transform）。"""
        resolved = {axis: self._axis_panel(scales, axis) for axis in AXES}
        params = PanelParams(
            x_range=resolved["x"].range,
            y_range=resolved["y"].range,
            x_limits=resolved["x"].limits,
            y_limits=resolved["y"].limits,
            clip=self.clip,
            ratio=self._ratio(),
            coord=self.name,
            discrete=MappingProxyType({axis: resolved[axis].discrete for axis in AXES}),
            reverse=MappingProxyType({axis: self._reverse_flag(axis) for axis in AXES}),
            trans=MappingProxyType(self._transforms()),
            cont_ranges=MappingProxyType({axis: resolved[axis].continuous for axis in AXES}),
        )
        return self._decorate(params)

    def _decorate(self, params: PanelParams) -> PanelParams:
        """子类追加自己那份几何（flip / polar / radial / sf）。"""
        return params

    def _transforms(self) -> dict[str, CoordTransform]:
        return {}

    def _coord_limit(self, axis: str) -> Any:
        """该轴的 coord limits（`xlim` / `ylim`）；radial 用 thetalim / rlim 覆盖。"""
        return getattr(self, f"{axis}lim")

    def _axis_panel(self, scales: ScaleSet, axis: str) -> _AxisPanel:
        scale = scales.scale(axis)
        limits = scales.limits(axis)
        discrete = bool(scale is not None and getattr(scale, "discrete", False))
        base = _base_limits(limits, discrete) if scale is not None else (0.0, 1.0)
        coord_limit = self._coord_limit(axis)
        if coord_limit is not None:
            base = _coord_limits(coord_limit, limits, discrete, axis)
            base = _transform_coord_limits(base, coord_limit, scale, discrete, axis)
        expansion = self._expansion(scale, axis)
        spec = self._transforms().get(axis)
        if spec is not None and spec.name != "identity":
            # 上游 `expand_limits_continuous_trans()`：先变换、再在变换后的空间
            # expand；`continuous_range` 是反变换回标度空间的结果（断点用）。
            transformed = spec.apply(np.array(base, dtype=np.float64))
            if spec.domain_error(transformed):
                raise CoordError(
                    f"{axis} 轴范围 {base!r} 在 coord_trans({spec.name!r}) 下不是有限值："
                    "换一个定义域内的范围，或先给标度设 limits"
                )
            low, high = sorted((float(transformed[0]), float(transformed[1])))
            mapped = expand_range(low, high, expansion.mult, expansion.add)
            continuous = tuple(
                float(value) for value in np.sort(spec.invert(np.array(mapped, dtype=np.float64)))
            )
            return _AxisPanel(limits=base, range=mapped, continuous=continuous, discrete=discrete)
        low, high = expand_range(base[0], base[1], expansion.mult, expansion.add)
        return _AxisPanel(limits=base, range=(low, high), continuous=(low, high), discrete=discrete)

    def _default_expansion(self, scale: ScaleBase | None, axis: str) -> Expansion:
        """标度没有显式 `expand` 时的默认展开（上游 `default_expansion()`）。

        cartesian / trans 用标度自己的默认（连续 5% / 离散 add 0.6）；
        `coord_polar` 覆盖为 theta `add = 0.5`、r 不展开（见 :class:`PolarCoord`）。
        """
        del axis
        return scale.expansion if scale is not None else CONTINUOUS_EXPANSION

    def _expansion(self, scale: ScaleBase | None, axis: str = "x") -> Expansion:
        default = self._default_expansion(scale, axis)
        if self.expand is False:
            return Expansion((0.0, 0.0), (0.0, 0.0))
        if self.expand is not None and self.expand is not True:
            return Expansion.from_param(self.expand, default=default)
        explicit = None if scale is None else scale.params.get("expand")
        if explicit is not None:
            return Expansion.from_param(explicit, default=default)
        return default

    def _reverse_flag(self, axis: str) -> bool:
        value = str(self.reverse or "none")
        if value in ("xy", "yx"):
            return True
        return value == axis

    def _ratio(self) -> float | None:
        return None

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"{type(self).__name__}(clip={self.clip!r})"


@dataclass(frozen=True, slots=True)
class CartesianCoord(CoordBase):
    """`coord_cartesian()`：范围只影响显示，不删数据（越界点裁在面板外）。

    `ratio` 是 4.0.3 新加的（`coord_equal()` / `coord_fixed()` 都只是它的糖）。
    """

    ratio: float | None = None
    name: str = field(default="cartesian", init=False)

    def __post_init__(self) -> None:
        CoordBase.__post_init__(self)
        if self.ratio is not None:
            value = float(self.ratio)
            if not math.isfinite(value) or value <= 0:
                raise CoordError(f"{self.name} 的 ratio 必须是正有限数，收到 {self.ratio!r}")
            object.__setattr__(self, "ratio", value)

    def _ratio(self) -> float | None:
        return self.ratio


@dataclass(frozen=True, slots=True)
class FixedCoord(CartesianCoord):
    """`coord_fixed(ratio = 1)`：面板物理高/宽 = `ratio × y 范围 / x 范围`。"""

    ratio: float = 1.0
    name: str = field(default="fixed", init=False)


@dataclass(frozen=True, slots=True)
class EqualCoord(CartesianCoord):
    """`coord_equal(ratio = 1)`：与 `coord_fixed(ratio = 1)` 同一口径。"""

    ratio: float = 1.0
    name: str = field(default="equal", init=False)


@dataclass(frozen=True, slots=True)
class FlipCoord(CartesianCoord):
    """`coord_flip()`：坐标轴互换（`flip_axis_labels` + 翻转 panel_params）。"""

    name: str = field(default="flip", init=False)

    def panel_params(self, scales: ScaleSet) -> PanelParams:
        # slots dataclass 会重建类，零参 super() 拿不到新类；显式走基类。
        base = CartesianCoord.panel_params(self, scales)
        return replace(
            base,
            x_range=base.y_range,
            y_range=base.x_range,
            x_limits=base.y_limits,
            y_limits=base.x_limits,
            discrete=MappingProxyType(
                {"x": base.discrete.get("y", False), "y": base.discrete.get("x", False)}
            ),
            cont_ranges=MappingProxyType(
                {
                    "x": base.continuous_ranges["y"],
                    "y": base.continuous_ranges["x"],
                }
            ),
            flipped=True,
        )


@dataclass(frozen=True, slots=True)
class TransCoord(CoordBase):
    """`coord_trans()` / `coord_transform()`：逐轴变换，变换在标度空间之后。"""

    x: Any = "identity"
    y: Any = "identity"
    name: str = field(default="trans", init=False)

    def __post_init__(self) -> None:
        CoordBase.__post_init__(self)
        object.__setattr__(self, "x", as_coord_transform(self.x))
        object.__setattr__(self, "y", as_coord_transform(self.y))

    def _transforms(self) -> dict[str, CoordTransform]:
        return {"x": self.x, "y": self.y}


@dataclass(frozen=True, slots=True)
class PolarCoord(CoordBase):
    """`coord_polar(theta = "x", start = 0, direction = 1, clip = "on")`。"""

    theta: str = "x"
    start: float = 0.0
    direction: float = 1.0
    name: str = field(default="polar", init=False)

    def __post_init__(self) -> None:
        CoordBase.__post_init__(self)
        if self.theta not in ("x", "y"):
            raise CoordError(f"coord_polar 的 theta 只能是 'x' / 'y'，收到 {self.theta!r}")
        if not math.isfinite(float(self.start)):
            raise CoordError(f"coord_polar 的 start 必须是有限数，收到 {self.start!r}")
        if float(self.direction) == 0:
            raise CoordError("coord_polar 的 direction 不能是 0（R 用 `sign(direction)`）")
        object.__setattr__(self, "start", float(self.start))
        object.__setattr__(self, "direction", float(np.sign(float(self.direction))))

    def _default_expansion(self, scale: ScaleBase | None, axis: str) -> Expansion:
        """`CoordPolar$setup_panel_params()` 的展开：theta 轴离散时 `add = 0.5`。

        上游对 theta 轴传 `default_expansion(scale, c(0, 0.5), c(0, 0))`（离散
        `add = 0.5`、连续不展开），对 r 轴传 `c(0, 0) / c(0, 0)`（都不展开）。
        `coord_polar(theta = "y")` 时离散的 x 是 **r 轴**，所以它不展开——
        `r.range` 仍是 `1..n`（SIL-729 的 R 夹具 `polar_y` 钉住这一点）。
        """
        if axis == self.theta and scale is not None and getattr(scale, "discrete", False):
            return Expansion((0.0, 0.0), (0.5, 0.5))
        return Expansion((0.0, 0.0), (0.0, 0.0))

    def _decorate(self, params: PanelParams) -> PanelParams:
        theta_axis = self.theta
        theta_range = params._range_for(theta_axis)
        r_range = params._range_for("y" if theta_axis == "x" else "x")
        arc = (self.start, self.start + _TWO_PI)
        polar = PolarGeometry(
            theta_axis=theta_axis,
            theta_range=theta_range,
            r_range=r_range,
            start=self.start,
            direction=self.direction,
            arc=arc,
            inner_radius=(0.0, 0.4),
            bbox=polar_bbox(arc, (0.0, 0.4)),
            axis_rotation=arc,
            radial=False,
        )
        return replace(params, polar=polar)


@dataclass(frozen=True, slots=True)
class RadialCoord(CoordBase):
    """`coord_radial()`：4.0 的极坐标替代品（partial arc / inner radius / r 轴位置）。

    参数与上游同名：`theta` / `start` / `end` / `thetalim` / `rlim` / `expand` /
    `direction`（已弃用，等价于 `reverse`）/ `clip` / `r.axis.inside` /
    `rotate.angle` / `inner.radius` / `reverse`。
    """

    theta: str = "x"
    start: float = 0.0
    end: float | None = None
    #: R 4.0.3 的 `coord_radial()` 默认 `clip = "off"`（coord_polar 是 "on"）。
    clip: str = "off"
    thetalim: Any = None
    rlim: Any = None
    direction: float | None = None
    r_axis_inside: bool | float | None = None
    rotate_angle: bool = False
    inner_radius: float = 0.0
    name: str = field(default="radial", init=False)

    def __post_init__(self) -> None:
        CoordBase.__post_init__(self)
        if self.theta not in ("x", "y"):
            raise CoordError(f"coord_radial 的 theta 只能是 'x' / 'y'，收到 {self.theta!r}")
        if self.reverse not in ("theta", "thetar", "r", "none"):
            raise CoordError(
                f"coord_radial 的 reverse 只能是 'theta' / 'thetar' / 'r' / 'none'，"
                f"收到 {self.reverse!r}"
            )
        if not math.isfinite(float(self.start)):
            raise CoordError(f"coord_radial 的 start 必须是有限数，收到 {self.start!r}")
        if self.end is not None and not math.isfinite(float(self.end)):
            raise CoordError(f"coord_radial 的 end 必须是有限数，收到 {self.end!r}")
        radius = float(self.inner_radius)
        if not math.isfinite(radius) or not 0.0 <= radius <= 1.0:
            raise CoordError(
                f"coord_radial 的 inner.radius 必须在 [0, 1]，收到 {self.inner_radius!r}"
            )
        object.__setattr__(self, "start", float(self.start))
        object.__setattr__(self, "inner_radius", radius)
        for axis in ("thetalim", "rlim"):
            value = getattr(self, axis)
            if value is not None and (isinstance(value, (str, bytes)) or len(tuple(value)) != 2):
                raise CoordError(f"coord_radial 的 {axis} 必须是 2 元序列，收到 {value!r}")
        if self.direction is not None:
            # 4.0.3：`direction` 已弃用（`deprecate_warn0`），等价写法是
            # `reverse`；这里只接受、不参与映射（与上游一致）。
            pass

    def _arc(self) -> tuple[float, float]:
        start = self.start
        end = start + _TWO_PI if self.end is None else float(self.end)
        arc = [start, end]
        if arc[0] > arc[1]:
            n_rotate = math.floor((arc[0] - arc[1]) / _TWO_PI) + 1
            arc[0] -= n_rotate * _TWO_PI
        if self.reverse in ("thetar", "theta"):
            arc = [arc[1], arc[0]]
        return (float(arc[0]), float(arc[1]))

    def _inner(self) -> tuple[float, float]:
        inner = (self.inner_radius * 0.4, 0.4)
        if self.reverse in ("thetar", "r"):
            inner = (inner[1], inner[0])
        return inner

    _REVERSE_VALUES = ("none", "theta", "thetar", "r")

    def _coord_limit(self, axis: str) -> Any:
        if axis == self.theta:
            return self.thetalim
        return self.rlim

    def _r_axis_inside(self, arc: tuple[float, float]) -> bool:
        if self.r_axis_inside is None:
            return not (abs(arc[1] - arc[0]) >= 1.999 * math.pi)
        return bool(self.r_axis_inside)

    def _decorate(self, params: PanelParams) -> PanelParams:
        theta_axis = self.theta
        theta_range = params._range_for(theta_axis)
        r_range = params._range_for("y" if theta_axis == "x" else "x")
        arc = self._arc()
        inner = self._inner()
        bbox = polar_bbox(arc, inner)
        axis_rotation: tuple[float, float] = (arc[0], arc[1])
        if isinstance(self.r_axis_inside, (int, float)) and not isinstance(
            self.r_axis_inside, bool
        ):
            # 数值形式：r 轴沿指定 theta 角度摆放（上游 `axis_rotation`）。
            angle = theta_rescale(np.array([float(self.r_axis_inside)]), theta_range, arc, 1.0)[0]
            axis_rotation = (float(angle), float(angle))
        polar = PolarGeometry(
            theta_axis=theta_axis,
            theta_range=theta_range,
            r_range=r_range,
            start=arc[0],
            direction=1.0,
            arc=arc,
            inner_radius=inner,
            bbox=bbox,
            axis_rotation=axis_rotation,
            radial=True,
            r_axis_inside=self._r_axis_inside(arc),
        )
        return replace(params, polar=polar)


@dataclass(frozen=True, slots=True)
class SfCoord(CoordBase):
    """`coord_sf()`：最小可用（identity 投影）。

    真正的投影 / graticule / sf 几何归 M3-2。这里 `crs` / `default_crs` /
    `datum` 只要给了非空值就报 :class:`CoordError`，消息点名 M3-2，不静默
    当 identity 画错图。
    """

    crs: Any = None
    default_crs: Any = None
    datum: Any = None
    lims_method: str = "cross"
    ndiscr: int = 100
    name: str = field(default="sf", init=False)

    def __post_init__(self) -> None:
        CoordBase.__post_init__(self)
        requested = [
            name for name in ("crs", "default_crs", "datum") if getattr(self, name) is not None
        ]
        if requested:
            raise CoordError(
                f"coord_sf({', '.join(requested)}) 需要真实的空间投影，M2-1 只做注册与最小可用"
                "（identity 投影）；投影 / graticule / sf 几何归 M3-2，见 docs/notes/coord.md"
            )

    def _decorate(self, params: PanelParams) -> PanelParams:
        # CoordSf$aspect(): 非经纬度数据 ratio = 1 → 面板高/宽 = y 跨度 / x 跨度。
        return replace(params, ratio=1.0)


@dataclass(frozen=True, slots=True)
class MapCoord(CoordBase):
    """`coord_map()`：最小可用（只支持 `projection = "identity"`）。

    上游默认 `projection = "mercator"` 需要 mapproj；M2-1 只做注册，遇到真实
    投影报错并点名 M3-2。
    """

    projection: str = "mercator"
    parameters: Any = None
    orientation: Any = None
    name: str = field(default="map", init=False)

    def __post_init__(self) -> None:
        CoordBase.__post_init__(self)
        if str(self.projection) not in ("identity", "none"):
            raise CoordError(
                f"coord_map(projection = {self.projection!r}) 需要 mapproj 投影，M2-1 只做"
                '注册与最小可用（projection = "identity"）；真正的空间能力归 M3-2'
            )
        if self.orientation is not None:
            raise CoordError(f"coord_map(orientation = {self.orientation!r}) 尚未实现（M3-2）")

    def _decorate(self, params: PanelParams) -> PanelParams:
        return replace(params, ratio=1.0)


@dataclass(frozen=True, slots=True)
class QuickmapCoord(CoordBase):
    """`coord_quickmap()`：等距圆柱近似（纬度 `1/cos(lat)` 因子）。"""

    orientation: Any = None
    name: str = field(default="quickmap", init=False)

    def _decorate(self, params: PanelParams) -> PanelParams:
        ratio = _quickmap_ratio(params.x_range, params.y_range, self.orientation)
        return replace(params, ratio=ratio)


def _quickmap_ratio(
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    orientation: Any = None,
) -> float:
    """上游 `CoordQuickmap$aspect()`：`diff(y)/diff(x) * y.dist/x.dist`。

    `orientation = c(latitude, longitude, rotation)` 时以给定纬度为准，否则取
    面板中心的纬度；`dist_central_angle` 的一度经线长度比 = `cos(lat)`。
    """
    x_span = float(x_range[1]) - float(x_range[0])
    y_span = float(y_range[1]) - float(y_range[0])
    if x_span == 0:
        raise CoordError(f"x 范围跨度为 0（{x_range!r}），coord_quickmap 无法算比例")
    if y_span == 0:
        raise CoordError(f"y 范围跨度为 0（{y_range!r}），coord_quickmap 无法算比例")
    if orientation is not None:
        items = tuple(orientation)
        latitude = float(items[0]) if items else (y_range[0] + y_range[1]) / 2.0
    else:
        latitude = (y_range[0] + y_range[1]) / 2.0
    if abs(latitude) >= 90.0:
        raise CoordError(f"coord_quickmap 的纬度 {latitude:g} 不在 (-90, 90) 内")
    # 返回的是**比例因子**（纬度 θ 的一度经线比一度纬线短 cos θ）；
    # `PanelParams.aspect_ratio` 再乘 `y 跨度 / x 跨度`，与上游 aspect() 同序。
    return 1.0 / math.cos(math.radians(latitude))


@dataclass(frozen=True, slots=True)
class _AxisPanel:
    limits: tuple[float, float]
    range: tuple[float, float]
    continuous: tuple[float, float]
    discrete: bool


# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------

#: 每个坐标系认的参数（其余直接报错，与 R 的 unused argument 一致）。
_COORD_PARAMS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "cartesian": frozenset({"xlim", "ylim", "expand", "clip", "reverse", "ratio", "default"}),
        "fixed": frozenset({"xlim", "ylim", "expand", "clip", "reverse", "ratio", "default"}),
        "equal": frozenset({"xlim", "ylim", "expand", "clip", "reverse", "ratio", "default"}),
        "flip": frozenset({"xlim", "ylim", "expand", "clip", "reverse", "ratio", "default"}),
        "trans": frozenset({"x", "y", "xlim", "ylim", "limx", "limy", "expand", "clip", "reverse"}),
        "transform": frozenset(
            {"x", "y", "xlim", "ylim", "limx", "limy", "expand", "clip", "reverse"}
        ),
        "polar": frozenset({"theta", "start", "direction", "clip"}),
        "radial": frozenset(
            {
                "theta",
                "start",
                "end",
                "thetalim",
                "rlim",
                "expand",
                "direction",
                "clip",
                "r.axis.inside",
                "r_axis_inside",
                "rotate.angle",
                "rotate_angle",
                "inner.radius",
                "reverse",
            }
        ),
        "sf": frozenset(
            {
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
            }
        ),
        "map": frozenset(
            {"projection", "parameters", "orientation", "xlim", "ylim", "clip", "expand"}
        ),
        "quickmap": frozenset({"xlim", "ylim", "expand", "clip", "orientation", "reverse"}),
    }
)

#: 实现的坐标名（`coord_from_component` 的注册表）。
COORD_IMPLEMENTATIONS: Mapping[str, type[CoordBase]] = MappingProxyType(
    {
        "cartesian": CartesianCoord,
        "fixed": FixedCoord,
        "equal": EqualCoord,
        "flip": FlipCoord,
        "trans": TransCoord,
        "transform": TransCoord,
        "polar": PolarCoord,
        "radial": RadialCoord,
        "sf": SfCoord,
        "map": MapCoord,
        "quickmap": QuickmapCoord,
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
            f"坐标系 {name!r} 尚未实现（已实现：{', '.join(sorted(COORD_IMPLEMENTATIONS))}）"
        )
    unknown = set(component.params) - _COORD_PARAMS[name]
    params = dict(component.params)
    # 上游的弃用别名在这里归一到现行名字。
    for old, new in (("limx", "xlim"), ("limy", "ylim")):
        if old in params:
            if new in params:
                raise CoordError(f"coord_{name}() 同时给了 {new} 与已弃用的 {old}，只留一个")
            params[new] = params.pop(old)
    # Python 的关键字参数写不出点号，underscore 写法视同上游的 dotted 名。
    for old, new in (
        ("r_axis_inside", "r.axis.inside"),
        ("rotate_angle", "rotate.angle"),
        ("inner_radius", "inner.radius"),
        ("label_graticule", "label_graticule"),
    ):
        if old in params and new in _COORD_PARAMS[name]:
            if new in params:
                raise CoordError(f"coord_{name}() 同时给了 {new} 与 {old}，只留一个")
            params[new] = params.pop(old)
    unknown = set(params) - _COORD_PARAMS[name]
    if unknown:
        raise CoordError(
            f"coord_{name}() 不认识参数：{', '.join(sorted(unknown))}；"
            f"可用：{', '.join(sorted(_COORD_PARAMS[name]))}"
        )
    if name == "trans" or name == "transform":
        params.setdefault("x", "identity")
        params.setdefault("y", "identity")
    if name == "radial":
        params.pop("direction", None)
    if name == "map":
        params.pop("parameters", None)
    if "default" in params:
        params.pop("default")
    # dataclass 的字段名只能是标识符：上游的点号名在这里折成下划线。
    fields = {
        "inner.radius": "inner_radius",
        "r.axis.inside": "r_axis_inside",
        "rotate.angle": "rotate_angle",
    }
    kwargs = {fields.get(key, key): value for key, value in params.items()}
    return COORD_IMPLEMENTATIONS[name](**kwargs)


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


def _valid_reverse(value: Any, allowed: Sequence[str] = ("none", "x", "y", "xy", "yx")) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    return str(value).lower() in allowed


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
    """coord limits → 标度空间（R 4.0.3 `expand_limits_scale()` 的第一步）。"""
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
# coord_munch：非线性坐标下的逐边细分
# ---------------------------------------------------------------------------


def coord_munch(
    panel: PanelParams,
    table: ColumnTable,
    *,
    x: str = "x",
    y: str = "y",
    group: str = "group",
    segment_length: float = 0.01,
    is_closed: bool = False,
) -> ColumnTable:
    """`coord_munch()`（上游 `R/coord-munch.R`）：把折线 / 多边形按 `segment_length`
    细分后再做坐标变换，让极坐标下的边变成弧。

    - 线性坐标直接返回 `x` / `y` 两列的 npc（不做细分，与上游
      `if (coord$is_linear()) return(coord$transform(data, range))` 一致）；
    - 非线性坐标按**数据空间**的归一化距离（除以 x / y 面板跨度）细分，再逐点
      `project_xy()`；`is_closed=True` 时先闭合成多边形；
    - 返回值是只含 `x` / `y`（+ `group`）的 npc 表，供 rect / polygon 图层画。

    这是 geom 侧唯一的极坐标适配入口——geom 不判断 coord 名字，只问
    `panel.is_linear`。
    """
    if not isinstance(table, ColumnTable):
        raise TypeError(f"coord_munch 需要 ColumnTable，收到 {type(table).__name__}")
    if x not in table or y not in table:
        raise CoordError(f"coord_munch 需要 {x!r} / {y!r} 两列，数据里是 {table.names!r}")
    xs = _values(table.column(x))
    if y in table:
        ys = _values(table.column(y))
    else:
        ys = np.zeros_like(xs)
    if group in table:
        keys = [str(item) for item in table.column(group).values.tolist()]
    else:
        keys = ["1"] * table.nrows
    if not panel.is_linear:
        xs, ys, keys = _munch_points(
            panel, xs, ys, keys, segment_length=segment_length, is_closed=is_closed
        )
    px, py = panel.project_xy(xs, ys)
    columns: list[tuple[str, Column]] = [
        ("x", Column("float", px)),
        ("y", Column("float", py)),
    ]
    if keys:
        columns.append(("group", Column("str", np.array(keys, dtype=object))))
    return ColumnTable(columns, nrows=int(px.size))


def _munch_points(
    panel: PanelParams,
    xs: np.ndarray,
    ys: np.ndarray,
    keys: list[str],
    *,
    segment_length: float,
    is_closed: bool,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """按组、按连续段细分；距离用面板跨度归一化（上游 `coord$distance()`）。"""
    if not (math.isfinite(float(segment_length)) and float(segment_length) > 0):
        raise CoordError(f"segment_length 必须是正有限数，收到 {segment_length!r}")
    x_span = panel.x_range[1] - panel.x_range[0]
    y_span = panel.y_range[1] - panel.y_range[0]
    keep_x: list[float] = []
    keep_y: list[float] = []
    keep_key: list[str] = []
    start = 0
    for index in range(1, len(keys) + 1):
        if index < len(keys) and keys[index] == keys[start]:
            continue
        key = keys[start]
        gx = xs[start:index].tolist()
        gy = ys[start:index].tolist()
        if is_closed and len(gx) >= 2:
            gx.append(gx[0])
            gy.append(gy[0])
        if gx:
            keep_x.append(gx[0])
            keep_y.append(gy[0])
            keep_key.append(key)
        pairs = zip(
            zip(gx[:-1], gy[:-1], strict=True), zip(gx[1:], gy[1:], strict=True), strict=True
        )
        for (x0, y0), (x1, y1) in pairs:
            if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
                keep_x.append(x1)
                keep_y.append(y1)
                keep_key.append(key)
                continue
            distance = math.hypot((x1 - x0) / x_span, (y1 - y0) / y_span)
            steps = max(1, math.ceil(distance / float(segment_length)))
            for step in range(1, steps + 1):
                ratio = step / steps
                keep_x.append(x0 + (x1 - x0) * ratio)
                keep_y.append(y0 + (y1 - y0) * ratio)
                keep_key.append(key)
        start = index
    return (
        np.asarray(keep_x, dtype=np.float64),
        np.asarray(keep_y, dtype=np.float64),
        keep_key,
    )


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
    非线性的 `coord_trans` / 极坐标不按数据范围判定（R 也不删），直接给 0。
    """
    counts = {axis: 0 for axis in AXES}
    if not panel.is_linear:
        return MappingProxyType(counts)
    for table in tables:
        for axis in AXES:
            source = swapped_axis(axis) if panel.flipped else axis
            if source not in table.names:
                continue
            column = table.column(source)
            if column.kind not in _NUMERIC_KINDS:
                continue
            low, high = panel._limits_for(axis)
            values = np.asarray(column.values, dtype=np.float64)
            finite = np.isfinite(values) & ~np.asarray(column.na_mask, dtype=bool)
            outside = finite & ((values < low) | (values > high))
            counts[axis] += int(np.count_nonzero(outside))
    return MappingProxyType(counts)


def swapped_axis(axis: str) -> str:
    """`x` ↔ `y`（`coord_flip` 的数据列对调）。"""
    return "y" if axis == "x" else "x"


def count_dropped(tables: Iterable[ColumnTable]) -> Mapping[str, int]:
    """按轴统计已经是 NA 的值数（原始 NA + 标度 `oob = censor` 丢掉的值）。

    这是**按轴**的口径；同一行 x、y 都缺会各记一次，所以
    `sum(count_dropped(...).values())` 不等于 R 的 "Removed N rows"——
    行级计数用 :func:`count_rows_dropped`。
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

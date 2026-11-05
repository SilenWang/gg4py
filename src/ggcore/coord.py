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
from ggcore.munch import munch_steps
from ggcore.scales import (
    CONTINUOUS_EXPANSION,
    Expansion,
    ScaleBase,
    ScaleSet,
    expand_range,
)
from ggcore.sf import (
    CRS,
    GraticuleLine,
    SfError,
    calc_limits_bbox,
    st_crs,
    st_graticule,
    st_transform_xy,
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
_NUMERIC_KINDS = frozenset({"float", "int", "bool", "datetime", "date", "timedelta"})

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

    **出口统一量化**：`apply()` / `invert()` 在返回前把结果舍到固定十进制网格
    （:data:`TRANSFORM_DECIMALS`）。变换结果会直接参与「断点是否落在范围内」这类
    **离散**判定与面板范围计算，宿主 libm / numpy 版本的末位差足以让
    `log10(1000)` 落在 3.0 的两侧，从而多画或少画一个刻度（SIL-824 返工）。
    子类只实现 `_apply()` / `_invert()`，量化口径只有这一处。
    """

    name: str = "identity"

    def apply(self, values: Any) -> np.ndarray:
        return _canonical_values(self._apply(values))

    def invert(self, values: Any) -> np.ndarray:
        return _canonical_values(self._invert(values))

    def _apply(self, values: Any) -> np.ndarray:
        return np.asarray(values, dtype=np.float64)

    def _invert(self, values: Any) -> np.ndarray:
        return np.asarray(values, dtype=np.float64)

    def domain_error(self, values: np.ndarray) -> bool:
        """变换后是否出现非有限值（调用方据此报错，而不是静默画 NaN）。"""
        return bool(np.any(~np.isfinite(values)))


class _LogTransform(CoordTransform):
    """`log` / `log2` / `log10`。"""

    def _apply(self, values: Any) -> np.ndarray:
        data = np.asarray(values, dtype=np.float64)
        out = np.full(data.shape, np.nan)
        valid = np.isfinite(data) & (data > 0)
        out[valid] = np.log(data[valid]) / math.log(self._BASE)
        return out

    def _invert(self, values: Any) -> np.ndarray:
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

    def _apply(self, values: Any) -> np.ndarray:
        data = np.asarray(values, dtype=np.float64)
        out = np.full(data.shape, np.nan)
        valid = np.isfinite(data) & (data > -1)
        out[valid] = np.log1p(data[valid])
        return out

    def _invert(self, values: Any) -> np.ndarray:
        return np.expm1(np.asarray(values, dtype=np.float64))


@dataclass(frozen=True, slots=True)
class _Exp(CoordTransform):
    name: str = field(default="exp", init=False)

    def _apply(self, values: Any) -> np.ndarray:
        return np.exp(np.asarray(values, dtype=np.float64))

    def _invert(self, values: Any) -> np.ndarray:
        return np.log(np.asarray(values, dtype=np.float64))


@dataclass(frozen=True, slots=True)
class _Sqrt(CoordTransform):
    name: str = field(default="sqrt", init=False)

    def _apply(self, values: Any) -> np.ndarray:
        data = np.asarray(values, dtype=np.float64)
        out = np.full(data.shape, np.nan)
        valid = np.isfinite(data) & (data >= 0)
        out[valid] = np.sqrt(data[valid])
        return out

    def _invert(self, values: Any) -> np.ndarray:
        return np.square(np.asarray(values, dtype=np.float64))


@dataclass(frozen=True, slots=True)
class _Reciprocal(CoordTransform):
    name: str = field(default="reciprocal", init=False)

    def _apply(self, values: Any) -> np.ndarray:
        data = np.asarray(values, dtype=np.float64)
        out = np.full(data.shape, np.nan)
        valid = np.isfinite(data) & (data != 0)
        out[valid] = 1.0 / data[valid]
        return out

    def _invert(self, values: Any) -> np.ndarray:
        data = np.asarray(values, dtype=np.float64)
        out = np.full(data.shape, np.nan)
        valid = np.isfinite(data) & (data != 0)
        out[valid] = 1.0 / data[valid]
        return out


@dataclass(frozen=True, slots=True)
class _Reverse(CoordTransform):
    name: str = field(default="reverse", init=False)

    def _apply(self, values: Any) -> np.ndarray:
        return -np.asarray(values, dtype=np.float64)

    def _invert(self, values: Any) -> np.ndarray:
        return -np.asarray(values, dtype=np.float64)


class _CallableTransform(CoordTransform):
    """用户给的函数（`coord_trans(x = lambda v: ...)`）。"""

    name = "function"

    def __init__(self, forward: Callable[[np.ndarray], Any], name: str = "function") -> None:
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "_forward", forward)

    def _apply(self, values: Any) -> np.ndarray:
        return np.asarray(self._forward(np.asarray(values, dtype=np.float64)), dtype=np.float64)

    def _invert(self, values: Any) -> np.ndarray:
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


#: `coord_trans()` 变换结果的量化位数。变换（`log` / `exp` / `sqrt` / `reverse`）
#: 的输出会直接参与**离散**判定（断点是否落在范围内、面板范围的端点），宿主
#: libm / numpy 版本的末位差足以让 `log10(1000)` 落在 3.0 的两侧，从而多画或少画
#: 一个刻度（SIL-824 返工：`coord-transform-reversed` 在另一台机器上多出 "1000"）。
#: 12 位十进制（相对 1e-12）足够吸收 1 ULP 的 libm 噪声，又小于 R 对拍的 1e-12 容差。
TRANSFORM_DECIMALS = 12


def _canonical_values(values: Any, decimals: int = TRANSFORM_DECIMALS) -> np.ndarray:
    """把变换结果舍到固定十进制网格（纯 IEEE 运算；NaN / ±Inf 原样保留）。"""
    arr = np.asarray(values, dtype=np.float64)
    scale = float(10**decimals)
    finite = np.isfinite(arr)
    return np.where(finite, np.rint(arr * scale) / scale, arr)


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
    #: `coord_sf` 的空间几何：CRS / graticule / 轴刻度（线性坐标为 None）。
    sf: Any = None
    #: `coord_map` 的投影几何：投影参数 + 投影后的范围（其余坐标为 None）。
    map_geom: Any = None
    #: 面板在页面上的实际尺寸（英寸）：场景装配时填入，`geom_text` 的
    #: `check_overlap` 与 `geom_label` 的字号 → npc 换算要用它。构建设置里没有
    #: 它是正常的（构建阶段还不知道版式）。
    panel_width_in: float | None = None
    panel_height_in: float | None = None

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

    def backtransform_range(self) -> dict[str, tuple[float, float]]:
        """上游 `coord$backtransform_range(panel_params)`。

        线性坐标就是面板 `x.range` / `y.range`；`coord_trans` 再把映射空间的
        范围反变换回标度空间——`geom_abline` / `hline` / `vline` 的端点按这个
        范围算（先反变换、再画、再由 `coord$transform()` 投回屏幕）。
        """
        out: dict[str, tuple[float, float]] = {}
        for axis in ("x", "y"):
            low, high = self.x_range if axis == "x" else self.y_range
            spec = self.trans.get(axis)
            if spec is not None and spec.name != "identity":
                values = np.asarray(spec.invert(np.array([low, high])), dtype=np.float64)
                low, high = float(values[0]), float(values[1])
            out[axis] = (low, high)
        return out

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
        if self.sf is not None and getattr(self.sf, "default_crs", None) is not None:
            # `CoordSf$is_linear()`：用 default_crs 时非 sf 图层的直线要按经线 /
            # 纬线细分（coord_munch），所以不是线性坐标。
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
        if self.map_geom is not None:
            raise CoordError("coord_map 的映射是二维的：用 `transform_column()` / `project_xy()`")
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
        if self.map_geom is not None:
            boundary = self.x_range[0] if axis == "y" else self.y_range[0]
            if axis == "x":
                px, _ = self.map_geom.project(
                    np.array([float(value)], dtype=np.float64),
                    np.array([boundary], dtype=np.float64),
                )
            else:
                _, px = self.map_geom.project(
                    np.array([boundary], dtype=np.float64),
                    np.array([float(value)], dtype=np.float64),
                )
            return float(px[0])
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
        if self.map_geom is not None:
            return self.map_geom.project(xs, ys)
        if self.sf is not None:
            # `CoordSf$transform()`：非 sf 图层的 x / y 先投影到目标 CRS。
            source = self.sf.default_crs if self.sf.default_crs is not None else self.sf.crs
            inf_x = np.isinf(xs)
            inf_y = np.isinf(ys)
            xs, ys = st_transform_xy(xs, ys, self.sf.crs, source)
        else:
            inf_x = inf_y = None
        if self.flipped:
            px, py = self.npc("x", ys), self.npc("y", xs)
        else:
            px, py = self.npc("x", xs), self.npc("y", ys)
        if inf_x is not None:
            # `squish_infinite()`：±Inf 夹到面板两端（不是删掉）。
            px = np.where(inf_x, np.where(xs > 0, 1.0, 0.0), px)
            py = np.where(inf_y, np.where(ys > 0, 1.0, 0.0), py)
        return px, py

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
        if self.sf is not None or self.map_geom is not None:
            if source not in X_AES + Y_AES:
                raise CoordError(f"{name!r} 不是位置列，投影坐标无从映射")
            xs = _values(table.column("x")) if "x" in table else None
            ys = _values(table.column("y")) if "y" in table else None
            if xs is None or ys is None:
                raise CoordError("投影坐标需要 x / y 两列配对")
            px, py = self.project_xy(xs, ys)
            out = px if axis == "x" else py
            mask = ~np.isfinite(out)
            return Column("float", np.nan_to_num(out, nan=0.0), na_mask=mask)
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

    def panel_params(self, scales: ScaleSet, layers: Any = None) -> PanelParams:
        """解析后的完整面板参数（范围 / limits / clip / ratio / transform）。

        `layers` 是各层的 `scaled` 表（`ColumnTable` 序列），只有 `coord_sf`
        用它确定数据 CRS；其余坐标忽略。
        """
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
        if discrete and scale is not None:
            # 上游 `expand_limits_discrete_trans()` 的混合分支：离散水平的展开范围
            # 与 `range_c`（`geom_bar()` 的 xmin/xmax 这类连续列）取并集，但连续
            # 那段先 squish 到 coord limits（`expand_limits_continuous_trans(range_c,
            # expansion(0, 0), coord_limits)`）——`coord_cartesian(xlim = c("a","b"))`
            # 的面板因此仍是 `0.4..2.6`，不会把第三根柱子拉回来。
            observer = getattr(scales, "continuous_range", None)
            continuous = observer(axis) if observer is not None else None
            if continuous is not None:
                c_low = float(continuous[0])
                c_high = float(continuous[1])
                if coord_limit is not None:
                    c_low = max(c_low, base[0])
                    c_high = min(c_high, base[1])
                if c_high >= c_low:
                    low = min(low, c_low)
                    high = max(high, c_high)
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

    def panel_params(self, scales: ScaleSet, layers: Any = None) -> PanelParams:
        # slots dataclass 会重建类，零参 super() 拿不到新类；显式走基类。
        base = CartesianCoord.panel_params(self, scales, layers)
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
class SfGeometry:
    """`coord_sf()` 的解析结果（挂在 :attr:`PanelParams.sf` 上）。

    - `crs` / `default_crs`：目标坐标系与非 sf 图层的缺省坐标系；
    - `graticule`：面板 bbox 内的经纬网（坐标已在目标 CRS），面板网格与轴刻度
      都从它派生；
    - `ticks`：四个轴位的 `(目标 CRS 下的位置, 标签)`，由
      `view_scales_from_graticule()` 的贴边判定得到。
    """

    crs: CRS | None = None
    default_crs: CRS | None = None
    datum: CRS | None = None
    graticule: tuple[GraticuleLine, ...] = ()
    ticks: Mapping[str, tuple[tuple[float, str], ...]] = MappingProxyType({})
    #: 面板四条边上的经纬网标签（`CoordSf$labels()` 的等价物，SIL-839）。
    labels: tuple[SfGraticuleLabel, ...] = ()

    @property
    def is_longlat(self) -> bool:
        return self.crs is not None and self.crs.is_longlat


@dataclass(frozen=True, slots=True)
class MapGeometry:
    """`coord_map()` 的解析结果：投影参数 + 投影后的范围（`x.proj` / `y.proj`）。"""

    projection: str
    params: tuple[float, ...]
    orientation: tuple[float, float, float]
    x_proj: tuple[float, float]
    y_proj: tuple[float, float]

    def project(self, xs: Any, ys: Any) -> tuple[np.ndarray, np.ndarray]:
        from ggcore.sf import mapproject

        px, py = mapproject(
            xs, ys, projection=self.projection, params=self.params, orientation=self.orientation
        )
        x0, x1 = self.x_proj
        y0, y1 = self.y_proj
        return ((px - x0) / (x1 - x0), (py - y0) / (y1 - y0))


def _sf_data_crs(layers: Any) -> CRS | None:
    """第一层带 CRS 的几何列 → 数据 CRS（上游 `CoordSf$determine_crs()`）。"""
    if not layers:
        return None
    for table in layers:
        if table is None or "geometry" not in table:
            continue
        column = table.column("geometry")
        for item, missing in zip(
            column.values.tolist(), np.asarray(column.na_mask, dtype=bool).tolist(), strict=True
        ):
            if missing or item is None:
                continue
            crs = getattr(item, "crs", None)
            if crs is not None:
                return crs
    return None


def _sf_geometry_bbox(layers: Any, target: CRS | None) -> tuple[float, float, float, float] | None:
    """所有 sf 图层的几何 bbox（投到 `target` 后）。"""
    boxes: list[tuple[float, float, float, float]] = []
    if not layers:
        return None
    for table in layers:
        if table is None or "geometry" not in table:
            continue
        column = table.column("geometry")
        for item, missing in zip(
            column.values.tolist(), np.asarray(column.na_mask, dtype=bool).tolist(), strict=True
        ):
            if missing or item is None or item.is_empty:
                continue
            geometry = item if target is None or item.crs == target else item.transform(target)
            try:
                boxes.append(geometry.bbox())
            except SfError:  # pragma: no cover - 空几何
                continue
    if not boxes:
        return None
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _parse_label_axes(value: Any) -> Mapping[str, str]:
    """`parse_axes_labeling()`：`"--EN"` 或 `{"bottom": "E", ...}`。"""
    sides = ("top", "right", "bottom", "left")
    if value is None:
        return MappingProxyType(dict(zip(sides, "--EN", strict=True)))
    if isinstance(value, str):
        text = value
        if len(text) != 4:
            raise CoordError(f"label_axes 必须是 4 个字符（top/right/bottom/left），收到 {value!r}")
        return MappingProxyType(dict(zip(sides, text, strict=True)))
    if isinstance(value, Mapping):
        return MappingProxyType({side: str(value.get(side, "-")) for side in sides})
    raise CoordError(f"label_axes 只接受字符串或映射，收到 {type(value).__name__}")


def _parse_label_graticule(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(value)
    raise CoordError(f"label_graticule 只接受字符串，收到 {type(value).__name__}")


def _view_scale_ticks(
    lines: Sequence[GraticuleLine],
    axis: str,
    side: str,
    label: str,
    label_graticule: Sequence[str],
    ranges: Mapping[str, tuple[float, float]],
) -> tuple[tuple[float, str], ...]:
    """`view_scales_from_graticule()`：一条轴上的刻度位置 + 标签。"""
    orth = "y" if axis == "x" else "x"
    thres_low, thres_high = ranges[orth]
    span = thres_high - thres_low
    orth_start = np.array([getattr(line, f"{orth}_start") for line in lines], dtype=float)
    orth_end = np.array([getattr(line, f"{orth}_end") for line in lines], dtype=float)
    if side in ("top", "right"):
        threshold = thres_low + 0.999 * span
        accept_start = orth_start > threshold
        accept_end = orth_end > threshold
    else:
        threshold = thres_low + 0.001 * span
        accept_start = orth_start < threshold
        accept_end = orth_end < threshold
    if not bool(np.any(accept_start | accept_end)):
        eps = math.sqrt(2.2250738585072014e-308)
        subtract = 90.0 if side in ("top", "bottom") else 0.0
        straight = np.array(
            [
                abs(line.angle_start - subtract) < eps and abs(line.angle_end - subtract) < eps
                for line in lines
            ],
            dtype=bool,
        )
        accept_start = straight
        accept_end = np.zeros(len(lines), dtype=bool)

    types = np.array([line.type for line in lines], dtype=object)
    idx_start: list[int] = [int(i) for i in np.flatnonzero((types == label) & accept_start)]
    idx_end: list[int] = [int(i) for i in np.flatnonzero((types == label) & accept_end)]
    if "S" in label_graticule:
        idx_start += [int(i) for i in np.flatnonzero((types == "E") & accept_start)]
    if "N" in label_graticule:
        idx_end += [int(i) for i in np.flatnonzero((types == "E") & accept_end)]
    if "W" in label_graticule:
        idx_start += [int(i) for i in np.flatnonzero((types == "N") & accept_start)]
    if "E" in label_graticule:
        idx_end += [int(i) for i in np.flatnonzero((types == "N") & accept_end)]

    idx_start = list(dict.fromkeys(idx_start))
    idx_end = list(dict.fromkeys(idx_end))
    attr = "x" if axis == "x" else "y"
    positions = [getattr(lines[i], f"{attr}_start") for i in idx_start] + [
        getattr(lines[i], f"{attr}_end") for i in idx_end
    ]
    labels = [lines[i].label for i in idx_start] + [lines[i].label for i in idx_end]
    pairs = sorted(zip(positions, labels, strict=True), key=lambda item: item[0])
    return tuple((float(position), str(text)) for position, text in pairs)


def _sf_axis_ticks(
    lines: Sequence[GraticuleLine],
    ranges: Mapping[str, tuple[float, float]],
    label_axes: Mapping[str, str],
    label_graticule: Sequence[str],
) -> dict[str, tuple[tuple[float, str], ...]]:
    out: dict[str, tuple[tuple[float, str], ...]] = {}
    for side in ("bottom", "left", "top", "right"):
        axis = "x" if side in ("bottom", "top") else "y"
        # `label_axes` 是 "--EN" 时 top / right 的 label 是 "-"（没有主轴标签），
        # 但 `label_graticule = "NSWE"` 仍可以在这些边上加标签——上游
        # `view_scales_from_graticule()` 的两套来源是**相加**的，不能提前返回。
        label = label_axes.get(side, "-")
        out[side] = _view_scale_ticks(lines, axis, side, label, label_graticule, ranges)
    return out


@dataclass(frozen=True, slots=True)
class SfGraticuleLabel:
    """`CoordSf$labels()` 的一行：面板边界上的一个经纬网标签。

    与轴刻度（`_view_scale_ticks()` 返回的 `(position, text)`）不同，这里同时给出
    **两个坐标**与**该点切线角**——上游 `labels()` 的 data.frame 就是
    `x` / `y` / `label` / `angle_start` / `angle_end` 这些列。
    """

    x: float
    y: float
    label: str
    angle: float
    #: `"E"`（经线标签，贴上下边，走 `axis.text.x`）或 `"N"`（纬线，贴左右边，走 `axis.text.y`）。
    type: str = "E"


def _graticule_side_labels(
    lines: Sequence[GraticuleLine],
    axis: str,
    side: str,
    label_graticule: Sequence[str],
    ranges: Mapping[str, tuple[float, float]],
) -> list[SfGraticuleLabel]:
    """一条边上的标签：选线规则与 `_view_scale_ticks()` 完全一致。

    `label_graticule = "NSWE"` 的四条规则（上游 `view_scales_from_graticule()`）：
    经线（type `E`）走上下边、纬线（type `N`）走左右边，具体落在 `_start` 端还是
    `_end` 端由边的位置决定。
    """
    orth = "y" if axis == "x" else "x"
    thres_low, thres_high = ranges[orth]
    span = thres_high - thres_low
    orth_start = np.array([getattr(line, f"{orth}_start") for line in lines], dtype=float)
    orth_end = np.array([getattr(line, f"{orth}_end") for line in lines], dtype=float)
    if side in ("top", "right"):
        threshold = thres_low + 0.999 * span
        accept_start = orth_start > threshold
        accept_end = orth_end > threshold
    else:
        threshold = thres_low + 0.001 * span
        accept_start = orth_start < threshold
        accept_end = orth_end < threshold
    # `label_graticule` 的字母直接决定「哪条边由哪一类线出标签」（上游语义）：
    #   S → 下边收经线（E）的下端、N → 上边收经线的上端、
    #   W → 左边收纬线（N）的左端、E → 右边收纬线的右端。
    letter = {"bottom": "S", "top": "N", "left": "W", "right": "E"}[side]
    if letter not in label_graticule:
        return []
    types = np.array([line.type for line in lines], dtype=object)
    want = "E" if axis == "x" else "N"
    accept = accept_start if side in ("bottom", "left") else accept_end
    idx = [int(i) for i in np.flatnonzero((types == want) & accept)]
    use_start = side in ("bottom", "left")
    idx_start = idx if use_start else []
    idx_end = [] if use_start else idx
    rows = [
        SfGraticuleLabel(
            x=float(lines[i].x_start),
            y=float(lines[i].y_start),
            label=lines[i].label,
            angle=float(lines[i].angle_start),
            type=lines[i].type,
        )
        for i in idx_start
    ]
    rows += [
        SfGraticuleLabel(
            x=float(lines[i].x_end),
            y=float(lines[i].y_end),
            label=lines[i].label,
            angle=float(lines[i].angle_end),
            type=lines[i].type,
        )
        for i in idx_end
    ]
    rows.sort(key=lambda row: (row.x, row.y))
    return rows


def sf_graticule_labels(
    lines: Sequence[GraticuleLine],
    label_graticule: Sequence[str],
    ranges: Mapping[str, tuple[float, float]],
) -> tuple[SfGraticuleLabel, ...]:
    """`CoordSf$labels(panel_params)`：面板四条边上的经纬网标签集合。

    返回的每一行是 `(x, y, label, angle)`——`x` / `y` 在目标 CRS 的坐标里
    （与 `expected.svg` 的 `<text x= y= transform=...>` 对位时再投到 npc），
    `angle` 是该端点的切线方向（度）。上游同一张表还带 `hjust` / `vjust`，
    等绘制那一步再补。
    """
    out: list[SfGraticuleLabel] = []
    for side in ("bottom", "left", "top", "right"):
        axis = "x" if side in ("bottom", "top") else "y"
        out.extend(_graticule_side_labels(lines, axis, side, label_graticule, ranges))
    return tuple(out)


@dataclass(frozen=True, slots=True)
class SfCoord(CoordBase):
    """`coord_sf()`：真实空间坐标（EPSG:4326 / 3857 / 3347）。

    与 `R/coord-sf.R` 对齐的三件事：

    1. **CRS**：`crs` 缺省取第一层几何的 CRS；`default_crs` 是非 sf 图层的
       坐标系（NULL = 与 `crs` 相同）；
    2. **范围**：比例尺 limits 先按 `lims_method`（cross / box / orthogonal /
       geometry_bbox）投到 `crs`，再 5% expand；经纬度数据的面板比例是
       `1/cos(中心纬度)`；
    3. **graticule**：面板 bbox 内的经纬网，grid 与轴标签都从它派生（
       `st_graticule()` 的移植在 :mod:`ggcore.sf`）。
    """

    crs: Any = None
    default_crs: Any = None
    datum: Any = 4326
    lims_method: str = "cross"
    label_graticule: Any = None
    label_axes: Any = None
    ndiscr: int = 100
    default: bool = False
    name: str = field(default="sf", init=False)

    def __post_init__(self) -> None:
        CoordBase.__post_init__(self)
        st_crs(self.crs) if self.crs is not None else None
        st_crs(self.default_crs) if self.default_crs is not None else None
        st_crs(self.datum) if self.datum is not None else None
        if self.lims_method not in ("cross", "box", "orthogonal", "geometry_bbox"):
            raise CoordError(
                f"lims_method 只能是 cross / box / orthogonal / geometry_bbox，"
                f"收到 {self.lims_method!r}"
            )
        _parse_label_axes(self.label_axes)
        _parse_label_graticule(self.label_graticule)
        if isinstance(self.ndiscr, bool) or int(self.ndiscr) < 2:
            raise CoordError(f"ndiscr 至少是 2，收到 {self.ndiscr!r}")

    # -- 参数 -------------------------------------------------------------

    def get_default_crs(self) -> CRS | None:
        return None if self.default_crs is None else st_crs(self.default_crs)

    def _label_axes(self) -> Mapping[str, str]:
        return _parse_label_axes(self.label_axes)

    def _label_graticule(self) -> tuple[str, ...]:
        value = self.label_graticule
        if value is None and self.label_axes is None:
            return ()
        return _parse_label_graticule(value)

    # -- 面板参数 ---------------------------------------------------------

    def panel_params(self, scales: ScaleSet, layers: Any = None) -> PanelParams:
        data_crs = _sf_data_crs(layers)
        target = st_crs(self.crs) if self.crs is not None else data_crs
        default = self.get_default_crs()
        scales_obj = {axis: scales.scale(axis) for axis in AXES}
        base: dict[str, tuple[float, float]] = {}
        for axis in AXES:
            scale = scales_obj[axis]
            if scale is not None and bool(getattr(scale, "discrete", False)):
                raise CoordError(
                    f"coord_sf 的 {axis} 轴需要连续位置标度；离散位置在空间坐标里没有意义"
                )
            coord_limit = getattr(self, f"{axis}lim")
            if coord_limit is not None:
                values = [float(value) for value in coord_limit]
                base[axis] = (min(values), max(values))
            else:
                limits = scales.limits(axis) if scale is not None else (0.0, 1.0)
                if limits is None or len(tuple(limits)) != 2:
                    limits = (0.0, 1.0)
                low, high = float(limits[0]), float(limits[1])
                base[axis] = (min(low, high), max(low, high))
        source = default if default is not None else target
        if target is not None and source is not None and target != source:
            xs, ys = calc_limits_bbox(base["x"], base["y"], target, source, self.lims_method)
            finite = np.isfinite(xs) & np.isfinite(ys)
            if not bool(finite.any()):
                raise CoordError(
                    "coord_sf 的 x/y limits 在投影后不是有限值；"
                    '考虑 lims_method = "geometry_bbox" 或 default_crs = None'
                )
            base["x"] = (float(np.min(xs[finite])), float(np.max(xs[finite])))
            base["y"] = (float(np.min(ys[finite])), float(np.max(ys[finite])))

        # 上游 `setup_panel_params()` 在「没有显式 limits」时把几何的 bbox 并进
        # 标度范围：投影后的 limits 只是近似（bbox 的四条边在非线性变换下不是
        # 直线），并上真实 bbox 才不会把图形切掉。
        if (
            target is not None
            and self.xlim is None
            and self.ylim is None
            and not self._has_explicit_limits(scales_obj)
        ):
            geometry_bbox = _sf_geometry_bbox(layers, target)
            if geometry_bbox is not None:
                xmin, ymin, xmax, ymax = geometry_bbox
                base["x"] = (min(base["x"][0], xmin), max(base["x"][1], xmax))
                base["y"] = (min(base["y"][0], ymin), max(base["y"][1], ymax))

        ranges: dict[str, tuple[float, float]] = {}
        for axis in AXES:
            expansion = self._expansion(scales_obj[axis], axis)
            low, high = expand_range(base[axis][0], base[axis][1], expansion.mult, expansion.add)
            if high <= low:
                low, high = low - 0.5, high + 0.5
            ranges[axis] = (low, high)

        lon, lat = self._explicit_breaks(scales_obj)
        lines = st_graticule(
            (ranges["x"][0], ranges["y"][0], ranges["x"][1], ranges["y"][1]),
            target,
            datum=self.datum,
            lon=lon,
            lat=lat,
            ndiscr=int(self.ndiscr),
        )
        ticks = _sf_axis_ticks(lines, ranges, self._label_axes(), self._label_graticule())
        ratio = 1.0
        if target is not None and target.is_longlat:
            mid = (ranges["y"][0] + ranges["y"][1]) / 2.0
            if abs(mid) >= 90.0:
                raise CoordError(f"coord_sf 的中心纬度 {mid:g} 不在 (-90, 90) 内")
            ratio = 1.0 / math.cos(math.radians(mid))

        params = PanelParams(
            x_range=ranges["x"],
            y_range=ranges["y"],
            x_limits=base["x"],
            y_limits=base["y"],
            clip=self.clip,
            ratio=ratio,
            coord="sf",
            discrete=MappingProxyType({"x": False, "y": False}),
            reverse=MappingProxyType({axis: self._reverse_flag(axis) for axis in AXES}),
            trans=MappingProxyType({}),
            cont_ranges=MappingProxyType(ranges),
        )
        return replace(
            params,
            sf=SfGeometry(
                crs=target,
                default_crs=default,
                datum=None if self.datum is None else st_crs(self.datum),
                graticule=tuple(lines),
                ticks=MappingProxyType(ticks),
                labels=sf_graticule_labels(lines, self._label_graticule(), ranges),
            ),
        )

    def _has_explicit_limits(self, scales_obj: Mapping[str, Any]) -> bool:
        """标度上有没有显式 `limits`（有就不把几何 bbox 并进范围）。"""
        for scale in scales_obj.values():
            if scale is not None and hasattr(scale, "_has_param") and scale._has_param("limits"):
                return True
        return False

    def _explicit_breaks(
        self, scales_obj: Mapping[str, Any]
    ) -> tuple[Sequence[float] | None, Sequence[float] | None]:
        """`sf_breaks()`：显式 breaks 视为经纬度；`breaks = NULL` → 该方向无线。"""
        out: list[Sequence[float] | None] = []
        for axis in AXES:
            scale = scales_obj[axis]
            if scale is None or not hasattr(scale, "_has_param"):
                out.append(None)
                continue
            if not scale._has_param("breaks"):
                out.append(None)
                continue
            value = scale._param("breaks")
            if value is None:
                out.append(())
                continue
            if callable(value):
                out.append(None)
                continue
            try:
                out.append(tuple(float(item) for item in value if item is not None))
            except (TypeError, ValueError):
                out.append(None)
        return out[0], out[1]

    def _decorate(self, params: PanelParams) -> PanelParams:  # pragma: no cover - 不走这里
        return params


@dataclass(frozen=True, slots=True)
class MapCoord(CoordBase):
    """`coord_map()`：mapproj 投影（M3-2 实现球面 mercator）。

    `CoordMap$setup_panel_params()` 的口径：在数据范围（经纬度）上铺 50×50 网格，
    用 `mapproj::mapproject()` 投影，投影后范围的宽高比就是面板比例；`transform()`
    把投影值 rescale 到 `x.proj` / `y.proj`。非 mercator 的投影（`gilbert` /
    `ortho` / `conic` …）需要 mapproj 全量，本仓不引入，显式报错。
    """

    projection: str = "mercator"
    parameters: Any = None
    orientation: Any = None
    name: str = field(default="map", init=False)

    def __post_init__(self) -> None:
        CoordBase.__post_init__(self)
        if str(self.projection) not in ("identity", "none", "mercator"):
            raise CoordError(
                f"coord_map(projection = {self.projection!r}) 尚未实现：M3-2 只移植了 "
                'mapproj 的 "mercator"（其余投影需要 mapproj 全量，见 docs/notes/sf.md）'
            )
        if self.orientation is not None:
            items = tuple(self.orientation)
            if len(items) != 3:
                raise CoordError(
                    f"orientation 必须是 (latitude, longitude, rotation) 三元组，收到 {items!r}"
                )

    def panel_params(self, scales: ScaleSet, layers: Any = None) -> PanelParams:
        from ggcore.sf import mapproject

        base = CoordBase.panel_params(self, scales)
        orientation = self._orientation(base)
        grid = np.linspace(0.0, 1.0, 50)
        xs = base.x_range[0] + (base.x_range[1] - base.x_range[0]) * np.repeat(grid, 50)
        ys = base.y_range[0] + (base.y_range[1] - base.y_range[0]) * np.tile(grid, 50)
        px, py = mapproject(
            xs,
            ys,
            projection=str(self.projection),
            params=tuple(self.parameters or ()),
            orientation=orientation,
        )
        finite = np.isfinite(px) & np.isfinite(py)
        if not bool(finite.any()):
            raise CoordError(
                f"coord_map({self.projection!r}) 投影失败：数据范围 {base.x_range!r} × "
                f"{base.y_range!r} 全部落在投影定义域外"
            )
        x_proj = (float(np.min(px[finite])), float(np.max(px[finite])))
        y_proj = (float(np.min(py[finite])), float(np.max(py[finite])))
        x_span = base.x_range[1] - base.x_range[0]
        y_span = base.y_range[1] - base.y_range[0]
        x_proj_span = x_proj[1] - x_proj[0]
        y_proj_span = y_proj[1] - y_proj[0]
        if x_proj_span == 0 or y_proj_span == 0 or x_span == 0 or y_span == 0:
            raise CoordError("coord_map 的投影范围退化成 0，无法计算面板比例")
        ratio = (y_proj_span / x_proj_span) * (x_span / y_span)
        geometry = MapGeometry(
            projection=str(self.projection),
            params=tuple(float(item) for item in (self.parameters or ())),
            orientation=tuple(float(item) for item in orientation),
            x_proj=x_proj,
            y_proj=y_proj,
        )
        return replace(base, ratio=ratio, map_geom=geometry)

    def _orientation(self, params: PanelParams) -> tuple[float, float, float]:
        if self.orientation is not None:
            items = tuple(float(item) for item in self.orientation)
            return (items[0], items[1], items[2])
        return (90.0, 0.0, (params.x_range[0] + params.x_range[1]) / 2.0)

    def _decorate(self, params: PanelParams) -> PanelParams:  # pragma: no cover - 走 panel_params
        return params


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
        builder = getattr(component, "build_coord", None)
        overridden = getattr(type(component), "build_coord", None) is not Coord.build_coord
        if callable(builder) and overridden:
            return builder()
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
            steps = munch_steps(distance, segment_length)
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

"""`align_scales()`：多图共享 scale limits / breaks + `coord_fixed` 适配（SIL-1000）。

aplot 的 `xlim2()` / `ylim2()` 在画布层统一各图的坐标范围，再靠 `adjust_coord()`
给面板补 `coord_fixed`，否则同列 / 同行的面板会因范围不同而错位。本模块复刻这
两件事，但落在**语法层**：返回 clone 后的 `ggplot` 列表，不改原对象。

    aligned = align_scales([p1, p2, p3], axis="xy", limits="union")
    aligned.plots            # 三张克隆图，x / y limits 已统一
    aligned.dropped          # {图号: {"x": 被裁行数, "y": ...}}
    aligned.coord_ratio      # 补上的 coord_fixed(ratio=)（没有就是 None）

口径：

- **`limits`**
  - `"union"`（默认）：各图训练范围的并集，尽量不丢数据；
  - `"first"`：复刻 aplot，以第一张（主图）的 limits 为准，超出部分按 `oob`
    处理（默认 `censor`，会丢行，行数记进 `dropped`）；
  - `"explicit"`：用 `x=` / `y=` 给的值；直接给 2 元数值序列或
    `{"x": (...), "y": (...)}` 也按显式处理。
- **连续 / 离散**：连续在**变换后空间**取范围再反映射回数据空间（`log10` /
  `reverse` / `sqrt` / 日期时间都适用，日期按底层数值——`date` 是天、`datetime`
  是秒）；离散统一的是 `levels`（并集保持首图顺序，显式值即新顺序），不是数值
  limits。
- **`axis` 指数据轴**：`coord_flip()` 只是把视觉轴换向，`axis="x"` 改的仍是
  数据 x；内部不做视觉轴映射。
- **`coord_fixed` 适配**：统一 limits 后，主图（或任一子图）有固定比例的，给
  其余没设比例的图补 `coord_fixed(ratio=同值)`；都没设就不动（不擅自改比例）。
- **不修改原图**：每张图 `clone()` 后再改 `scales` / `coordinates`。

非范围（见 SIL-998）：跨图共享同一个 scale 对象、free-scale 跨图对齐、双轴、
极坐标 / 固定纵横比的刻度对齐（只做 `coord_fixed` 适配）。
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import numpy as np

from ggcore.build import PlotBuild, build_plot, compute_aesthetics
from ggcore.components import Coord, Scale
from ggcore.coord import coord_from_component
from ggcore.data import Column
from ggcore.scales import ScaleBase, _string_values

__all__ = ["AlignedPlots", "align_scales"]

_AXES = ("x", "y")

#: 默认标度名：按 `ScaleBase.transform_` 的日历单位 / 变换选注册名。
_CONTINUOUS_NAMES = {
    "identity": "continuous",
    "date": "date",
    "time": "datetime",
    "hms": "time",
    "log10": "log10",
    "log": "log10",
    "sqrt": "sqrt",
    "reverse": "reverse",
}


@dataclass(frozen=True, slots=True)
class AlignedPlots:
    """`align_scales()` 的结果：可以直接当序列迭代，也可以读诊断字段。"""

    plots: tuple[Any, ...]
    #: 统一后的 limits（数据空间；离散是水平元组）。
    limits: Mapping[str, Any]
    #: `{图下标: {轴: 被裁行数}}`；`oob = "squish"` 时恒为 0。
    dropped: Mapping[int, Mapping[str, int]]
    #: 补上的 `coord_fixed(ratio=)`；没有任何图设比例时是 `None`。
    coord_ratio: float | None = None

    def __iter__(self) -> Iterator[Any]:
        return iter(self.plots)

    def __len__(self) -> int:
        return len(self.plots)

    def __getitem__(self, index: int) -> Any:
        return self.plots[index]


def align_scales(
    plots: Sequence[Any],
    *,
    axis: str = "xy",
    limits: Any = "union",
    x: Any = None,
    y: Any = None,
    adjust_coord: bool = True,
    oob: str = "censor",
) -> AlignedPlots:
    """统一多张图的 scale limits / levels，并按需补 `coord_fixed`。

    `plots` 是 `ggplot` 序列（也接受单张，自动包成列表）。返回值见
    :class:`AlignedPlots`。
    """
    items = list(plots) if isinstance(plots, (list, tuple)) else [plots]
    if not items:
        return AlignedPlots((), {}, {})
    axes = _parse_axis(axis)
    mode, explicit = _parse_limits(limits, x, y, axes)
    if oob not in ("censor", "squish"):
        raise ValueError(f"oob 只能是 'censor' 或 'squish'，收到 {oob!r}")

    builds = [build_plot(plot) for plot in items]
    unified: dict[str, Any] = {}
    for name in axes:
        collected = [_axis_limits(build, name) for build in builds]
        unified[name] = _combine(name, collected, mode, explicit)

    clones: list[Any] = []
    dropped: dict[int, dict[str, int]] = {}
    for index, (plot, build) in enumerate(zip(items, builds, strict=True)):
        clone = plot.clone()
        counts: dict[str, int] = {}
        for name in axes:
            target = unified[name]
            counts[name] = _count_dropped(plot, build, name, target, oob=oob)
            clone.scales[name] = _scale_component(
                plot, build, name, target, oob=oob if oob != "censor" else None
            )
        clones.append(clone)
        dropped[index] = counts

    ratio = None
    if adjust_coord:
        ratio = _coord_ratio(builds)
        if ratio is not None:
            clones = [_with_fixed_coord(plot, ratio) for plot in clones]

    return AlignedPlots(
        plots=tuple(clones),
        limits=MappingProxyType(dict(unified)),
        dropped=MappingProxyType(
            {index: MappingProxyType(dict(counts)) for index, counts in dropped.items()}
        ),
        coord_ratio=ratio,
    )


# ---------------------------------------------------------------------------
# 参数
# ---------------------------------------------------------------------------


def _parse_axis(axis: str) -> tuple[str, ...]:
    value = str(axis).lower()
    if value in ("x", "y"):
        return (value,)
    if set(value) == {"x", "y"} and len(value) == 2:
        return _AXES
    raise ValueError(f"axis 只能是 'x' / 'y' / 'xy'，收到 {axis!r}")


def _parse_limits(
    limits: Any, x: Any, y: Any, axes: tuple[str, ...]
) -> tuple[str, Mapping[str, Any]]:
    if isinstance(limits, str):
        mode = limits
        if mode not in ("union", "first", "explicit"):
            raise ValueError(f"limits 只能是 'union' / 'first' / 'explicit'，收到 {limits!r}")
        explicit = {name: value for name, value in (("x", x), ("y", y)) if value is not None}
        return mode, explicit
    if isinstance(limits, Mapping):
        unknown = set(limits) - set(_AXES)
        if unknown:
            raise ValueError(f"limits 映射里不认识的轴：{', '.join(sorted(unknown))}")
        return "explicit", {name: limits[name] for name in _AXES if name in limits}
    # 2 元数值序列：两条轴共用（“显式”）。
    values = tuple(limits)
    if len(values) != 2:
        raise ValueError(
            f"limits 必须是 2 元序列、映射或 'union'/'first'/'explicit'，收到 {limits!r}"
        )
    return "explicit", {name: values for name in axes}


# ---------------------------------------------------------------------------
# 范围
# ---------------------------------------------------------------------------


def _scale_of(build: PlotBuild, axis: str) -> ScaleBase | None:
    scale = build.scales.scale(axis)
    if scale is not None:
        return scale
    for panel in build.panels:
        candidate = panel.scales.scale(axis)
        if candidate is not None:
            return candidate
    return None


def _axis_limits(build: PlotBuild, axis: str) -> tuple[bool, Any]:
    """`(是否离散, 数据空间的 limits)`。

    连续标度的 `limits()` 给的是**变换后**的值（`scale_x_log10(limits = c(1,100))`
    → `0..2`），这里逆变换回数据空间，方便跨图取并集后重新写回 `limits`。
    """
    scale = _scale_of(build, axis)
    if scale is None:
        return False, None
    if getattr(scale, "discrete", False):
        return True, tuple(value for value in scale.limits() if value is not None)
    transformed = scale.limits()
    inverse = scale.transform_.inverse(np.asarray(transformed, dtype=np.float64))
    values = tuple(float(value) for value in np.asarray(inverse).reshape(-1)[:2])
    if len(values) != 2 or not all(np.isfinite(values)):
        return False, None
    return False, values


def _combine(
    axis: str,
    collected: Sequence[tuple[bool, Any]],
    mode: str,
    explicit: Mapping[str, Any],
) -> Any:
    if mode == "explicit":
        if axis not in explicit:
            # 没给显式值的轴退回并集：不擅自丢数据。
            return _union(axis, collected)
        return _explicit(axis, explicit[axis], collected)
    if mode == "first":
        _discrete, values = collected[0]
        if values is None:
            return _union(axis, collected)
        return values
    return _union(axis, collected)


def _union(axis: str, collected: Sequence[tuple[bool, Any]]) -> Any:
    present = [(discrete, values) for discrete, values in collected if values is not None]
    if not present:
        return None
    discrete = present[0][0]
    if discrete:
        out: list[Any] = []
        for _, values in present:
            for value in values:
                if value not in out:
                    out.append(value)
        return tuple(out)
    lows = [float(values[0]) for _, values in present]
    highs = [float(values[1]) for _, values in present]
    return (min(lows), max(highs))


def _explicit(axis: str, value: Any, collected: Sequence[tuple[bool, Any]]) -> Any:
    discrete = bool(collected[0][0]) if collected else False
    items = tuple(value)
    if discrete:
        return tuple(str(item) for item in items)
    if len(items) != 2:
        raise ValueError(f"{axis} 的显式 limits 必须是 2 元序列，收到 {value!r}")
    low, high = (float(items[0]), float(items[1]))
    if low > high:
        low, high = high, low
    return (low, high)


# ---------------------------------------------------------------------------
# 写回标度
# ---------------------------------------------------------------------------


def _scale_component(
    plot: Any, build: PlotBuild, axis: str, limits: Any, *, oob: str | None
) -> Scale:
    """构造该轴的 `components.Scale`：复用原注册名与参数，只换 limits。"""
    plot_scale = getattr(plot, "scales", {}).get(axis)
    name = getattr(plot_scale, "name", None)
    params: dict[str, Any] = dict(getattr(plot_scale, "params", {}) or {})
    discrete = bool(getattr(_scale_of(build, axis), "discrete", False))
    if name is None:
        name = _default_scale_name(build, axis)
    params["limits"] = limits
    # `oob` 只有连续标度认；离散标度把缺的水平直接当缺失。
    if oob is not None and not discrete:
        params["oob"] = oob
    return Scale(name=name, aesthetic=axis, params=params)


def _default_scale_name(build: PlotBuild, axis: str) -> str:
    scale = _scale_of(build, axis)
    if scale is None or getattr(scale, "discrete", False):
        return f"{axis}_discrete"
    transform = getattr(scale, "transform_", None)
    kind = getattr(transform, "date_kind", None)
    if kind:
        return f"{axis}_{_CONTINUOUS_NAMES.get(kind, 'continuous')}"
    suffix = _CONTINUOUS_NAMES.get(getattr(transform, "name", "identity"), "continuous")
    return f"{axis}_{suffix}"


# ---------------------------------------------------------------------------
# 裁剪计数
# ---------------------------------------------------------------------------


def _count_dropped(plot: Any, build: PlotBuild, axis: str, limits: Any, *, oob: str) -> int:
    """统一后的 limits 会裁掉多少行（`censor` 语义；`squish` 不裁）。

    计数用**原始数据**（`compute_aesthetics()` 的 `table`），不是
    `LayerBuild.aesthetics`：后者是位置标度映射之后的表，离散 x 已经变成
    1..n 的数值码，拿水平名去比会全判成越界。
    """
    if limits is None or oob != "censor":
        return 0
    scale = _scale_of(build, axis)
    if scale is None:
        return 0
    discrete = getattr(scale, "discrete", False)
    if discrete:
        allowed = set(limits)
        return sum(_count_discrete_dropped(column, allowed) for column in _raw_columns(plot, axis))
    transformed = np.asarray(scale.transform_limits(limits), dtype=np.float64)
    low, high = float(np.nanmin(transformed)), float(np.nanmax(transformed))
    total = 0
    for column in _raw_columns(plot, axis):
        values, _invalid = scale.transform_.transform(np.asarray(column.values, dtype=np.float64))
        values = np.asarray(values, dtype=np.float64)
        mask = np.asarray(column.na_mask, dtype=bool)
        finite = np.isfinite(values) & ~mask
        total += int(np.count_nonzero(finite & ((values < low) | (values > high))))
    return total


def _raw_columns(plot: Any, axis: str) -> list[Column]:
    """各层的原始美学表里该轴的列（未 transform、未 map）。"""
    out: list[Column] = []
    for index, layer in enumerate(getattr(plot, "layers", ())):
        table = compute_aesthetics(plot, layer, index).table
        if axis in table.names:
            out.append(table.column(axis))
    return out


def _count_discrete_dropped(column: Column, allowed: set[Any]) -> int:
    labels = _string_values(column)
    total = 0
    for value in labels.tolist():
        if value is not None and value not in allowed:
            total += 1
    return total


# ---------------------------------------------------------------------------
# coord_fixed 适配
# ---------------------------------------------------------------------------


def _coord_ratio(builds: Sequence[PlotBuild]) -> float | None:
    """主图的固定比例；主图没有就找任一子图的（aplot 的 `adjust_coord`）。"""
    for build in builds:
        coord = coord_from_component(build.coord) if build.coord is not None else None
        ratio = _ratio_of(coord)
        if ratio is not None:
            return ratio
    return None


def _ratio_of(coord: Any) -> float | None:
    if coord is None:
        return None
    getter = getattr(coord, "_ratio", None)
    if callable(getter):
        value = getter()
    else:
        value = getattr(coord, "ratio", None)
    return None if value is None else float(value)


def _with_fixed_coord(plot: Any, ratio: float) -> Any:
    component = plot.coordinates
    if _ratio_of(coord_from_component(component)) is not None:
        return plot
    params = dict(getattr(component, "params", {}) or {})
    params["ratio"] = ratio
    plot.coordinates = Coord(name="fixed", params=params)
    return plot

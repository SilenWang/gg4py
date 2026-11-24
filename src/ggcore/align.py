"""多图刻度对齐（M3-1 / SIL-1000）：统一 scale limits / breaks + `coord_fixed` 适配。

对应 aplot 0.3.2 的 `xlim2()` / `ylim2()`（`R/axis.R`）与 `adjust_coord()`
（`R/utilities.R`），但一次处理**一组**图，并按 issue 的口径把几个隐含语义写死：

- **pre-IR 层**：只克隆 `ggplot` 对象、替换 `plot.scales` 里的位置标度，不碰
  `build_plot()` / IR / gtable。组合层（`plot_gtable()` / `wrap_plots()`）在同一
  层消费它的返回值。
- **`axis` 指数据轴**：`axis="x"` 调的是 `aes(x=…)` 那条标度（`scale_x_*`）。
  `coord_flip()` 只交换**视觉**轴，不影响这里的选择；比例适配（`adjust_coord`）
  才按视觉轴取范围。
- **不修改原图**：`ggplot.clone()` 之后替换标度；原对象的 `scales` 一个字不变。
- **裁剪不静默**：`limits="first"` / `"explicit"` 会按 `oob` 丢数据。丢了多少
  行记在 `report.clipped_plots`（每图一条的跨轴行并集 = R 的 "Removed N rows"），
  每图每轴的明细在 `report.clipped`；`clipped_rows` / `rows_dropped()` 用并集口径，
  不会把同一行数两次。
- **变换在变换后的空间里取**：`scale_x_log10()` 的并集是 `log10(值)` 的并集，
  再反变换回数据空间写进 `limits=`；日期按底层数值（Date = 天，POSIXct = 秒）。

与 aplot 0.3.2 的关系（逐值对拍见 `docs/notes/align-scales.md`）：

- aplot 的 `xlim2()` 取 **视觉** x；这里 `axis` 是数据轴。`coord_flip()` 的图上
  两者方向相反（本仓语义有专门测试；flip 的对拍把 aplot 的 `x` 换算成本仓 `y`）。
- aplot 把 `xrange(region = "plot")`（**标度空间**的 limits，log10 下是 0..1）
  直接写回 `scale$limits`；这里先反变换回数据空间再写回，标度会再变换一次。
  两条路径的面板范围 / breaks / 裁剪行数一致（R 夹具逐项钉住）。
- aplot 的 `adjust_coord()` 用 `size`（layout 行列号）缩放 `coord_fixed` 的
  `ratio`；这里用 `coord_size=` 显式给，默认 1（布局层可传，见 stage 2）。
"""

from __future__ import annotations

import datetime as dt
import math
import warnings
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import numpy as np

from ggcore.build import PlotBuild, build_plot
from ggcore.components import Coord, Scale
from ggcore.coord import coord_from_component
from ggcore.scales import BinnedPositionScale, ScaleBase

__all__ = [
    "AXES",
    "AlignError",
    "AlignReport",
    "AlignedPlots",
    "AxisLimits",
    "ClipCount",
    "PlotClip",
    "align_scales",
]

AXES: tuple[str, ...] = ("x", "y")

#: `axis=` 的合法取值（`yx` 与 `xy` 同义，顺序按 x → y 处理）。
_AXIS_MODES = frozenset({"x", "y", "xy", "yx"})

#: `limits=` 的模式。
_LIMIT_MODES = frozenset({"union", "first", "explicit"})

#: `oob=` 的取值。`None` / `"keep"` 表示「沿用各标度自己的默认」（连续 censor /
#: 分箱 squish），与 issue 要求的「默认 censor」在连续位置上等价。
_OOB_VALUES = frozenset({"censor", "squish", "keep"})

_EPOCH_DATE = dt.date(1970, 1, 1)
_EPOCH_DATETIME = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)
_EPOCH_DATETIME_NAIVE = dt.datetime(1970, 1, 1)


class AlignError(ValueError):
    """对齐前置条件不满足（跨图变换不一致、free scale、不支持的坐标系 …）。"""


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AxisLimits:
    """一条轴上的统一结果。

    `limits` 是**数据空间**的值（连续是 `(low, high)` 的数值；日期时间也是底层
    数值，见 `native`）。`transformed` 是变换后空间的范围（连续才有），
    `native` 把日期时间还原成 `date` / `datetime` 便于阅读。
    """

    axis: str
    discrete: bool
    kind: str
    trans: str
    source: str
    limits: tuple[float, float] | tuple[str | None, ...]
    transformed: tuple[float, float] | None
    native: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class ClipCount:
    """一张图在**一条轴**上因对齐新增的裁剪。

    `rows` 是这条轴自己的越界行数；跨轴的行级并集（R 的 "Removed N rows"）在
    :class:`PlotClip` / :attr:`AlignReport.clipped_plots` 里。双轴同时裁剪时同一
    行会在两条轴上各出现一次，所以**不要**把 `clipped` 的 `rows` 直接相加。
    """

    plot: int
    axis: str
    #: 这条轴自己的越界行数。
    rows: int
    #: 与 `rows` 相同（保留的别名，便于按轴读「值数」）。
    values: int
    #: 离散轴上被统一 levels 去掉的水平（连续轴为空）。
    levels: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlotClip:
    """一张图的跨轴行级裁剪 = R 的 "Removed N rows"（x / y 任一越界即一行）。"""

    plot: int
    rows: int


@dataclass(frozen=True, slots=True)
class AlignReport:
    """对齐的完整记录：统一后的 limits、裁剪计数、提示。"""

    axis: str
    limits: Mapping[str, AxisLimits]
    #: 每图每轴的明细（同一行可能在 x / y 上各记一条）。
    clipped: tuple[ClipCount, ...] = ()
    #: 每图一条的跨轴行级并集（R 口径）；`clipped_rows` / `rows_dropped()` 用它。
    clipped_plots: tuple[PlotClip, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def clipped_rows(self) -> int:
        """所有图的新增裁剪行数（跨轴并集，不重复计同一行）。"""
        return sum(item.rows for item in self.clipped_plots)

    def rows_dropped(self, plot: int) -> int:
        """第 `plot` 张图因对齐新增的裁剪行数（跨轴并集）。"""
        return sum(item.rows for item in self.clipped_plots if item.plot == plot)


@dataclass(frozen=True, slots=True)
class AlignedPlots(Sequence[Any]):
    """`align_scales()` 的返回值：克隆后的图（可序列）+ 对齐报告。

    `for p in aligned` / `aligned[0]` / `wrap_plots(*aligned)` 拿到的是图本身；
    统一后的 limits 与裁剪计数在 `aligned.report` 里。
    """

    plots: tuple[Any, ...]
    report: AlignReport

    def __len__(self) -> int:
        return len(self.plots)

    def __getitem__(self, index: Any) -> Any:
        if isinstance(index, slice):
            return self.plots[index]
        return self.plots[index]


@dataclass(frozen=True, slots=True)
class _Measurement:
    """一张图一条轴的构建期测量结果（内部用）。"""

    build: PlotBuild
    scale: ScaleBase
    spec: Scale | None
    discrete: bool
    kind: str
    trans: str
    #: 数据空间的 limits（连续是数值对；离散是水平序列，NA 水平以 None 收尾）。
    limits: Any
    #: 变换后空间的范围（连续才有）。
    transformed: tuple[float, float] | None
    binned: bool
    #: 该轴的映射列里是否有实际数据（空图 / 只有另一条轴的图没有）。
    has_data: bool


_Unified = tuple[tuple[Any, ...], dict[int, _Measurement]]


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------


def align_scales(
    plots: Iterable[Any],
    axis: str = "xy",
    limits: str | Sequence[Any] = "union",
    *,
    x: Sequence[Any] | None = None,
    y: Sequence[Any] | None = None,
    oob: str | None = None,
    breaks: str | Sequence[Any] | None = None,
    expand: str = "keep",
    adjust_coord: bool = True,
    coord_size: float | Sequence[float] = 1.0,
) -> AlignedPlots:
    """统一多张图的刻度：克隆图、统一位置标度的 limits（可选 breaks）、补
    `coord_fixed` 比例。

    参数
    ----
    plots:
        一组 `ggplot()` 对象。**不会被修改**；返回的是克隆。
    axis:
        `"x"` / `"y"` / `"xy"`。指**数据轴**（`aes(x=…)` 那条标度），不是视觉轴；
        `coord_flip()` 的图同样按数据轴取。
    limits:
        - `"union"`（默认）：各图并集，尽量不丢数据；
        - `"first"`：以第一张图（主图）为准，其余图可能被裁剪；
        - `"explicit"`：用 `x=` / `y=` 给出的范围；
        - 也可以直接传 `(lo, hi)` / `("a", "b", "c")`（等价于单轴 explicit，
          此时 `axis` 必须只含一条轴）。
    x, y:
        `limits="explicit"` 时的范围。连续轴是 2 元数值序列；离散轴是水平序列；
        `Date` / `POSIXct` 可以给 `datetime.date` / `datetime.datetime`（按
        `ggio` 的口径折成天 / UTC 秒，报告里还原成原类型）。
    oob:
        `None`（默认，沿用各标度自己的默认：连续 `censor`、分箱 `squish`）、
        `"censor"`（越界变 NA）或 `"squish"`（压到边界）。`"keep"` 同 `None`。
    breaks:
        `None`（默认，不动各图的断点；limits 一致时默认断点自然一致）、
        `"first"`（把第一张图算出来的断点写到所有图上）或显式的数据空间序列。
    expand:
        `"keep"`（默认，与 aplot 相同）保留各图自己的 `expand`；`"first"` 用第一
        张图的 `expand`。

        **默认值不保证 tick 的页面坐标相同**：只要某张图显式设过 `expand`（例如
        `scale_x_continuous(expand = (0, 0))`），统一 limits 后它与其他图的面板
        范围仍不同，tick 的 npc 位置就会差一截。组合层（SIL-1001 的
        `wrap_plots()` / `plot_gtable()`）必须传 `expand="first"`，或者调用方自己
        保证所有图 `expand` 一致；只比「tick 值集合」时 `"keep"` 够用。
    adjust_coord:
        主图（第一张）是 `coord_fixed()` 时，给其它没设 `coord_fixed()` 的图补
        一个，避免组合后 panel 错位（aplot `adjust_coord()` 的对应物）。
    coord_size:
        补 `coord_fixed(ratio=)` 时的缩放因子，对应 aplot `.cal_ratio()` 的
        `size`（aplot 用 layout 的行 / 列号）；默认 1。

    返回
    ----
    :class:`AlignedPlots`：可当序列遍历 / 下标取图，`.report` 给统一后的
    limits 与裁剪计数。

    例子
    ----
    ```python
    plots = align_scales([p1, p2, p3], axis="xy", limits="union")
    p1_aligned, p2_aligned, p3_aligned = plots
    plots.report.limits["x"].limits        # (0.0, 10.0) 之类
    plots.report.clipped                   # first / explicit 的裁剪行数
    ```
    """
    items = tuple(plots)
    if not items:
        raise AlignError("align_scales() 至少需要一张图")
    axes = _parse_axis(axis)
    mode, explicit = _parse_limits_mode(limits, x, y, axes)
    resolved_oob = _parse_oob(oob)
    if expand not in ("keep", "first"):
        raise AlignError(f"expand 只能是 'keep' / 'first'，收到 {expand!r}")

    measurements = [_measure(plot, axes) for plot in items]
    warnings_out: list[str] = []
    unified: dict[str, _Unified] = {}
    for name in axes:
        present = {index: found[name] for index, found in enumerate(measurements) if name in found}
        if not present:
            warnings_out.append(f"{name} 轴：所有图都没有位置标度，跳过对齐")
            continue
        usable = _with_data(present)
        _check_comparable(name, usable)
        value = _resolve_limits(name, mode, explicit, usable)
        unified[name] = (value, present)

    if not unified:
        return AlignedPlots(
            plots=tuple(plot.clone() for plot in items),
            report=AlignReport(
                axis="".join(axes),
                limits=MappingProxyType({}),
                warnings=tuple(warnings_out),
            ),
        )

    primary = _primary_measurement(unified)
    aligned = list(items)
    for index, plot in enumerate(items):
        clone = plot.clone()
        for name in axes:
            if name not in unified:
                continue
            value, present = unified[name]
            measurement = present.get(index)
            if _coord_limits(clone, name) is not None:
                warnings_out.append(
                    f"第 {index + 1} 张图的 coord {name}lim 不是空：coord limits 优先于"
                    f"统一后的 scale limits，这条轴不会被真正对齐"
                )
            if measurement is None or not measurement.has_data:
                clone.scales[name] = _default_scale(
                    name, primary[name], value, resolved_oob, expand
                )
                continue
            clone.scales[name] = _uniform_scale(
                measurement, value, resolved_oob, breaks, expand, present
            )
        aligned[index] = clone

    clipped, clipped_plots = _clip_counts(measurements, axes, unified)
    if adjust_coord:
        aligned, notes = _adjust_coord(aligned, unified, coord_size)
        warnings_out.extend(notes)

    report = AlignReport(
        axis="".join(axes),
        limits=MappingProxyType(
            {
                name: _axis_limits(name, mode, value, present)
                for name, (value, present) in unified.items()
            }
        ),
        clipped=clipped,
        clipped_plots=clipped_plots,
        warnings=tuple(warnings_out),
    )
    for note in warnings_out:
        warnings.warn(note, UserWarning, stacklevel=2)
    return AlignedPlots(plots=tuple(aligned), report=report)


# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------


def _parse_axis(axis: str) -> tuple[str, ...]:
    mode = str(axis or "").lower()
    if mode not in _AXIS_MODES:
        raise AlignError(f"axis 只能是 'x' / 'y' / 'xy'，收到 {axis!r}")
    return AXES if mode in ("xy", "yx") else (mode,)


def _parse_limits_mode(
    limits: Any,
    x: Sequence[Any] | None,
    y: Sequence[Any] | None,
    axes: tuple[str, ...],
) -> tuple[str, dict[str, Sequence[Any]]]:
    if isinstance(limits, str):
        mode = limits.lower()
        if mode not in _LIMIT_MODES:
            raise AlignError(f"limits 只能是 'union' / 'first' / 'explicit'，收到 {limits!r}")
        explicit = {name: value for name, value in (("x", x), ("y", y)) if value is not None}
        if mode == "explicit":
            missing = [name for name in axes if name not in explicit]
            if missing:
                raise AlignError(
                    "limits='explicit' 需要给出 " + " / ".join(f"{name}=" for name in missing)
                )
        elif explicit:
            raise AlignError("只有 limits='explicit' 才接受 x= / y=；别的模式请用 limits=")
        return mode, explicit

    # 序列简写：limits=(lo, hi) / limits=("a", "b")
    if len(axes) != 1:
        raise AlignError(
            "limits 直接给序列时 axis 只能是一条轴（'x' 或 'y'）；"
            "同时对齐两条轴请写 limits='explicit' 并用 x= / y="
        )
    return "explicit", {axes[0]: limits}


def _parse_oob(oob: str | None) -> str | None:
    if oob is None:
        return None
    value = str(oob).lower()
    if value == "keep":
        return None
    if value not in _OOB_VALUES:
        raise AlignError(f"oob 只能是 'censor' / 'squish' / 'keep' / None，收到 {oob!r}")
    return value


# ---------------------------------------------------------------------------
# 测量
# ---------------------------------------------------------------------------


def _measure(plot: Any, axes: tuple[str, ...]) -> dict[str, _Measurement]:
    build = build_plot(plot)
    out: dict[str, _Measurement] = {}
    for name in axes:
        scale = _panel_scale(build, name)
        if scale is None:
            continue
        spec = _explicit_spec(plot, name)
        discrete = bool(getattr(scale, "discrete", False))
        transformed: tuple[float, float] | None = None
        if discrete:
            limits = tuple(scale.limits())
        else:
            low, high = (float(value) for value in scale.limits())
            # `Scale.limits()` 是**标度空间**（log10 下 0..2、reverse 下 -2..-1）；
            # 报告与写回的 `limits=` 都要数据空间，所以先反变换。
            transformed = tuple(sorted((low, high)))
            limits = _inverse_transform(scale, transformed)
        out[name] = _Measurement(
            build=build,
            scale=scale,
            spec=spec,
            discrete=discrete,
            kind=_scale_kind(scale),
            trans=_trans_name(scale),
            limits=limits,
            transformed=transformed,
            binned=isinstance(scale, BinnedPositionScale),
            has_data=_axis_has_data(build, name),
        )
    return out


def _axis_has_data(build: PlotBuild, axis: str) -> bool:
    """这条轴有没有实际绘图数据（空图 / 只有 y 的图在 x 上是没有的）。

    没有数据的图不参与 union 的范围计算：`build_plot()` 会给空图建一条默认
    `(0, 1)` 标度，把它并进来会让所有图的面板被拉到 0..1。
    """
    for layer in build.layers:
        table = layer.aesthetics
        if axis not in table.names:
            continue
        column = table.column(axis)
        if column.size and int((~np.asarray(column.na_mask, dtype=bool)).sum()) > 0:
            return True
    return False


def _panel_scale(build: PlotBuild, axis: str) -> ScaleBase | None:
    """该图的这条轴在第一个面板上的标度（单 panel 与固定 scales 的分面同一份）。"""
    if not build.panels:
        return build.scales.scale(axis)
    panel = build.panels[0]
    scales = getattr(panel, "scales", None)
    if scales is not None and hasattr(scales, "scale"):
        return scales.scale(axis)
    return build.scales.scale(axis)


def _explicit_spec(plot: Any, axis: str) -> Scale | None:
    spec = getattr(plot, "scales", {}).get(axis)
    return spec if isinstance(spec, Scale) else None


def _scale_kind(scale: ScaleBase) -> str:
    if getattr(scale, "discrete", False):
        return "discrete"
    date_kind = getattr(getattr(scale, "transform_", None), "date_kind", None)
    if date_kind:
        return f"date:{date_kind}"
    return "continuous"


def _trans_name(scale: ScaleBase) -> str:
    if getattr(scale, "discrete", False):
        return "identity"
    return str(getattr(getattr(scale, "transform_", None), "name", "identity"))


def _check_comparable(axis: str, present: Mapping[int, _Measurement]) -> None:
    kinds = {measurement.kind for measurement in present.values()}
    if len(kinds) > 1:
        detail = "；".join(
            f"第 {index + 1} 张 {measurement.kind}"
            for index, measurement in sorted(present.items())
        )
        raise AlignError(f"{axis} 轴的标度类型不一致（{detail}），无法在同一个空间里对齐")
    trans = {measurement.trans for measurement in present.values()}
    if len(trans) > 1:
        detail = "；".join(
            f"第 {index + 1} 张 {measurement.trans}"
            for index, measurement in sorted(present.items())
        )
        raise AlignError(f"{axis} 轴的变换不一致（{detail}）：请先统一 scale_*_*() 的 trans")
    for index, measurement in sorted(present.items()):
        if _has_free_scales(measurement.build, axis):
            raise AlignError(
                f"第 {index + 1} 张图的 {axis} 轴是 free scale（各面板范围不同）："
                "首期只支持单 panel 或 scales='fixed'"
            )


def _has_free_scales(build: PlotBuild, axis: str) -> bool:
    """**同一张图**的分面 free scale 检测：逐面板 limits 不同即 free。"""
    if len(build.panels) <= 1:
        return False
    seen = {panel.panel_params.limits.get(axis) for panel in build.panels}
    return len(seen) > 1


# ---------------------------------------------------------------------------
# 统一 limits
# ---------------------------------------------------------------------------


def _resolve_limits(
    axis: str,
    mode: str,
    explicit: Mapping[str, Sequence[Any]],
    present: Mapping[int, _Measurement],
) -> tuple[Any, ...]:
    present = _with_data(present)
    reference = present[min(present)]
    if reference.discrete:
        if mode == "explicit":
            return _explicit_levels(axis, explicit[axis])
        if mode == "first":
            return tuple(reference.limits)
        levels: list[Any] = []
        for index in sorted(present):
            for level in present[index].limits:
                if level is not None and level not in levels:
                    levels.append(level)
        if any(None in present[index].limits for index in present):
            # NA 在 ggplot2 的离散标度里是**最后一个水平**（`scale$get_limits()`
            # 把它 append 在结尾），统一时保持这条规则。
            levels.append(None)
        return tuple(levels)

    if mode == "explicit":
        return _explicit_numeric(axis, explicit[axis], reference)

    if mode == "first":
        low, high = reference.limits
        return (float(low), float(high))

    transformed = [
        present[index].transformed
        for index in sorted(present)
        if present[index].transformed is not None
    ]
    low = min(item[0] for item in transformed)
    high = max(item[1] for item in transformed)
    return _from_transformed(reference, (low, high))


def _from_transformed(
    measurement: _Measurement, limits: tuple[float, float]
) -> tuple[float, float]:
    """变换后空间的范围 → 数据空间（`scale_*_log10()` 的 0..2 → 1..100）。"""
    return _inverse_transform(measurement.scale, limits)


def _inverse_transform(scale: ScaleBase, limits: tuple[float, float]) -> tuple[float, float]:
    inverse = getattr(getattr(scale, "transform_", None), "inverse", None)
    if inverse is None:  # pragma: no cover - 连续标度都有
        return (float(limits[0]), float(limits[1]))
    data = np.asarray(inverse(np.asarray(limits, dtype=np.float64)), dtype=np.float64)
    low, high = float(data[0]), float(data[1])
    if not (math.isfinite(low) and math.isfinite(high)):  # pragma: no cover - 防御
        raise AlignError(f"{scale.aesthetic} 轴无法反变换回数据空间：{limits!r}")
    return (min(low, high), max(low, high))


def _explicit_numeric(
    axis: str, value: Sequence[Any], reference: _Measurement
) -> tuple[float, float]:
    items = tuple(value)
    if len(items) != 2:
        raise AlignError(f"{axis}= 需要 2 个端点，收到 {value!r}")
    if any(isinstance(item, str) for item in items):
        raise AlignError(f"{axis} 轴是连续标度，不能给水平名 {value!r}")
    low = _to_number(items[0], axis)
    high = _to_number(items[1], axis)
    if not (low <= high):
        raise AlignError(f"{axis}= 需要 low <= high，收到 {value!r}")
    return (low, high)


def _explicit_levels(axis: str, value: Sequence[Any]) -> tuple[str, ...]:
    items = tuple(value)
    if not items:
        raise AlignError(f"{axis}= 的水平序列不能为空")
    levels: list[str] = []
    for item in items:
        if item is None:
            raise AlignError(f"{axis}= 的离散水平不能是 None（NA 水平由数据自己带）")
        if isinstance(item, (int, float, np.integer, np.floating)) and not isinstance(item, bool):
            raise AlignError(f"{axis} 轴是离散标度，水平必须是字符串，收到 {item!r}")
        text = str(item)
        if text not in levels:
            levels.append(text)
    return tuple(levels)


def _to_number(value: Any, axis: str) -> float:
    """explicit limits → 底层数值（Date = 天，POSIXct = UTC 秒）。"""
    if isinstance(value, bool):
        raise AlignError(f"{axis}= 的端点不能是布尔值：{value!r}")
    if isinstance(value, dt.datetime):
        return _datetime_seconds(value)
    if isinstance(value, dt.date):
        return float((value - _EPOCH_DATE).days)
    if isinstance(value, np.datetime64):
        unit = np.datetime_data(value.dtype)[0]
        if unit in ("D", "M", "Y"):
            return float(value.astype("datetime64[D]").astype(np.int64))
        return float(value.astype("datetime64[s]").astype(np.int64))
    if isinstance(value, dt.timedelta):
        return value.total_seconds()
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise AlignError(f"{axis}= 的端点不是数值 / 日期：{value!r}") from exc
    if not math.isfinite(number):
        raise AlignError(f"{axis}= 的端点必须是有限数：{value!r}")
    return number


def _datetime_seconds(value: dt.datetime) -> float:
    if value.tzinfo is None:
        return (value - _EPOCH_DATETIME_NAIVE).total_seconds()
    return (value.astimezone(dt.UTC) - _EPOCH_DATETIME).total_seconds()


# ---------------------------------------------------------------------------
# 写回标度
# ---------------------------------------------------------------------------


def _with_data(present: Mapping[int, _Measurement]) -> dict[int, _Measurement]:
    """有实际数据的图（没有数据的图不参与范围计算，见 `_axis_has_data`）。"""
    usable = {index: measurement for index, measurement in present.items() if measurement.has_data}
    return usable or dict(present)


def _primary_measurement(unified: Mapping[str, _Unified]) -> dict[str, _Measurement]:
    """每条轴取第一张**有数据**的图的测量，用来决定缺轴图的默认标度。"""
    return {
        name: _with_data(present)[min(_with_data(present))]
        for name, (_, present) in unified.items()
    }


def _uniform_scale(
    measurement: _Measurement,
    value: tuple[Any, ...],
    oob: str | None,
    breaks: Any,
    expand: str,
    present: Mapping[int, _Measurement],
) -> Scale:
    """一张图的一条轴：保留原标度的名字与参数，只换 limits / oob / breaks / expand。"""
    spec = measurement.spec
    params: dict[str, Any] = dict(spec.params) if spec is not None else {}
    params["limits"] = tuple(value)
    if oob is not None:
        params["oob"] = oob
    if breaks is not None:
        params["breaks"] = _resolve_breaks(measurement, breaks, present)
    if expand == "first":
        usable = _with_data(present)
        source = usable[min(usable)].scale.params
        if "expand" in source:
            params["expand"] = source["expand"]
    name = spec.name if spec is not None else _default_scale_name(measurement)
    return Scale(name, measurement.scale.aesthetic, params)


def _default_scale(
    axis: str,
    measurement: _Measurement,
    value: tuple[Any, ...],
    oob: str | None,
    expand: str,
) -> Scale:
    """给「本来没有这条轴」的图补一条标度（显式 limits）。"""
    params: dict[str, Any] = {"limits": tuple(value)}
    if oob is not None:
        params["oob"] = oob
    if expand == "first" and "expand" in measurement.scale.params:
        params["expand"] = measurement.scale.params["expand"]
    return Scale(_default_scale_name(measurement), axis, params)


def _default_scale_name(measurement: _Measurement) -> str:
    """复刻这张图实际用到的默认标度（日期 / log10 / 分箱 / 离散各有自己的名字）。"""
    axis = measurement.scale.aesthetic
    if measurement.discrete:
        return f"{axis}_discrete"
    kind = measurement.kind
    if kind == "date:date":
        return f"{axis}_date"
    if kind == "date:time":
        return f"{axis}_datetime"
    if kind == "date:hms":
        return f"{axis}_time"
    if measurement.binned:
        return f"{axis}_binned"
    trans = measurement.trans
    if trans in ("log10", "sqrt", "reverse"):
        return f"{axis}_{trans}"
    return f"{axis}_continuous"


def _resolve_breaks(
    measurement: _Measurement,
    breaks: Any,
    present: Mapping[int, _Measurement],
) -> Any:
    if isinstance(breaks, str):
        if breaks != "first":
            raise AlignError(f"breaks 只能是 'first' 或显式序列，收到 {breaks!r}")
        usable = _with_data(present)
        source = usable[min(usable)]
        if source.discrete:
            return tuple(level for level in source.scale.breaks() if level is not None)
        values = [
            float(value)
            for value in source.scale.breaks()
            if value is not None and math.isfinite(float(value))
        ]
        return tuple(_inverse_values(source, values))
    items = tuple(breaks)
    if measurement.discrete:
        return tuple(str(item) for item in items)
    return tuple(_to_number(item, measurement.scale.aesthetic) for item in items)


def _inverse_values(measurement: _Measurement, values: Sequence[float]) -> list[float]:
    inverse = getattr(getattr(measurement.scale, "transform_", None), "inverse", None)
    if inverse is None:  # pragma: no cover - 连续标度都有
        return [float(value) for value in values]
    data = np.asarray(inverse(np.asarray(values, dtype=np.float64)), dtype=np.float64)
    return [float(value) for value in data]


def _coord_limits(plot: Any, axis: str) -> Any:
    params = getattr(plot.coordinates, "params", {})
    return params.get(f"{axis}lim")


# ---------------------------------------------------------------------------
# 裁剪统计
# ---------------------------------------------------------------------------


def _clip_counts(
    before: Sequence[Mapping[str, _Measurement]],
    axes: tuple[str, ...],
    unified: Mapping[str, _Unified],
) -> tuple[tuple[ClipCount, ...], tuple[PlotClip, ...]]:
    """对齐引入的裁剪：在**映射后、stat 前**的表（`LayerBuild.aesthetics`）上判越界。

    为什么不在对齐后的构建里数 NA：`stat_count()` / `stat_bin()` 会在统计阶段就
    把越界行删掉，留下的 `rows_dropped` 恒为 0，看起来像「没丢数据」。为什么用
    `layer.aesthetics` 而不是更早的原始列：它就是 `map_position()` 之后的表，
    连续轴在标度空间、离散轴是旧水平号，`_outside_by_layer()` 有对应的翻回逻辑。

    返回两份口径：

    - `ClipCount`：每图每轴的明细（`rows` 只算该轴）；
    - `PlotClip`：每图一条的跨轴行并集，= R 的 "Removed N rows"。
    """
    out: list[ClipCount] = []
    plots: list[PlotClip] = []
    for index in range(len(before)):
        per_axis: dict[str, int] = {}
        per_layer: dict[int, np.ndarray] = {}
        for name in axes:
            if name not in unified:
                continue
            value, present = unified[name]
            measurement = present.get(index)
            if measurement is None:
                continue
            masks = _outside_by_layer(measurement.build, name, measurement, value)
            per_axis[name] = int(sum(int(mask.sum()) for mask in masks.values()))
            for layer_index, mask in masks.items():
                merged = per_layer.get(layer_index)
                per_layer[layer_index] = mask if merged is None else (merged | mask)
        rows = int(sum(int(mask.sum()) for mask in per_layer.values()))
        if rows:
            plots.append(PlotClip(plot=index, rows=rows))
        for name in axes:
            if name not in unified:
                continue
            source = unified[name][1].get(index)
            levels: tuple[str, ...] = ()
            if source is not None and source.discrete:
                kept = set(unified[name][0])
                levels = tuple(level for level in source.limits if level not in kept)
            values = per_axis.get(name, 0)
            if values or levels:
                out.append(
                    ClipCount(plot=index, axis=name, rows=values, values=values, levels=levels)
                )
    return tuple(out), tuple(plots)


def _outside_by_layer(
    build: PlotBuild,
    axis: str,
    measurement: _Measurement,
    limits: Sequence[Any],
) -> dict[int, np.ndarray]:
    """每层的**映射后**数据里，该轴有多少行走出了统一后的 limits。

    `LayerBuild.aesthetics` 是 `map_position()` 之后的表：连续轴已经是标度空间
    （log10 之后）、离散轴是旧水平号。所以：

    - 连续：把新 limits（数据空间）过一遍 `transform_limits()`，再与映射值比；
    - 离散：用旧水平序列（`measurement.limits`）把水平号翻回名字，看它是否还在
      统一后的 levels 里。未知水平在映射阶段就是 NaN（不是这次对齐造成的），不数。
    """
    out: dict[int, np.ndarray] = {}
    if measurement.discrete:
        levels = list(measurement.limits)
        kept = set(limits)
        for layer in build.layers:
            table = layer.aesthetics
            if axis not in table.names:
                continue
            values = np.asarray(table.column(axis).values, dtype=np.float64)
            mask = np.zeros(values.size, dtype=bool)
            for position, value in enumerate(values.tolist()):
                if not math.isfinite(value):
                    continue
                index = round(value) - 1
                if 0 <= index < len(levels) and levels[index] not in kept:
                    mask[position] = True
            out[layer.index] = mask
        return out

    transformed = measurement.scale.transform_limits(tuple(limits))
    low, high = sorted((float(transformed[0]), float(transformed[1])))
    for layer in build.layers:
        table = layer.aesthetics
        if axis not in table.names:
            continue
        column = table.column(axis)
        values = np.asarray(column.values, dtype=np.float64)
        missing = np.asarray(column.na_mask, dtype=bool)
        out[layer.index] = np.isfinite(values) & ~missing & ((values < low) | (values > high))
    return out


# ---------------------------------------------------------------------------
# adjust_coord（aplot `adjust_coord()`）
# ---------------------------------------------------------------------------


def _adjust_coord(
    plots: list[Any],
    unified: Mapping[str, _Unified],
    coord_size: float | Sequence[float],
) -> tuple[list[Any], list[str]]:
    if not plots:
        return plots, []
    main_coord = coord_from_component(getattr(plots[0], "coordinates", None))
    if getattr(main_coord, "ratio", None) is None:
        return plots, []
    sizes = _coord_sizes(coord_size, len(plots))
    notes: list[str] = []
    for index in range(1, len(plots)):
        coord = coord_from_component(getattr(plots[index], "coordinates", None))
        if getattr(coord, "ratio", None) is not None:
            continue
        ratio = _aplot_ratio(unified, index, sizes[index])
        clone = plots[index].clone()
        clone.coordinates = Coord("fixed", {"ratio": ratio})
        plots[index] = clone
        notes.append(
            f"第 {index + 1} 张图没有 coord_fixed：按主图补 coord_fixed(ratio={ratio:.6g})"
        )
    return plots, notes


def _coord_sizes(coord_size: float | Sequence[float], count: int) -> tuple[float, ...]:
    if isinstance(coord_size, (int, float, np.integer, np.floating)):
        return tuple(float(coord_size) for _ in range(count))
    items = tuple(float(value) for value in coord_size)
    if len(items) != count:
        raise AlignError(
            f"coord_size 给了 {len(items)} 个值，但一共有 {count} 张图（需要一一对应）"
        )
    return items


def _aplot_ratio(unified: Mapping[str, _Unified], index: int, size: float) -> float:
    """aplot `.cal_ratio()`：视觉 x 范围 / 视觉 y 范围 / size。

    `coord_flip()` 的图视觉 x 来自数据 y，所以这支按视觉轴取（issue 的
    「内部按 flip 映射到视觉轴」）；`axis` 本身仍指数据轴。
    """
    if "x" not in unified or "y" not in unified:
        return 1.0
    x_measurement = unified["x"][1].get(index)
    y_measurement = unified["y"][1].get(index)
    if x_measurement is None or y_measurement is None:
        return 1.0
    x_range = _range_span(unified["x"][0])
    y_range = _range_span(unified["y"][0])
    flipped = str(getattr(x_measurement.build.coord, "name", "")).lower() == "flip"
    if flipped:
        x_range, y_range = y_range, x_range
    if not (y_range > 0) or not (size > 0):
        raise AlignError(
            "coord_fixed 的 ratio 需要正的范围与 coord_size；"
            f"x={x_range!r} / y={y_range!r} / size={size!r}"
        )
    return float(x_range / y_range / size)


def _range_span(value: Sequence[Any]) -> float:
    """统一后该轴的范围宽度（离散 = 水平数，与 aplot `.cal_limit_range` 同口径）。"""
    if not value:
        return 0.0
    if isinstance(value[0], str) or value[0] is None:
        return float(len(value))
    return float(value[1] - value[0])


def _axis_limits(
    axis: str,
    source: str,
    value: tuple[Any, ...],
    present: Mapping[int, _Measurement],
) -> AxisLimits:
    present = _with_data(present)
    reference = present[min(present)]
    if reference.discrete:
        return AxisLimits(
            axis=axis,
            discrete=True,
            kind=reference.kind,
            trans=reference.trans,
            source=source,
            limits=tuple(value),
            transformed=None,
            native=tuple(value),
        )
    low, high = float(value[0]), float(value[1])
    native: tuple[Any, ...] = (low, high)
    if reference.kind == "date:date":
        native = (
            _EPOCH_DATE + dt.timedelta(days=low),
            _EPOCH_DATE + dt.timedelta(days=high),
        )
    elif reference.kind == "date:time":
        native = (
            _EPOCH_DATETIME + dt.timedelta(seconds=low),
            _EPOCH_DATETIME + dt.timedelta(seconds=high),
        )
    elif reference.kind == "date:hms":
        native = (dt.timedelta(seconds=low), dt.timedelta(seconds=high))
    transformed: tuple[float, float] | None = None
    transform = getattr(reference.scale, "transform_", None)
    if transform is not None:
        values, _ = transform.transform(np.asarray([low, high], dtype=np.float64))
        transformed = tuple(sorted((float(values[0]), float(values[1]))))
    return AxisLimits(
        axis=axis,
        discrete=False,
        kind=reference.kind,
        trans=reference.trans,
        source=source,
        limits=(low, high),
        transformed=transformed,
        native=native,
    )

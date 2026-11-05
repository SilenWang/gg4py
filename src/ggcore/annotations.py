"""标注（annotation）：`annotation_logticks()`（SIL-739）。

ggplot2 4.0.3 的 `annotation_logticks()` 是一个 `GeomLogticks` 图层；它的
`draw_panel()` 只读 **panel_params 的范围与 coord 变换**，不读数据（`dummy_data()`
+ `inherit.aes = FALSE`）。本仓的图层流水线假定每层都有数据表，所以这里把它落成
**plot 级标注**：

```
p + annotation_logticks(sides = "bl")
```

- gg4py：`ggplot.annotations`（tuple）→ `PlotBuild.annotations` → scene 的轴阶段
  按面板 / 边逐段画；
- R：`layer(geom = GeomLogticks, data = dummy_data(), ...)`。

两者视觉契约一致（位置、三档长度、sides、outside、scaled、颜色 / 线宽 / 线型），
差别只在「是不是一个图层」——图例、分面与 `inherit.aes` 都不参与，与 R 的
`show.legend = FALSE, inherit.aes = FALSE` 同义。

位置口径照 `GeomLogticks$draw_panel()`：

```
minpow = floor(range[1]); maxpow = ceil(range[2])          # range 是面板范围（变换后）
ticks  = [1..base-1] × base^minpow .. base^(maxpow-1) + base^maxpow
value  = scaled ? log(ticks, base) : ticks
end    = 1 / 5 / 9 位置换成 long / mid / short 三档（calc_logticks 的 detail）
```

`scaled = TRUE` 对应「标度已经做过 log10 变换」的常见写法
（`scale_x_log10() + annotation_logticks()`）；`scaled = FALSE` 对应在未变换的
面板上手工按对数摆放。
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from ggcore import registry
from ggcore.aes import Aes
from ggcore.data import Column, ColumnTable
from ggcore.gtable import CellBox
from ggcore.layer import Layer, Position, Stat
from ggcore.units import UnitContext, convert_height, convert_width
from ggcore.viewport import gpar

__all__ = [
    "LogticksAnnotation",
    "annotate",
    "annotation_borders",
    "annotation_logticks",
    "borders",
    "logticks_grobs",
]


@dataclass(frozen=True, slots=True)
class LogticksAnnotation:
    """`annotation_logticks()` 的参数（长度单位已归一成 cm）。"""

    base: float = 10.0
    sides: str = "bl"
    outside: bool = False
    scaled: bool = True
    short_cm: float = 0.1
    mid_cm: float = 0.2
    long_cm: float = 0.3
    colour: str = "black"
    linewidth: float = 0.5
    linetype: int = 1
    alpha: float = 1.0

    def __post_init__(self) -> None:
        if self.base <= 1:
            raise ValueError(f"annotation_logticks(base=) 必须 > 1，收到 {self.base!r}")
        for side in self.sides:
            if side not in "bltr":
                raise ValueError(
                    f"annotation_logticks(sides=) 只能是 b / l / t / r 的组合，收到 {self.sides!r}"
                )


def _cm(value: Any, *, height: bool) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    convert = convert_height if height else convert_width
    return float(np.asarray(convert(value, "cm", ctx=UnitContext())).sum())


def annotation_logticks(
    base: float = 10,
    sides: str = "bl",
    outside: bool = False,
    scaled: bool = True,
    short: Any = None,
    mid: Any = None,
    long: Any = None,
    colour: str = "black",
    linewidth: float = 0.5,
    linetype: int = 1,
    alpha: float = 1.0,
    color: str | None = None,
    **deprecated: Any,
) -> LogticksAnnotation:
    """`annotation_logticks()`：在面板边上画对数刻度（`guide_axis_logticks` 的旧写法）。

    R 4.0.3 已把本函数标记为 superseded、推荐改用 `guide_axis_logticks()`；
    本仓两个都提供：guide 版走轴带，annotation 版把刻度画在**面板里面**。
    """
    del deprecated
    if color is not None:
        colour = color
    return LogticksAnnotation(
        base=float(base),
        sides=str(sides),
        outside=bool(outside),
        scaled=bool(scaled),
        short_cm=_cm(short, height=True) if short is not None else 0.1,
        mid_cm=_cm(mid, height=True) if mid is not None else 0.2,
        long_cm=_cm(long, height=True) if long is not None else 0.3,
        colour=str(colour),
        linewidth=float(linewidth),
        linetype=int(linetype),
        alpha=float(alpha),
    )


def calc_logticks(
    base: float,
    minpow: int,
    maxpow: int,
    shortend: float,
    midend: float,
    longend: float,
) -> tuple[np.ndarray, np.ndarray]:
    """`calc_logticks()` 的移植：`(value, end)`（end 是 cm 长度）。"""
    per = max(1, round(base) - 1)
    reps = maxpow - minpow
    ticknums = np.tile(np.linspace(1.0, base - 1.0, per), reps)
    powers = np.repeat(np.arange(minpow, maxpow, dtype=np.float64), per)
    ticks = np.concatenate([ticknums * np.power(base, powers), [base**maxpow]])
    ends = np.full(ticks.size, shortend, dtype=np.float64)
    cycle = (ticknums - 1.0).astype(int)
    ends[: cycle.size][cycle == 0] = longend
    long_after = math.floor(per / 2)
    ends[: cycle.size][cycle == long_after] = midend
    # R 的 `tickend[cycleIdx == 0]` 里逻辑下标比 tickend 短一位，按 R 的回收规则
    # 最后一个 `base^maxpow` 也落到 long。
    ends[-1] = longend
    return ticks, ends


def _axis_value(annotation: LogticksAnnotation, ticks: np.ndarray) -> np.ndarray:
    if not annotation.scaled:
        return ticks
    return np.log(ticks) / math.log(annotation.base)


def logticks_grobs(
    annotation: LogticksAnnotation,
    params: Any,
    box: CellBox,
    *,
    name: str = "annotation-logticks",
) -> list[Any]:
    """一个面板上的对数刻度（页面 cm 坐标，y 向上）。"""
    from ggcore.geom.base import POINT_PER_MM, alpha_colour
    from ggcore.grobs import segments_grob

    colour = alpha_colour(annotation.colour, annotation.alpha)
    # 与 geom_line / 轴刻度同一条换算：`linewidth`（mm）→ gpar lwd。
    gp = gpar(
        col=colour,
        lwd=annotation.linewidth * POINT_PER_MM,
        lty=annotation.linetype,
    )
    grobs: list[Any] = []
    for side in ("b", "t", "l", "r"):
        if side not in annotation.sides:
            continue
        axis = params.screen_axis({"b": "bottom", "t": "top", "l": "left", "r": "right"}[side])
        ranges = getattr(params, "continuous_ranges", None) or {}
        if axis not in ranges:
            continue
        low, high = (float(value) for value in ranges[axis])
        if not (math.isfinite(low) and math.isfinite(high)):
            continue
        low, high = min(low, high), max(low, high)
        ticks, ends = calc_logticks(
            annotation.base,
            math.floor(low),
            math.ceil(high),
            shortend=annotation.short_cm,
            midend=annotation.mid_cm,
            longend=annotation.long_cm,
        )
        values = _axis_value(annotation, ticks)
        sign = -1.0 if annotation.outside else 1.0
        xs: list[float] = []
        ys: list[float] = []
        xs2: list[float] = []
        ys2: list[float] = []
        for value, end in zip(values.tolist(), ends.tolist(), strict=True):
            if not (low - 1e-12 <= value <= high + 1e-12):
                continue
            position = params.position_of(axis, float(value))
            if not (-1e-9 <= position <= 1.0 + 1e-9):
                continue
            position = min(max(float(position), 0.0), 1.0)
            offset = sign * float(end)
            if side in ("b", "t"):
                x = box.x_cm + position * box.width_cm
                edge = box.y_cm if side == "b" else box.y_cm + box.height_cm
                xs.append(x)
                ys.append(edge)
                xs2.append(x)
                ys2.append(edge + offset)
            else:
                y = box.y_cm + position * box.height_cm
                edge = box.x_cm if side == "l" else box.x_cm + box.width_cm
                xs.append(edge)
                ys.append(y)
                xs2.append(edge + offset)
                ys2.append(y)
        if xs:
            grobs.append(
                segments_grob(
                    xs,
                    ys,
                    xs2,
                    ys2,
                    default_units="cm",
                    gp=gp,
                    name=f"{name}-{side}",
                )
            )
    return grobs


# ---------------------------------------------------------------------------
# annotate() / annotation_borders()
# ---------------------------------------------------------------------------

#: `annotate()` 明确拒绝的 geom（R 4.0.3 的 `is_string(geom, c("abline", ...))`）。
_UNSUPPORTED_ANNOTATE_GEOMS = ("abline", "hline", "vline")


def _column(values: Any, nrows: int) -> Column:
    """`annotate()` 的一个位置参数 → 列（长度 1 广播 / 长度 n 逐行）。

    不用 `ggio.frame`：ggcore 不依赖 ggio（X1 门禁），所以这里只做最小类型判定：
    字符串 → `str`，`None` → 缺失，其余按数值。
    """
    if isinstance(values, (list, tuple, np.ndarray)):
        items = list(values)
        if len(items) == 1 and nrows != 1:
            items = items * nrows
    else:
        items = [values] * nrows
    if len(items) != nrows:
        raise ValueError(f"标注参数长度 {len(items)} 与数据行数 {nrows} 不一致")

    missing = np.array([item is None for item in items], dtype=bool)
    present = [item for item in items if item is not None]
    if present and all(isinstance(item, str) for item in present):
        data = np.array(["" if item is None else item for item in items], dtype=object)
        return Column("str", data, na_mask=missing)
    if present and all(isinstance(item, (bool, np.bool_)) for item in present):
        data = np.array(
            [False if flag else bool(item) for item, flag in zip(items, missing, strict=True)]
        )
        return Column("bool", data, na_mask=missing)
    integral = present and all(
        isinstance(item, (int, np.integer)) and not isinstance(item, (bool, np.bool_))
        for item in present
    )
    data = np.array(
        [0.0 if flag else float(item) for item, flag in zip(items, missing, strict=True)],
        dtype=np.float64,
    )
    if integral and not missing.any():
        return Column("int", data)
    return Column("float", data, na_mask=missing)


def annotate(
    geom: Any,
    x: Any = None,
    y: Any = None,
    xmin: Any = None,
    xmax: Any = None,
    ymin: Any = None,
    ymax: Any = None,
    xend: Any = None,
    yend: Any = None,
    na_rm: bool = False,
    **kwargs: Any,
) -> Layer:
    """`annotate()`（ggplot2 4.0.3 的 `R/annotation.R`）：用**向量**而不是映射加一个图层。

    与 `geom_*()` 的三点差别，全部照上游：

    1. 位置美学（`x` / `y` / `xmin` / `xmax` / `ymin` / `ymax` / `xend` / `yend`）
       进**数据 + 映射**（`aes_all(names(data))`），所以它们参与标度训练、撑开范围；
    2. 其余参数（`colour` / `size` / `label` …）进 `params`（**设值**，不映射），
       因此不进图例；
    3. `stat = identity`、`position = identity`、`inherit.aes = FALSE`、
       `show.legend = FALSE`。

    长度规则照上游：所有参数长度取「去掉长度 1 后的唯一值」；多于一个就报错
    （`Unequal parameter lengths`），长度 1 的标量广播到 n。
    """
    name = geom if isinstance(geom, str) else getattr(geom, "name", None)
    if not isinstance(name, str) or not name:
        raise TypeError(f"annotate(geom=) 必须是 geom 名字或 Geom，收到 {type(geom).__name__}")
    if name in _UNSUPPORTED_ANNOTATE_GEOMS:
        warnings.warn(
            f"annotate() 不支持 geom = {name!r}；请直接用 geom_{name}()",
            UserWarning,
            stacklevel=2,
        )

    position = {
        key: value
        for key, value in {
            "x": x,
            "xmin": xmin,
            "xmax": xmax,
            "xend": xend,
            "y": y,
            "ymin": ymin,
            "ymax": ymax,
            "yend": yend,
        }.items()
        if value is not None
    }
    if not position:
        raise ValueError(
            "annotate() 至少要给一个位置美学（x / y / xmin / xmax / ymin / ymax / xend / yend）"
        )

    lengths = {
        len(value)
        for value in {**position, **kwargs}.values()
        if isinstance(value, (list, tuple, np.ndarray))
    }
    varied = lengths - {1}
    if len(varied) > 1:
        bad = [
            f"{key} ({len(value)})"
            for key, value in {**position, **kwargs}.items()
            if isinstance(value, (list, tuple, np.ndarray)) and len(value) != 1
        ]
        raise ValueError("annotate() 的参数长度不一致：" + ", ".join(bad))
    nrows = varied.pop() if varied else 1

    table = ColumnTable([(key, _column(value, nrows)) for key, value in position.items()])
    params = dict(kwargs)
    params.setdefault("na.rm", na_rm)
    layer = registry.construct("geom", name, **params)
    return replace(
        layer,
        stat=Stat("identity"),
        position=Position("identity"),
        mapping=Aes({key: key for key in position}),
        data=table,
        inherit_aes=False,
        show_legend=False,
        unlabelled=True,
    )


def annotation_borders(
    database: str = "world",
    regions: str = ".",
    fill: Any = None,
    colour: Any = "grey50",
    xlim: Any = None,
    ylim: Any = None,
    **kwargs: Any,
) -> Layer:
    """`annotation_borders()`：`maps::map()` 的边界 → `annotate("polygon", ...)`。

    **数据范围**：本仓不依赖 R 的 `maps` 包（X1：ggcore 只依赖 numpy），所以只内置
    了上游快照用到的那一份（`database = "state"`, `regions = "utah"`，逐点与
    `maps::map("state", "utah")` 同值，见 `ggcore.map_data`）。其它 database /
    regions 直接报错，不做静默降级——地图投影与数据投影是 M3-2 的空间能力。
    """
    from ggcore.map_data import map_frame

    frame = map_frame(database, str(regions), xlim=xlim, ylim=ylim)
    del kwargs
    return annotate(
        "polygon",
        x=frame["x"],
        y=frame["y"],
        group=frame["group"],
        fill=fill,
        colour=colour,
    )


def borders(*args: Any, **kwargs: Any) -> Layer:
    """`borders()`：已废弃的 `annotation_borders()` 别名（R 4.0 起 `deprecate_soft`）。"""
    warnings.warn(
        "borders() 自 ggplot2 4.0.0 起已废弃，请用 annotation_borders()",
        DeprecationWarning,
        stacklevel=2,
    )
    return annotation_borders(*args, **kwargs)

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
from dataclasses import dataclass
from typing import Any

import numpy as np

from ggcore.gtable import CellBox
from ggcore.units import UnitContext, convert_height, convert_width
from ggcore.viewport import gpar

__all__ = [
    "LogticksAnnotation",
    "annotation_logticks",
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

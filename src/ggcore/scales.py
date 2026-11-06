"""`ggcore.scales` —— ggplot2 4.0.3 的标度实现（M1-4 + M2-4 A）。

M1-4 打底 15 个名字；M2-4 A（SIL-731）按族补齐连续侧，注册表共 75 个
`scale_*` 导出（见 `ggcore.scale_specs`）。本模块的类按「实现族」组织：
`ContinuousScale`（位置 / 渐变 / size / alpha / linewidth）、`BinnedScale`
（分箱）、`DiscreteScale`（hue / shape）。日期时间是连续标度的 `trans`，不是
第四套实现。

标度回答四个问题：训练后的范围、断点、标签、以及「数据值 → 美学值」的映射。
口径逐条对齐上游（`R/scale-continuous.R` / `R/scale-discrete.R` /
`R/scale-*.R`），全文见 `docs/notes/scales.md`。

    scales = ScaleSet()
    scales.transform_table(table)      # 位置数据先做变换（上游 scales$transform_df）
    scales.train(column, "x")          # 训练范围 / 水平
    scaled = scales.map(column, "x")   # 映射（连续位置：变换后的值）
    scales.limits("x"), scales.breaks("x"), scales.labels("x")

四个必须记住的口径：

1. **变换在训练之前**：ggplot2 4.0.3 先 `scales$transform_df()` 再
   `train_position()`，所以连续标度的 `limits()` / `breaks()` 都在**变换后**的
   空间里（`scale_x_log10()` 下 x = 1/10/100 的训练范围是 `(0, 2)`）。
2. **expand 只影响面板范围**，不影响 `limits()`：`limits()` 是
   `scale$get_limits()`（数据范围 / 显式 limits），`expanded_limits()` 才是
   `expansion()` 处理后的面板范围。M1-5 的 coord 只消费后者。
3. **连续默认 expand = `expansion(mult = 0.05)`，离散默认
   `expansion(add = 0.6)`**——离散 n 个水平的面板范围是 `0.4 .. n + 0.6`
   （不是 0.5..n+0.5；上游 3.0 之后就是 0.6）。
4. **越界默认 → NA**（`oob = censor`；分箱族默认 `squish`），离散标度里 NA
   本身是一个水平（排在最后）。

本模块只用标准库 + numpy（X1），不 import pandas / 绘图库。
"""

from __future__ import annotations

import datetime as _dt
import itertools
import math
import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import numpy as np

from ggcore import plotmath, scales_date
from ggcore.components import Scale
from ggcore.data import Column, ColumnTable
from ggcore.palettes import (
    BREWER_NAMES,
    MUTED,
    SHAPE_CODES_SOLID,
    alpha_ordinal_pal,
    brewer_pal,
    colour_ramp,
    gradient_n_pal,
    gradient_pal,
    grey_pal,
    hex_to_lab,
    hue_pal,
    lab_to_hex,
    linetype_pal,
    linewidth_ordinal_pal,
    shape_pal,
    size_ordinal_pal,
    viridis_pal,
)
from ggcore.scale_specs import SCALE_DEFAULTS, SCALE_FAMILIES

__all__ = [
    "BREWER_NAMES",
    "CONTINUOUS_AESTHETICS",
    "DISCRETE_AESTHETICS",
    "POSITION_AESTHETICS",
    "Expansion",
    "ScaleError",
    "ScaleSet",
    "brewer_pal",
    "colour_ramp",
    "expand_range",
    "extended_breaks",
    "gradient_pal",
    "hex_to_lab",
    "hue_pal",
    "lab_to_hex",
    "label_math",
    "new_transform",
    "pretty_breaks",
    "scale_from_component",
    "transform_probability",
]

#: 位置美学：x 与 y 两条通道。`xmin/xmax/xend` 共用 x 标度，`ymin/ymax/yend` 共用
#: y 标度（上游 `ggplot_global$x_aes` / `$y_aes`）。
POSITION_AESTHETICS = frozenset({"x", "y", "xmin", "xmax", "xend", "ymin", "ymax", "yend"})

#: 连续标度覆盖的美学（默认解析里位置按列类型二选一）。
CONTINUOUS_AESTHETICS = frozenset({"size", "alpha", "colour", "fill", "linewidth"})

#: 离散标度覆盖的美学。
DISCRETE_AESTHETICS = frozenset({"shape", "colour", "fill", "linetype"})

#: 位置标度吃的美学名（上游 `ggplot_global$x_aes` / `y_aes`）：除了 `x` / `y`
#: 本体，还有箱线图 / 区间几何派生的 `ymin_final` / `lower` 这一批。第二段
#: 训练（`plot-build.R` 的 `train_position()`）靠它们把「画出来的范围」收进
#: 标度——`geom_boxplot()` 的离群点就只在 `ymin_final` / `ymax_final` 里。
_X_ALIASES = frozenset(
    {
        "xmin",
        "xmax",
        "xend",
        "xintercept",
        "xmin_final",
        "xmax_final",
        "xlower",
        "xmiddle",
        "xupper",
        "x0",
    }
)
_Y_ALIASES = frozenset(
    {
        "ymin",
        "ymax",
        "yend",
        "yintercept",
        "ymin_final",
        "ymax_final",
        "lower",
        "middle",
        "upper",
        "y0",
    }
)


class ScaleError(ValueError):
    """标度无法构造或无法映射（未实现的 trans / 参数形态不对）。"""


# ---------------------------------------------------------------------------
# expand
# ---------------------------------------------------------------------------


def _zero_range(low: float, high: float) -> bool:
    """上游 `zero_range()`：相等，或相对差小于 1000 * eps。"""
    if low == high:
        return True
    if not (math.isfinite(low) and math.isfinite(high)):
        return False
    smallest = min(abs(low), abs(high))
    if smallest == 0:
        return False
    return abs((low - high) / smallest) < 1000 * np.finfo(float).eps


def _pair(value: float | Sequence[float]) -> tuple[float, float]:
    """标量 → (v, v)；长度 1 / 2 的序列 → 两端。"""
    if isinstance(value, (int, float, np.integer, np.floating)):
        number = float(value)
        return number, number
    items = [float(item) for item in value]
    if len(items) == 1:
        return items[0], items[0]
    if len(items) == 2:
        return items[0], items[1]
    raise ScaleError(f"expand 的分量必须是标量或 1/2 元序列，收到 {value!r}")


def expand_range(
    low: float,
    high: float,
    mult: float | Sequence[float] = 0.05,
    add: float | Sequence[float] = 0,
) -> tuple[float, float]:
    """上游 `expand_range()`：`range + c(-1, 1) * (width * mult + add)`。

    宽度为零（只有一种取值）时按上游的 `zero_width = 1` 处理，所以单点数据也会
    得到一段有宽度的范围。`mult` / `add` 可以给 2 元序列，表示两端不同。

    这是**唯一**的 expand 实现：连续默认 `mult = 0.05`，离散标度调用时传
    `mult = 0, add = 0.6`（见 :meth:`ScaleSet.expanded_limits`）。
    """
    width = 1.0 if _zero_range(float(low), float(high)) else float(high) - float(low)
    lower_mult, upper_mult = _pair(mult)
    lower_add, upper_add = _pair(add)
    return (
        float(low) - (width * lower_mult + lower_add),
        float(high) + (width * upper_mult + upper_add),
    )


@dataclass(frozen=True, slots=True)
class Expansion:
    """上游 `expansion()` 的 4 个数：`c(mult_low, add_low, mult_high, add_high)`。"""

    mult: tuple[float, float] = (0.05, 0.05)
    add: tuple[float, float] = (0.0, 0.0)

    def apply(self, low: float, high: float) -> tuple[float, float]:
        return expand_range(low, high, self.mult, self.add)

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.mult[0], self.add[0], self.mult[1], self.add[1])

    @classmethod
    def from_param(cls, value: Any, *, default: Expansion) -> Expansion:
        """把 `scale_*(expand = ...)` 的参数解析成 :class:`Expansion`。

        与上游 `default_expansion()` 一样按 `rep_len(expand, 4)` 解释：标量 → 四个
        分量都是它；2 元序列 → `(mult, add)` 两端相同；4 元序列 → `(mult_low,
        add_low, mult_high, add_high)`。也接受 `{"mult":…, "add":…}` 与
        :class:`Expansion`。
        """
        if value is None:
            return default
        if isinstance(value, Expansion):
            return value
        if isinstance(value, Mapping):
            mult = _pair(value.get("mult", 0.05))
            add = _pair(value.get("add", 0))
            return Expansion(mult, add)
        if isinstance(value, (int, float, np.integer, np.floating)):
            return Expansion.from_param([value], default=default)
        items = [float(item) for item in value]
        # 上游 `default_expansion()` 对 scale$expand 做的是 `rep_len(expand, 4)`：
        # 标量 → 四个分量都是它；2 元 → c(mult, add, mult, add)；4 元 → 原样。
        if len(items) == 1:
            number = items[0]
            return Expansion((number, number), (number, number))
        if len(items) == 2:
            return Expansion((items[0], items[0]), (items[1], items[1]))
        if len(items) == 4:
            return Expansion((items[0], items[2]), (items[1], items[3]))
        raise ScaleError(f"expand 必须是标量 / 2 元 / 4 元序列，收到 {value!r}")


CONTINUOUS_EXPANSION = Expansion((0.05, 0.05), (0.0, 0.0))
DISCRETE_EXPANSION = Expansion((0.0, 0.0), (0.6, 0.6))


# ---------------------------------------------------------------------------
# labelling::extended（连续默认断点）
# ---------------------------------------------------------------------------

_SIMPLICITY_Q = (1.0, 5.0, 2.0, 2.5, 4.0, 3.0)
_WEIGHTS = (0.25, 0.2, 0.5, 0.05)
_EPS = float(np.finfo(float).eps) * 100


def _simplicity_max(q: float, j: int) -> float:
    index = _SIMPLICITY_Q.index(q) + 1
    return 1 - (index - 1) / (len(_SIMPLICITY_Q) - 1) - j + 1


def _simplicity(q: float, j: int, low: float, high: float, step: float) -> float:
    index = _SIMPLICITY_Q.index(q) + 1
    residue = low % step if step else 0.0
    centre = 1.0 if (residue < _EPS or step - residue < _EPS) and low <= 0 <= high else 0.0
    return 1 - (index - 1) / (len(_SIMPLICITY_Q) - 1) - j + centre


def _density_max(k: int, m: int) -> float:
    return 2 - (k - 1) / (m - 1) if k >= m else 1.0


def _density(k: int, m: int, dmin: float, dmax: float, low: float, high: float) -> float:
    r = (k - 1) / (high - low)
    rt = (m - 1) / (max(high, dmax) - min(dmin, low))
    return 2 - max(r / rt, rt / r)


def _coverage_max(dmin: float, dmax: float, span: float) -> float:
    width = dmax - dmin
    if span > width:
        half = (span - width) / 2
        return 1 - 0.5 * (half * half + half * half) / ((0.1 * width) ** 2)
    return 1.0


def _coverage(dmin: float, dmax: float, low: float, high: float) -> float:
    width = dmax - dmin
    return 1 - 0.5 * ((dmax - high) ** 2 + (dmin - low) ** 2) / ((0.1 * width) ** 2)


def extended_breaks(dmin: float, dmax: float, m: int = 5) -> tuple[float, ...]:
    """`labeling::extended()` 的移植（ggplot2 连续标度的默认断点）。

    与上游逐条对齐打分函数：simplicity / coverage / density / legibility
    四项加权（0.25 / 0.2 / 0.5 / 0.05），`Q = c(1, 5, 2, 2.5, 4, 3)`。
    返回值与 R 的 `labeling::extended(dmin, dmax, m)` 逐项相等（`tests/test_scales.py`
    用 19 组范围钉住）。
    """
    if dmin > dmax:
        dmin, dmax = dmax, dmin
    if dmax - dmin < _EPS:
        if m == 1:
            return (dmin,)
        return tuple(dmin + (dmax - dmin) * index / (m - 1) for index in range(m))

    best_low = best_high = best_step = 0.0
    best_score = -2.0
    j = 1
    while j < math.inf:
        stop = False
        for q in _SIMPLICITY_Q:
            simple = _simplicity_max(q, j)
            if (_WEIGHTS[0] * simple + _WEIGHTS[1] + _WEIGHTS[2] + _WEIGHTS[3]) < best_score:
                stop = True
                break
            k = 2
            while k < math.inf:
                density = _density_max(k, m)
                if (_WEIGHTS[0] * simple + _WEIGHTS[1] + _WEIGHTS[2] * density + _WEIGHTS[3]) < (
                    best_score
                ):
                    break
                delta = (dmax - dmin) / (k + 1) / j / q
                z = math.ceil(math.log10(delta))
                while z < math.inf:
                    step = j * q * 10.0**z
                    cover_max = _coverage_max(dmin, dmax, step * (k - 1))
                    if (
                        _WEIGHTS[0] * simple
                        + _WEIGHTS[1] * cover_max
                        + _WEIGHTS[2] * density
                        + _WEIGHTS[3]
                    ) < best_score:
                        break
                    min_start = math.floor(dmax / step) * j - (k - 1) * j
                    max_start = math.ceil(dmin / step) * j
                    if min_start > max_start:
                        z += 1
                        continue
                    for start in range(int(min_start), int(max_start) + 1):
                        low = start * (step / j)
                        high = low + step * (k - 1)
                        score = (
                            _WEIGHTS[0] * _simplicity(q, j, low, high, step)
                            + _WEIGHTS[1] * _coverage(dmin, dmax, low, high)
                            + _WEIGHTS[2] * _density(k, m, dmin, dmax, low, high)
                            + _WEIGHTS[3]
                        )
                        if score > best_score:
                            best_score = score
                            best_low, best_high, best_step = low, high, step
                    z += 1
                k += 1
        if stop:
            break
        j += 1

    if best_step <= 0:
        return tuple(dmin + (dmax - dmin) * index / (m - 1) for index in range(m))
    values: list[float] = []
    index = 0
    while True:
        value = best_low + index * best_step
        if value > best_high + abs(best_step) * 1e-10:
            break
        values.append(value)
        index += 1
    return tuple(values)


# ---------------------------------------------------------------------------
# R 的 format()（默认标签）
# ---------------------------------------------------------------------------


def _decimals_needed(value: float) -> int:
    """表示一个数至少需要几位小数（R `format()` 的 7 位有效数字口径）。

    R 的 `format(x)` 缺省 `digits = getOption("digits")` = 7：每个元素按**7 位有效
    数字**取舍，再按元素修掉尾随 0，最后整组补到最多的小数位。所以
    `2^c(3.5, 4, 4.5, 5, 5.5)` 印成 `11.31371 / 16.00000 / 22.62742 / …`，而
    11.313708498984761 的浮点尾数不再多印一位。

    旧实现按 `|value|·1e-7` 的绝对容差逐位试，对 11.313708… 会给出 6 位（多一位），
    上游 `sec_axis-with-coord-transform` 的断点标签因此宽 0.17cm，面板被挤窄。
    """
    if value == 0:
        return 0
    exponent = math.floor(math.log10(abs(value)))
    decimals = max(0, 6 - exponent)
    while decimals > 0 and round(value, decimals) == round(value, decimals - 1):
        decimals -= 1
    return decimals


def _scientific_text(value: float) -> str:
    """最短的科学记号（R 的样子："1e+05" / "2.5e-04"）。"""
    if value == 0:
        return "0e+00"
    mantissa, exponent = f"{value:.7e}".split("e")
    mantissa = mantissa.rstrip("0").rstrip(".")
    sign = exponent[0]
    digits = exponent[1:].lstrip("0") or "0"
    return f"{mantissa}e{sign}{digits.rjust(2, '0')}"


def format_numbers(values: Sequence[float | None]) -> list[str | None]:
    """仿 R 的 `format(x, trim = TRUE, justify = "left")`（连续标度的默认标签）。

    规则（与 R 的常见路径一致）：整组取同一套小数位（取各元素需要的最大位数），
    再比较定宽写法与科学记号的宽度，科学记号更短就用科学记号。量级极端
    （>= 1e7 或 < 1e-4）时可能和 R 的取舍差一位，见 `docs/notes/scales.md`。
    """
    present = [float(value) for value in values if value is not None]
    if not present:
        return [None for _ in values]
    decimals = max(_decimals_needed(value) for value in present)
    fixed = [f"{round(value, decimals):.{decimals}f}" for value in present]
    scientific = [_scientific_text(value) for value in present]
    use_scientific = max(len(text) for text in scientific) < max(len(text) for text in fixed)
    formatted = scientific if use_scientific else fixed
    iterator = iter(formatted)
    return [None if value is None else next(iterator) for value in values]


# ---------------------------------------------------------------------------
# 色板 / 颜色空间
#
# 颜色空间与色板本身在 `ggcore.palettes`（M2-4 A、B 两段共用一个模块）：
# `hex_to_lab` / `lab_to_hex` / `hue_pal` / `gradient_pal` 等仍然从这里再导出，
# 老调用方不用改。本模块只负责「标度怎么用色板」。
# ---------------------------------------------------------------------------


def div_gradient_pal(
    low: str = MUTED["red"], mid: str = "white", high: str = MUTED["blue"]
) -> Callable[[Sequence[float]], list[str]]:
    """上游 `pal_div_gradient(low, mid, high)`（默认停靠点 0 / 0.5 / 1）。"""
    return colour_ramp([low, mid, high])


def brewer_gradient(
    type: str = "seq",
    palette: Any = 1,
    direction: float = -1,
    values: Sequence[float] | None = None,
) -> Callable[[Sequence[float]], list[str]]:
    """`scale_*_distiller()` 的调色板：Brewer 的 7 色表 → 连续渐变。"""
    stops = [colour for colour in brewer_pal(type, palette, direction)(7) if colour is not None]
    return gradient_n_pal(stops, values)


def brewer_binned(
    type: str = "seq",
    palette: Any = 1,
    direction: float = -1,
) -> Callable[[Sequence[float]], list[str]]:
    """`scale_*_fermenter()` 的调色板：`pal_binned(pal_brewer(...))`（按箱数取色）。"""
    pal = brewer_pal(type, palette, direction)

    def palette_fn(positions: Sequence[float]) -> list[str]:
        return [colour if colour is not None else "grey50" for colour in pal(len(positions))]

    return palette_fn


def pretty_breaks(low: float, high: float, n: int = 5) -> tuple[float, ...]:
    """base R `pretty()`（日期时间标度的默认断点）。"""
    return scales_date.pretty(low, high, n)


#: `scale_shape_discrete()` 的默认实心形状（上游 `pal_shape(solid = TRUE)`）。
_SHAPE_CODES = SHAPE_CODES_SOLID


def _rescale(
    values: np.ndarray, to: tuple[float, float], source: tuple[float, float]
) -> np.ndarray:
    """`scales::rescale(x, to, from)`（NA 保持 NA；退化区间取 to 的中点）。"""
    low, high = source
    if _zero_range(low, high) or _zero_range(*to):
        return np.where(np.isnan(values), np.nan, (to[0] + to[1]) / 2)
    return (values - low) / (high - low) * (to[1] - to[0]) + to[0]


def _apply_rescaler(
    rescaler: Any, values: np.ndarray, limits: tuple[float, float], scale: Any
) -> np.ndarray:
    """`ScaleContinuous$rescale` 的三种内置 rescaler + 自定义回调。"""
    if callable(rescaler):
        try:
            return np.asarray(rescaler(values, limits), dtype=np.float64)
        except TypeError:
            return np.asarray(rescaler(values), dtype=np.float64)
    if rescaler == "rescale_max":
        # scales::rescale_max(x, to = c(0, 1), from = limits) = x / from[2]
        top = float(limits[1])
        if top == 0:
            return np.where(np.isnan(values), np.nan, 0.0)
        return values / top
    if rescaler == "rescale_mid":
        mid = float(getattr(scale, "_mid_transformed", 0.0))
        low, high = float(limits[0]), float(limits[1])
        if _zero_range(low, high):
            return np.where(np.isnan(values), np.nan, 0.5)
        extent = 2 * max(abs(low - mid), abs(high - mid))
        if extent == 0:
            return np.where(np.isnan(values), np.nan, 0.5)
        return (values - mid) / extent + 0.5
    return _rescale(values, (0.0, 1.0), (float(limits[0]), float(limits[1])))


# ---------------------------------------------------------------------------
# 列工具
# ---------------------------------------------------------------------------


def _is_missing(values: np.ndarray) -> np.ndarray:
    if values.dtype.kind == "f":
        return np.isnan(values)
    if values.dtype.kind == "O":
        return np.array(
            [
                item is None or (isinstance(item, (float, np.floating)) and bool(np.isnan(item)))
                for item in values.tolist()
            ],
            dtype=bool,
        )
    return np.zeros(values.shape[0], dtype=bool)


def _numeric_values(column: Column) -> np.ndarray:
    """列 → 数值数组（NA / 非数值 → NaN）。"""
    if column.kind in ("float", "int", "datetime", "date", "timedelta"):
        values = np.asarray(column.values, dtype=np.float64).copy()
        values[column.na_mask] = np.nan
        return values
    if column.kind == "bool":
        values = column.values.astype(np.float64)
        values[column.na_mask] = np.nan
        return values
    return np.full(column.size, np.nan)


def _string_values(column: Column) -> np.ndarray:
    """列 → 字符串数组（NA → None）；categorical 用 levels 还原。"""
    values = np.empty(column.size, dtype=object)
    if column.kind == "categorical":
        if column.levels:
            values[:] = np.asarray(column.levels, dtype=object)[column.values]
        else:
            values[:] = None
    elif column.kind == "bool":
        values[:] = np.where(column.values, "True", "False")
    elif column.kind == "str":
        values[:] = np.asarray(column.values, dtype=object)
    else:
        values[:] = [str(item) for item in column.values.tolist()]
    values[column.na_mask] = None
    return values


def _level_key(item: Any) -> str:
    if isinstance(item, (bool, np.bool_)):
        return "True" if bool(item) else "False"
    return item if isinstance(item, str) else str(item)


def _column_from_array(values: Any) -> Column:
    """ndarray / 序列 → Column（`map` 的 ndarray 入口用）。"""
    array = np.asarray(values)
    if array.ndim != 1:
        raise ScaleError(f"标度输出必须是 1 维数组，得到 {array.ndim} 维")
    if array.dtype.kind == "f":
        missing = np.isnan(array)
        return Column("float", np.where(missing, 0.0, array), na_mask=missing)
    if array.dtype.kind == "b":
        return Column("bool", array)
    if array.dtype.kind in ("i", "u"):
        return Column("int", array)
    items = array.tolist()
    missing = np.array([item is None for item in items], dtype=bool)
    data = np.array(["" if item is None else str(item) for item in items], dtype=object)
    return Column("str", data, na_mask=missing)


def _float_column(values: np.ndarray) -> Column:
    missing = np.isnan(values)
    return Column("float", np.where(missing, 0.0, values), na_mask=missing)


def _fill_value(value: Any) -> Any:
    """`values=` 的一项：颜色折成字符串，渐变 / 图案原样留着。"""
    from ggcore.fills import FillSpec

    return value if isinstance(value, FillSpec) else str(value)


def _str_column(values: Sequence[str | None]) -> Column:
    items = list(values)
    missing = np.array([item is None for item in items], dtype=bool)
    data = np.array(["" if item is None else str(item) for item in items], dtype=object)
    return Column("str", data, na_mask=missing)


# ---------------------------------------------------------------------------
# transform（上游 `scales$transform_df`）
# ---------------------------------------------------------------------------


class _Transform:
    """连续标度的变换：`identity` / `log10` / `sqrt` / `reverse` / 日期时间。

    `breaks()` 收的是**数据空间**的范围（`_raw_breaks()` 先把 transforms 后的
    limits 反变换回去），返回值也在数据空间，再由调用方变换回来——这是
    `ScaleContinuous$get_breaks()` 的口径。
    """

    name: str = "identity"
    #: 日期时间变换的类别（`date` / `time` / `hms`）；其余为 `None`。
    date_kind: str | None = None

    def transform(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        raise NotImplementedError

    def inverse(self, values: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    @property
    def domain(self) -> tuple[float, float]:
        return (-math.inf, math.inf)

    def breaks(self, low: float, high: float, n: int = 5) -> tuple[float, ...]:
        return extended_breaks(low, high, n)

    def label(self, values: Sequence[float | None]) -> list[str | None]:
        """默认标签：数值格式（日期时间变换覆盖成 `format()`）。"""
        return format_numbers(values)


class _Identity(_Transform):
    name = "identity"

    def transform(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return values, np.isnan(values)

    def inverse(self, values: np.ndarray) -> np.ndarray:
        return values


class _Sqrt(_Transform):
    """`scales::transform_sqrt()`：负值 → NA（R 给 NaN + warning）。"""

    name = "sqrt"

    def transform(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        invalid = ~(values >= 0) | ~np.isfinite(values)
        out = np.full(values.shape, np.nan)
        valid = ~invalid
        out[valid] = np.sqrt(values[valid])
        return out, invalid

    def inverse(self, values: np.ndarray) -> np.ndarray:
        out = np.array(values, dtype=np.float64, copy=True)
        out[out < 0] = np.nan
        return out**2

    @property
    def domain(self) -> tuple[float, float]:
        return (0.0, math.inf)

    def label(self, values: Sequence[float | None]) -> list[str | None]:
        return format_numbers(values)


class _Reverse(_Transform):
    """`scales::transform_reverse()`：`x → -x`（域是整个实数轴）。"""

    name = "reverse"

    def transform(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return -values, np.isnan(values)

    def inverse(self, values: np.ndarray) -> np.ndarray:
        return -values

    def breaks(self, low: float, high: float, n: int = 5) -> tuple[float, ...]:
        return extended_breaks(low, high, n)

    def label(self, values: Sequence[float | None]) -> list[str | None]:
        return format_numbers(values)


class _CallableTransform(_Transform):
    """`scales::new_transform()`：用户给的 `transform` / `inverse` 两段函数。

    R 的两段都要求矢量化的函数（`Vectorize()` 包一层即可）；`domain` 之外的值
    按 R 的 `transform()` 口径落成 NA 并在训练时计数。
    """

    date_kind: str | None = None

    def __init__(
        self,
        name: str,
        transform: Callable[[Any], Any],
        inverse: Callable[[Any], Any],
        domain: tuple[float, float] = (-math.inf, math.inf),
    ) -> None:
        if not callable(transform) or not callable(inverse):
            raise ScaleError("new_transform() 的 transform / inverse 都必须是函数")
        self.name = str(name)
        self._forward = transform
        self._backward = inverse
        self._domain = (float(domain[0]), float(domain[1]))

    @property
    def domain(self) -> tuple[float, float]:
        return self._domain

    def transform(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        values = np.asarray(values, dtype=np.float64)
        invalid = np.isnan(values) | (values < self._domain[0]) | (values > self._domain[1])
        out = np.array(values, dtype=np.float64, copy=True)
        with np.errstate(invalid="ignore", divide="ignore"):
            try:
                forward = np.asarray(self._forward(out), dtype=np.float64)
            except (TypeError, ValueError) as exc:  # pragma: no cover - 用户函数报错
                raise ScaleError(f"new_transform({self.name!r}) 的 transform 失败：{exc}") from exc
        out = np.broadcast_to(forward, values.shape).astype(np.float64, copy=True)
        invalid = invalid | ~np.isfinite(out)
        out[invalid] = np.nan
        return out, invalid

    def inverse(self, values: np.ndarray) -> np.ndarray:
        values = np.asarray(values, dtype=np.float64)
        with np.errstate(invalid="ignore", divide="ignore"):
            try:
                back = np.asarray(self._backward(values), dtype=np.float64)
            except (TypeError, ValueError) as exc:  # pragma: no cover - 用户函数报错
                raise ScaleError(f"new_transform({self.name!r}) 的 inverse 失败：{exc}") from exc
        return np.broadcast_to(back, values.shape).astype(np.float64, copy=True)


def new_transform(
    name: str,
    transform: Callable[[Any], Any],
    inverse: Callable[[Any], Any],
    domain: tuple[float, float] = (-math.inf, math.inf),
) -> _Transform:
    """`scales::new_transform(name, transform, inverse, domain)`。

    `scale_x_continuous(transform = new_transform(...))` 就是 R 的自定义变换入口
    （`sec_axis-custom-transform` 的那条 `magnify_trans_log()`）。
    """
    return _CallableTransform(name, transform, inverse, domain)


class _NormProbability(_Transform):
    """`scales::transform_probability("norm", lower.tail = ...)`（=`transform_norm`）。

    `lower_tail=TRUE`：`x → qnorm(x)`（probit）；`FALSE`：`x → qnorm(x, lower.tail=FALSE)`
    = `-qnorm(x)`，逆变换是 `pnorm(y, lower.tail=...)`。定义域 `[0, 1]`。
    """

    name = "probability"

    def __init__(self, mean: float = 0.0, sd: float = 1.0, *, lower_tail: bool = True) -> None:
        if not (sd > 0):
            raise ScaleError("transform_probability() 的 sd 必须为正")
        self.mean = float(mean)
        self.sd = float(sd)
        self.lower_tail = bool(lower_tail)

    @property
    def domain(self) -> tuple[float, float]:
        return (0.0, 1.0)

    def transform(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        from statistics import NormalDist

        values = np.asarray(values, dtype=np.float64)
        invalid = np.isnan(values) | (values < 0.0) | (values > 1.0)
        out = np.full(values.shape, np.nan)
        valid = ~invalid
        distribution = NormalDist(mu=self.mean, sigma=self.sd)
        probabilities = values[valid]
        if not self.lower_tail:
            probabilities = 1.0 - probabilities
        out[valid] = [
            distribution.inv_cdf(float(p))
            if 0.0 < float(p) < 1.0
            else math.copysign(math.inf, float(p) - 0.5)
            for p in probabilities
        ]
        return out, invalid

    def inverse(self, values: np.ndarray) -> np.ndarray:
        from statistics import NormalDist

        values = np.asarray(values, dtype=np.float64)
        distribution = NormalDist(mu=self.mean, sigma=self.sd)
        out = np.array([distribution.cdf(float(v)) for v in values], dtype=np.float64)
        if not self.lower_tail:
            out = 1.0 - out
        return out


def transform_probability(
    distribution: str = "norm",
    *,
    mean: float = 0.0,
    sd: float = 1.0,
    lower_tail: bool = True,
) -> _Transform:
    """`scales::transform_probability()`（目前只有 `distribution = "norm"`）。"""
    if str(distribution) != "norm":
        raise ScaleError(
            f"transform_probability(): 只实现了 distribution='norm'，收到 {distribution!r}"
        )
    return _NormProbability(mean, sd, lower_tail=lower_tail)


class _DateTransform(_Transform):
    """日期时间：数值本身就是「自 epoch 起的天 / 秒」，只换断点与标签口径。

    - 断点默认 `pretty()`（`scales::transform_date()` / `transform_time()` /
      `transform_hms()` 的 `breaks=breaks_pretty()`）；
    - 标签默认 `format()`：Date → `%Y-%m-%d`，POSIXct → 有非零时刻时带时分秒，
      hms → `%H:%M:%S`。
    """

    def __init__(self, kind: str) -> None:
        self.name = kind
        self.date_kind = kind
        #: `pretty.Date()` / `pretty.POSIXt()` 选出来的标签格式（默认断点才有；
        #: 显式 breaks / date_breaks 与 R 一样用 `format()` 的默认格式）。
        self.break_format: str | None = None

    def transform(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return values, np.isnan(values)

    def inverse(self, values: np.ndarray) -> np.ndarray:
        return values

    def breaks(self, low: float, high: float, n: int = 5) -> tuple[float, ...]:
        if self.date_kind == "date":
            values, self.break_format = scales_date.pretty_date([low, high], n)
            return tuple(values)
        if self.date_kind == "time":
            values, self.break_format = scales_date.pretty_datetime([low, high], n)
            return tuple(values)
        return pretty_breaks(low, high, n)

    def label(self, values: Sequence[float | None]) -> list[str | None]:
        out: list[str | None] = []
        for value in values:
            if value is None or not math.isfinite(float(value)):
                out.append(None)
            elif self.date_kind == "date":
                fmt = self.break_format or "%Y-%m-%d"
                out.append(scales_date.format_date(float(value), fmt))
            elif self.date_kind == "time":
                fmt = self.break_format
                out.append(scales_date.format_datetime(float(value), fmt))
            else:
                out.append(scales_date.format_hms(float(value)))
        return out


class _Log(_Transform):
    """`scales::transform_log(base)`：对数变换 + `breaks_log(base)`。

    `log10` 是它的一个特例（:class:`_Log10` 只钉名字与实现细节不变）。幂的底数
    影响断点栅格：`transform_log2()` 的断点按 2 的幂取，与 `transform_log10()`
    的整十次幂不是同一张表。
    """

    def __init__(self, base: float = 10.0, name: str | None = None) -> None:
        self.base = float(base)
        self.name = name or f"log{_format_base(self.base)}"

    def transform(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """0 与负值 → NA（并计数）。

        上游把 0 落成 `-Inf`（`censor()` 只 censor 有限值），绘制时会画出无限远
        的点；这里按本任务的要求统一记 NA 并计数，见 `docs/notes/scales.md`。
        """
        invalid = ~(values > 0) | ~np.isfinite(values)
        out = np.full(values.shape, np.nan)
        valid = ~invalid
        out[valid] = np.log(values[valid]) / math.log(self.base)
        return out, invalid

    def inverse(self, values: np.ndarray) -> np.ndarray:
        return np.power(self.base, values)

    @property
    def domain(self) -> tuple[float, float]:
        return (1e-100, math.inf)

    def breaks(self, low: float, high: float, n: int = 5) -> tuple[float, ...]:
        """上游 `breaks_log(n, base)`：整次幂，必要时用 `log_sub_breaks` 补细分。"""
        if not (high > 0):
            return ()
        base = self.base
        low_value = max(low, 1e-300)
        span_low = math.log(low_value) / math.log(base)
        span_high = math.log(high) / math.log(base)
        minimum = math.floor(span_low)
        maximum = math.ceil(span_high)
        if maximum == minimum:
            return (base**minimum,)
        step = math.floor((maximum - minimum) / n) + 1
        while step >= 1:
            breaks = [base**exponent for exponent in range(minimum, maximum + 1, step)]
            relevant = [value for value in breaks if low <= value <= high]
            if len(relevant) >= n - 2:
                return tuple(breaks)
            step -= 1
        return _log_sub_breaks(low, high, n, base=base)


class _Log10(_Log):
    """`scales::transform_log10()`（= `transform_log(10)`）。"""

    name = "log10"

    def __init__(self) -> None:
        super().__init__(10.0)
        self.name = "log10"

    def transform(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        invalid = ~(values > 0) | ~np.isfinite(values)
        out = np.full(values.shape, np.nan)
        valid = ~invalid
        out[valid] = np.log10(values[valid])
        return out, invalid


class _Exp(_Transform):
    """`scales::transform_exp(base)`：`x → base**x`，断点仍按数据空间取默认值。

    上游 `transform_exp()` 不传 `breaks` / `domain`，所以断点是
    `extended_breaks()` 作用在**未变换**的 limits 上（`numeric-exp` 快照里 x / y
    的标签都是 1.0…3.0 就是这个原因）。
    """

    def __init__(self, base: float = math.e, name: str | None = None) -> None:
        self.base = float(base)
        self.name = name or ("exp" if self.base == math.e else f"exp{_format_base(self.base)}")

    def transform(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        with np.errstate(over="ignore", invalid="ignore"):
            out = np.power(self.base, values)
        invalid = ~np.isfinite(out)
        out = np.where(invalid, np.nan, out)
        return np.asarray(out, dtype=np.float64), invalid

    def inverse(self, values: np.ndarray) -> np.ndarray:
        out = np.array(values, dtype=np.float64, copy=True)
        out[out <= 0] = np.nan
        return np.log(out) / math.log(self.base)


def _format_base(base: float) -> str:
    """底数写进名字时不带 `.0`（`log2` / `exp2`，不是 `log2.0`）。"""
    return str(int(base)) if float(base).is_integer() else repr(float(base))


def _log_sub_breaks(low: float, high: float, n: int = 5, base: float = 10.0) -> tuple[float, ...]:
    """上游 `scales:::log_sub_breaks()`（整次幂给不出足够断点时）。"""
    if base == 10:
        minimum = math.floor(math.log10(low))
        maximum = math.ceil(math.log10(high))
    else:
        minimum = math.floor(math.log(low, base))
        maximum = math.ceil(math.log(high, base))
    if base <= 2:
        return tuple(base**exponent for exponent in range(minimum, maximum + 1))

    def delta(step: int, steps: Sequence[int]) -> float:
        values = sorted([*steps, step, float(base)])
        return min(math.log(b / a, base) for a, b in itertools.pairwise(values))

    steps = [1]
    candidates = [value for value in range(1, int(base)) if 1 < value < base]
    breaks: list[float] = []
    while candidates:
        best = max(candidates, key=lambda value: delta(value, steps))
        steps.append(best)
        candidates.remove(best)
        breaks = sorted(
            base**exponent * step for exponent in range(minimum, maximum + 1) for step in steps
        )
        if sum(1 for value in breaks if low <= value <= high) >= n - 2:
            break
    if sum(1 for value in breaks if low <= value <= high) >= n - 2:
        lower = max(next(i for i, v in enumerate(breaks) if v >= low) - 1, 0)
        upper = min(max(i for i, v in enumerate(breaks) if v <= high) + 1, len(breaks) - 1)
        return tuple(breaks[lower : upper + 1])
    return extended_breaks(low, high, n)


_TRANSFORMS: Mapping[str, Callable[[], _Transform]] = MappingProxyType(
    {
        "identity": _Identity,
        "log10": _Log10,
        "log": lambda: _Log(math.e, "log"),
        "log2": lambda: _Log(2.0),
        "exp": _Exp,
        "sqrt": _Sqrt,
        "reverse": _Reverse,
        "date": lambda: _DateTransform("date"),
        "time": lambda: _DateTransform("time"),
        "hms": lambda: _DateTransform("hms"),
    }
)

#: 尚未实现的变换：报错时点名后续任务，不静默当 identity。
_UNSUPPORTED_TRANSFORMS: Mapping[str, str] = MappingProxyType(
    {
        "log1p": "后续标度任务（M2-4 B 之后的 transform 扩展）",
        "pseudo_log": "后续标度任务（M2-4 B 之后的 transform 扩展）",
        "reciprocal": "后续标度任务（M2-4 B 之后的 transform 扩展）",
        "asn": "后续标度任务（M2-4 B 之后的 transform 扩展）",
        "atanh": "后续标度任务（M2-4 B 之后的 transform 扩展）",
        "logit": "后续标度任务（M2-4 B 之后的 transform 扩展）",
        "probit": "后续标度任务（M2-4 B 之后的 transform 扩展）",
    }
)

#: 带参数的变换：`trans=("log", 2)` / `trans=("exp", 2)`（上游的同名构造函数
#: `scales::transform_log(2)` / `transform_exp(2)`）。字符串形式只覆盖常用底数
#: （`"log2"` / `"log10"` / `"exp"` = 自然底）。
_PARAMETRIC_TRANSFORMS: Mapping[str, Callable[[float], _Transform]] = MappingProxyType(
    {
        "log": _Log,
        "exp": _Exp,
    }
)


def _trans_for(name: Any) -> _Transform:
    if isinstance(name, _Transform):
        return name
    if isinstance(name, (tuple, list)):
        if len(name) != 2 or str(name[0]) not in _PARAMETRIC_TRANSFORMS:
            raise ScaleError(
                f"未知的 trans：{name!r}（带参数的形式是 ('log', base) / ('exp', base)）"
            )
        return _PARAMETRIC_TRANSFORMS[str(name[0])](float(name[1]))
    key = "identity" if name is None else str(name)
    if key in _TRANSFORMS:
        return _TRANSFORMS[key]()
    if key in _UNSUPPORTED_TRANSFORMS:
        raise ScaleError(f"trans = {key!r} 尚未实现（留给 {_UNSUPPORTED_TRANSFORMS[key]}）")
    raise ScaleError(
        f"未知的 trans：{key!r}（已实现 identity / log / log2 / log10 / exp / sqrt / reverse / "
        "date / time / hms，以及 ('log', base) / ('exp', base)）"
    )


def _squish(values: Sequence[float], domain: tuple[float, float]) -> tuple[float, float]:
    return tuple(  # type: ignore[return-value]
        min(max(float(value), domain[0]), domain[1]) for value in values
    )


_OOB_NAMES = ("censor", "squish", "squish_infinite", "keep")


def _resolve_oob(value: Any) -> Any:
    """`oob` 参数 → `"censor"` / `"squish"` / `"squish_infinite"` / `"keep"` / 回调。

    上游接受 `scales::censor` 这类函数；Python 侧字符串写 `oob="squish"`，也可以
    直接给可调用对象 `oob=lambda values, limits: ...`。
    """
    if callable(value):
        return value
    key = "censor" if value is None else str(value)
    if key in _OOB_NAMES:
        return key
    raise ScaleError(
        f"oob = {value!r} 不支持；可用 censor / squish / squish_infinite / keep（或可调用对象）"
    )


def _apply_oob(values: np.ndarray, limits: tuple[float, float], oob: Any) -> np.ndarray:
    """上游 `oob` 四种语义；NA 始终是 NA。"""
    low, high = float(limits[0]), float(limits[1])
    out = np.array(values, dtype=np.float64, copy=True)
    if callable(oob):
        try:
            result = oob(out, (low, high))
        except TypeError:
            result = oob(out)
        return np.asarray(result, dtype=np.float64)
    if oob == "keep":
        return out
    finite = np.isfinite(out)
    if oob == "censor":
        out[finite & (out < low)] = np.nan
        out[finite & (out > high)] = np.nan
        return out
    if oob == "squish":
        out[~np.isnan(out)] = np.clip(out[~np.isnan(out)], low, high)
        return out
    # squish_infinite：只钳 ±Inf，有限越界值原样保留。
    out[out == math.inf] = high
    out[out == -math.inf] = low
    return out


# ---------------------------------------------------------------------------
# 标度基类
# ---------------------------------------------------------------------------


class ScaleBase:
    """标度的公共部分：美学名、参数、训练与映射的接口。"""

    discrete: bool = False
    #: 只有位置标度有「面板范围」（上游 view_scales_from_scale() 只服务 x / y）。
    is_position: bool = False
    default_expansion: Expansion = CONTINUOUS_EXPANSION

    def __init__(self, aesthetic: str, params: Mapping[str, Any] | None = None) -> None:
        self.aesthetic = aesthetic
        self.params: Mapping[str, Any] = MappingProxyType(dict(params or {}))
        self._trained = False
        from ggcore.axis import SecondaryAxis

        secondary = self._param("sec.axis")
        if secondary is not None and not isinstance(secondary, SecondaryAxis):
            raise ScaleError(f"sec.axis 必须是 sec_axis() / dup_axis() 的结果，收到 {secondary!r}")
        self._secondary_axis = secondary

    @property
    def secondary_axis(self) -> Any:
        """`scale_*(sec.axis = sec_axis(...))` 的第二条轴（没有就是 None）。"""
        return self._secondary_axis

    # -- 参数读取 ---------------------------------------------------------

    def _param(self, name: str, default: Any = None) -> Any:
        """读参数；R 的 `na.value` / `n.breaks` / `h.start` 与 Python 的
        `na_value` / `n_breaks` / `h_start` 两种写法都认（先查原样）。"""
        if name in self.params:
            return self.params[name]
        alternate = name.replace("_", ".") if "_" in name else name.replace(".", "_")
        if alternate in self.params:
            return self.params[alternate]
        return default

    def _has_param(self, name: str) -> bool:
        """参数是否**显式给出**（区分「没写」与「显式 None」）。

        `breaks = NULL` / `labels = NULL` 在 R 里是「不要断点 / 不要标签」，与
        `breaks = waiver()` 的默认完全不同，所以不能用 `_param(...) is None` 判断。
        """
        if name in self.params:
            return True
        alternate = name.replace("_", ".") if "_" in name else name.replace(".", "_")
        return alternate in self.params

    def reset(self) -> None:
        """`Scale$reset()`：重新训练前的钩子。默认什么都不做。

        上游 `layout$reset_scales()` 在 `compute_position()` 之后调用，紧接着用
        **stat / position 之后**的数据重训位置标度（`plot-build.R` 的第二次
        `train_position()`）。连续位置标度因此要丢弃第一段的范围
        （:meth:`ContinuousScale.reset`）；离散位置标度只能清「连续部分」
        （`range_c`，见 :meth:`ScaleSet.reset`）。分箱位置标度在这里翻到
        「stat 之后」的映射（:class:`BinnedPositionScale`）。
        """

    @property
    def expansion(self) -> Expansion:
        return Expansion.from_param(self._param("expand"), default=self.default_expansion)

    def _na_value(self, default: Any) -> Any:
        return self._param("na.value", default)

    def _limits_param(self) -> Any:
        return self._param("limits")

    # -- 训练 / 变换 / 映射 ----------------------------------------------

    def train(self, column: Column) -> None:
        raise NotImplementedError

    def transform(self, column: Column) -> Column:
        return column

    def transform_limits(self, limits: Any) -> tuple[Any, ...]:
        """数据空间的坐标 limits → 标度空间（上游 `transformation$transform()`）。

        只有连续标度真的变换；离散标度按水平序号解释，原样返回。
        """
        return tuple(limits)

    def map(self, column: Column) -> Column:
        raise NotImplementedError

    # -- 面板范围 / 断点 / 标签 ------------------------------------------

    def limits(self) -> Any:
        raise NotImplementedError

    def expanded_limits(self) -> Any:
        raise NotImplementedError

    def breaks(self) -> tuple[Any, ...]:
        raise NotImplementedError

    def minor_breaks(self) -> tuple[Any, ...]:
        """次断点（`panel.grid.minor` 的位置）；离散标度没有次要网格。"""
        return ()

    def labels(self) -> tuple[Any, ...]:
        raise NotImplementedError

    @property
    def levels(self) -> tuple[str, ...]:
        """离散标度的水平（不含 NA）；连续标度给空元组。"""
        return ()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(aesthetic={self.aesthetic!r})"


class ContinuousScale(ScaleBase):
    """连续标度：`trans` → 训练范围 → `oob` → 断点 / 标签 → 调色板。"""

    discrete = False
    default_expansion = CONTINUOUS_EXPANSION
    default_na_value: Any = float("nan")
    #: 连续标度的默认 `oob`（分箱族覆写为 squish）。
    default_oob: str = "censor"

    def __init__(self, aesthetic: str, params: Mapping[str, Any] | None = None) -> None:
        super().__init__(aesthetic, params)
        self.oob = _resolve_oob(self._param("oob", self.default_oob))
        self.transform_ = _trans_for(self._trans_request())
        self._range: tuple[float, float] | None = None
        self.non_finite_count = 0
        # `breaks = NULL` / `labels = NULL` 是显式「不要」，不是默认值。
        self.breaks_disabled = self._has_param("breaks") and self._param("breaks") is None
        self.labels_disabled = self._has_param("labels") and self._param("labels") is None

    def _trans_request(self) -> Any:
        """`trans=` 与 4.0 的 `transform=` 是同一个参数（R 里 `trans` 是弃用别名）。

        显式给出的 `transform` 优先；都没给就是 identity。
        """
        if self._has_param("trans"):
            return self._param("trans")
        if self._has_param("transform"):
            return self._param("transform")
        return "identity"

    # -- 训练 -------------------------------------------------------------

    def transform(self, column: Column) -> Column:
        values = _numeric_values(column)
        transformed, invalid = self.transform_.transform(values)
        self.non_finite_count += int(np.count_nonzero(invalid & ~np.isnan(values)))
        return _float_column(transformed)

    def train(self, column: Column) -> None:
        """训练一列**已经过 transform** 的值（上游 `ScaleContinuous$train`）。"""
        values = _numeric_values(column)
        values = values[np.isfinite(values)]
        if values.size == 0:
            return
        low = float(values.min())
        high = float(values.max())
        if self._range is None:
            self._range = (low, high)
        else:
            self._range = (min(self._range[0], low), max(self._range[1], high))
        self._trained = True

    def reset(self) -> None:
        """`Scale$reset()`：清空训练范围，等第二段训练重填。

        只对位置标度生效：非位置标度（colour / size / …）在本仓只在第一段
        训练，清空会让调色板失去范围。面板范围取「画出来的值」——`geom_hex()`
        的面板是六边形中心的范围，不是原始数据的范围（SIL-811）。
        """
        if self.is_position:
            self._range = None

    # -- 范围 -------------------------------------------------------------

    def limits(self) -> tuple[float, float]:
        explicit = self._limits_param()
        if callable(explicit):
            # 上游 `ScaleContinuous$get_limits()`：函数形态的 limits 收**变换后**的
            # 训练范围（`self$range$range`），返回值也按变换后空间消费。
            # 无数据时与上游一致，给 `c(0, 1)`。
            base = self._range if self._range is not None else (0.0, 1.0)
            computed = tuple(float(value) for value in explicit(base))
            if len(computed) != 2:
                raise ScaleError(f"函数 limits 必须返回 2 个值，收到 {computed!r}")
            return (computed[0], computed[1])
        if explicit is not None:
            pairs = list(explicit)
            if len(pairs) != 2:
                raise ScaleError(f"limits 必须是 2 元序列，收到 {explicit!r}")
            base = self._range if self._range is not None else (0.0, 1.0)
            # 显式 limits 给的是**数据空间**的值，上游 `get_limits()` 返回变换后的
            # 值（`scale_x_log10(limits = c(1, 100))$get_limits()` → `0 2`），后面
            # 的 censor / expand / breaks 全在变换后的空间里消费。单侧 `None` 取
            # 已变换的训练范围那一侧。
            low = base[0] if pairs[0] is None else self._transform_limit(float(pairs[0]))
            high = base[1] if pairs[1] is None else self._transform_limit(float(pairs[1]))
            return (low, high)
        if self._range is None:
            return (0.0, 1.0)
        return self._range

    def _transform_limit(self, value: float) -> float:
        """单个显式 limit → 变换后的空间（`log10(0)` 按约定落成 NA）。"""
        return float(self.transform_limits((value,))[0])

    def transform_limits(self, limits: Any) -> tuple[float, ...]:
        """坐标 limits → 变换后的空间（不累加 `non_finite_count`，与训练无关）。

        R 4.0.3 的 `expand_limits_scale()` 对连续标度调
        `transformation$transform(coord_limits)`；`log10(0)` / 负值在这里是
        NaN，由调用方（coord）报成明确的错误。
        """
        values = np.asarray(tuple(limits), dtype=np.float64)
        transformed, _ = self.transform_.transform(values)
        return tuple(float(value) for value in transformed)

    def expanded_limits(self) -> tuple[float, float] | None:
        if not self.is_position:
            return None
        low, high = self.limits()
        return self.expansion.apply(low, high)

    # -- 断点 / 标签 ------------------------------------------------------

    def _breaks_param(self) -> Any:
        return self._param("breaks")

    def _n_breaks(self) -> int | None:
        value = self._param("n_breaks")
        return None if value is None else int(value)

    def _raw_breaks(self, limits: Any = None) -> tuple[float, ...]:
        if self.breaks_disabled:
            return ()
        # 位置标度用 expand 后的范围（面板 / guide 看到的那一套），其余用 limits。
        # `limits` 显式给定时按它算（上游 `Scale$break_info(range)` 的入口，
        # coord limits / coord_trans 的断点走这条路）。
        limits = self.expanded_limits() or self.limits() if limits is None else tuple(limits)
        # 上游先把 domain 变换到当前空间，再 squish 到 domain（见 get_breaks()）。
        transformed_domain, _ = self.transform_.transform(
            np.asarray(self.transform_.domain, dtype=np.float64)
        )
        if all(math.isfinite(value) for value in limits):
            # reverse 的域是 (-Inf, Inf) → 变换后变成 (Inf, -Inf)，上游会 sort()。
            squish_domain = tuple(sorted(float(value) for value in transformed_domain))
            low, high = _squish(limits, squish_domain)  # type: ignore[arg-type]
        else:
            low, high = limits
        if _zero_range(low, high):
            return (low,)
        n_breaks = self._n_breaks()
        data_low, data_high = (
            float(value) for value in self.transform_.inverse(np.array([low, high])).tolist()
        )
        date_breaks = self._param("date_breaks")
        if date_breaks is not None and self.transform_.date_kind is not None:
            width = scales_date.calendar_breaks(self.transform_.date_kind, str(date_breaks))
            values = width((data_low, data_high))
        else:
            requested = self._breaks_param()
            if requested is None:
                values = self.transform_.breaks(data_low, data_high, n_breaks or 5)
            elif callable(requested):
                data_limits = self.transform_.inverse(np.array([low, high]))
                try:
                    values = (
                        tuple(requested(data_limits, n_breaks))
                        if n_breaks
                        else tuple(requested(data_limits))
                    )
                except TypeError:
                    values = tuple(requested(data_limits))
            elif isinstance(requested, Mapping):
                values = tuple(requested.keys())
            elif isinstance(requested, str) and self.transform_.date_kind is not None:
                # 上游 `datetime_scale()`：字符形态的 `breaks` / `minor_breaks` 是
                # `breaks_width(<spec>)` 的简写（`scale_x_date(breaks = "week")`）。
                width = scales_date.calendar_breaks(self.transform_.date_kind, requested)
                values = width((data_low, data_high))
            else:
                values = tuple(float(value) for value in requested)
        transformed, _ = self.transform_.transform(np.asarray(values, dtype=np.float64))
        return tuple(float(value) for value in transformed)

    def breaks(self) -> tuple[float | None, ...]:
        """面板断点（变换后的空间）；越界项是 `None`（R 的 `NA`）。"""
        low, high = sorted(self.expanded_limits() or self.limits())
        return self.breaks_in(low, high)

    def breaks_in(self, low: float, high: float) -> tuple[float | None, ...]:
        """给定范围内（**标度空间**）的断点；越界项 `None`（R `break_info(range)`）。

        `coord_cartesian(xlim=)` / `coord_trans()` 的断点要用面板自己的
        `continuous_range`，不是标度自己的 limits：R 的 `view_scales_from_scale()`
        把面板范围喂给 `scale$break_info()`。SIL-729 的
        `log10_scale_limits_coord`（1/3/10 而不是 1/10/100）钉住这条。
        """
        low, high = sorted((float(low), float(high)))
        out: list[float | None] = []
        for value in self._raw_breaks((low, high)):
            if not math.isfinite(value) or value < low or value > high:
                out.append(None)
            else:
                out.append(float(value))
        return tuple(out)

    def raw_breaks_in(self, low: float, high: float) -> tuple[float, ...]:
        """给定范围内的**未 censor** 断点（R `Scale$get_breaks(range)`）。

        `break_info()` 先拿未 censor 的主断点去算次断点（`get_breaks_minor(b=major)`），
        再 censor 主断点；极坐标的 theta 次网格要靠这条序列（见
        `ggcore.axis.polar_minor_breaks`）。
        """
        low, high = sorted((float(low), float(high)))
        return tuple(float(value) for value in self._raw_breaks((low, high)))

    def labels_in(self, breaks: Sequence[float | None]) -> tuple[str | None, ...]:
        """给定断点的标签（与 :meth:`breaks_in` 配套；R `get_labels(breaks)`）。"""
        if self.labels_disabled:
            return ()
        requested = self._param("labels")
        if requested is not None:
            return _apply_labels(requested, breaks, inverse=self.transform_.inverse)
        data_values = [
            None if value is None else float(self.transform_.inverse(np.array([value]))[0])
            for value in breaks
        ]
        date_labels = self._param("date_labels")
        if date_labels is not None and self.transform_.date_kind is not None:
            formatter = scales_date.date_formatter(self.transform_.date_kind, str(date_labels))
            return tuple(None if value is None else formatter([value])[0] for value in data_values)
        if self._date_default_breaks():
            # `pretty.Date()` 把标签挂在断点上，R 的 `format()` 走 names 分支：
            # 被 censor 的端点也带着标签（fixture 里 x_date_default 就是这样）。
            raw = self._raw_breaks()
            raw_values = [float(self.transform_.inverse(np.array([value]))[0]) for value in raw]
            return tuple(self.transform_.label(raw_values))
        return tuple(self.transform_.label(data_values))

    def minor_breaks(self) -> tuple[float, ...]:
        """次断点（`panel.grid.minor` 的位置）。

        默认 = 相邻主断点的中点（R 的 `regular_minor_breaks()`，n = 2）。

        口径照 `get_breaks_minor()`：喂进去的是**未 censor** 的主断点全序列
        （R 的注释 "major breaks are not censored"），不是 :meth:`breaks` 过滤后
        剩下的那截——先按 :meth:`breaks` 过滤会让最外两个半区间整个丢掉。R 还会
        在 limits 超出主断点两端时各补一个 `bd` 宽的端点（`regular_minor_breaks`
        的 "Allow minor breaks to extend outside major breaks towards limits"），
        让次断点能贴到面板边界；中点取完再按面板范围过滤，范围外的不画。

        位置在主断点同一个（变换后的）空间里，所以 `scale_x_log10()` 的次网格
        落在对数空间的中点，与 R 一致。SIL-725。

        `minor_breaks = NULL` 关掉次网格；给定序列 / 函数 / `date_minor_breaks`
        时按上游 `get_breaks_minor()` 的优先级消费。
        """
        if self._has_param("minor_breaks") and self._param("minor_breaks") is None:
            return ()
        low, high = sorted(self.expanded_limits() or self.limits())
        low, high = float(low), float(high)
        requested_minor = self._param("minor_breaks")
        date_minor = self._param("date_minor_breaks")
        if date_minor is not None and self.transform_.date_kind is not None:
            width = scales_date.calendar_breaks(self.transform_.date_kind, str(date_minor))
            data_low, data_high = (
                float(value) for value in self.transform_.inverse(np.array([low, high])).tolist()
            )
            transformed, _ = self.transform_.transform(np.asarray(width((data_low, data_high))))
            return tuple(value for value in transformed if low <= value <= high)
        if requested_minor is not None:
            if callable(requested_minor):
                data_limits = self.transform_.inverse(np.array([low, high]))
                try:
                    values = requested_minor(data_limits)
                except TypeError:  # 两参数形态：(limits, major_breaks)
                    values = requested_minor(
                        data_limits,
                        self.transform_.inverse(np.asarray(self._raw_breaks())),
                    )
            else:
                values = tuple(float(value) for value in requested_minor)
            transformed, _ = self.transform_.transform(np.asarray(values, dtype=np.float64))
            return tuple(value for value in transformed if low <= value <= high)
        if _zero_range(low, high):
            return ()
        values = [float(value) for value in self._raw_breaks() if math.isfinite(float(value))]
        if len(values) < 2:
            return ()
        # 主断点间距取第一段的宽度（R：`bd <- diff(b)[1]`），两端按 limits 补齐。
        step = values[1] - values[0]
        if low < values[0]:
            values.insert(0, values[0] - step)
        if high > values[-1]:
            values.append(values[-1] + step)
        midpoints = ((first + second) / 2.0 for first, second in itertools.pairwise(values))
        return tuple(value for value in midpoints if low <= value <= high)

    def labels(self) -> tuple[str | None, ...]:
        return self.labels_in(self.breaks())

    def _date_default_breaks(self) -> bool:
        return (
            self.transform_.date_kind in ("date", "time")
            and not self._has_param("breaks")
            and self._param("date_breaks") is None
        )

    # -- 映射 -------------------------------------------------------------

    def _censor(self, values: np.ndarray) -> np.ndarray:
        """按 `oob` 语义处理越界值（保留旧名字：映射路径都走这里）。"""
        return _apply_oob(values, self.limits(), self.oob)

    def map(self, column: Column) -> Column:
        values = self._censor(_numeric_values(column))
        return _float_column(self._na_fill(values, float("nan")))

    def _na_fill(self, values: np.ndarray, default: Any) -> np.ndarray:
        na_value = self._na_value(default)
        missing = np.isnan(values)
        if missing.any() and not (isinstance(na_value, float) and math.isnan(na_value)):
            values[missing] = float(na_value)
        return values

    def _rescaled(self, column: Column) -> tuple[np.ndarray, np.ndarray]:
        """`rescaler(oob(x), from = limits) → 0..1`；返回 (values, missing)。"""
        values = self._censor(_numeric_values(column))
        limits = self.limits()
        rescaled = _apply_rescaler(self._rescaler, values, limits, self)
        missing = np.isnan(rescaled)
        return rescaled, missing

    #: `continuous_scale(rescaler=...)`：默认 `scales::rescale`；面积标度用
    #: `rescale_max`，发散渐变用 `rescale_mid`。
    _rescaler: Any = "rescale"


class PositionContinuousScale(ContinuousScale):
    """连续位置标度：映射结果就是变换后的坐标值。"""

    is_position = True


class GradientScale(ContinuousScale):
    """连续 colour / fill：Lab 插值的渐变（上游 `scale_colour_gradient`）。"""

    default_na_value = "grey50"

    def __init__(self, aesthetic: str, params: Mapping[str, Any] | None = None) -> None:
        super().__init__(aesthetic, params)
        self._init_palette()

    def _init_palette(self) -> None:
        space = self._param("space", "Lab")
        if str(space).lower() != "lab":
            raise ScaleError(f"渐变插值空间 {space!r} 尚未实现（上游 4.0.3 只支持 Lab）")
        explicit = self._param("palette")
        if explicit is None:
            self._palette = gradient_pal(
                str(self._param("low", "#132B43")), str(self._param("high", "#56B1F7"))
            )
        elif callable(explicit):
            self._palette = explicit
        elif isinstance(explicit, str):
            self._palette = brewer_gradient("seq", explicit, 1)
        else:
            self._palette = colour_ramp([str(colour) for colour in explicit])

    def palette(self, positions: Sequence[float]) -> list[str]:
        return self._palette(positions)

    def map(self, column: Column) -> Column:
        rescaled, missing = self._rescaled(column)
        na_value = self._na_value(self.default_na_value)
        colours = self._palette(rescaled.tolist())
        out: list[str | None] = [
            na_value if is_missing else colour
            for colour, is_missing in zip(colours, missing.tolist(), strict=True)
        ]
        return _str_column(out)


class Gradient2Scale(GradientScale):
    """发散渐变：`low` / `mid` / `high`，`midpoint` 落在 0.5（`rescale_mid`）。"""

    _rescaler = "rescale_mid"

    def _init_palette(self) -> None:
        space = self._param("space", "Lab")
        if str(space).lower() != "lab":
            raise ScaleError(f"渐变插值空间 {space!r} 尚未实现（上游 4.0.3 只支持 Lab）")
        explicit = self._param("colours", self._param("colors"))
        if explicit is None:
            self._palette = div_gradient_pal(
                str(self._param("low", MUTED["red"])),
                str(self._param("mid", "white")),
                str(self._param("high", MUTED["blue"])),
            )
        else:
            self._palette = gradient_n_pal(
                [str(colour) for colour in explicit],
                self._param("values"),
            )

    @property
    def _mid_transformed(self) -> float:
        midpoint = float(self._param("midpoint", 0.0))
        transformed, _ = self.transform_.transform(np.array([midpoint], dtype=np.float64))
        return float(transformed[0])


class GradientNScale(GradientScale):
    """n 色渐变：`colours`（必填）、`values` 给颜色停靠位置。"""

    def _init_palette(self) -> None:
        explicit = self._param("colours", self._param("colors"))
        if explicit is None:
            raise ScaleError("scale_*_gradientn()/stepsn() 必须给 colours（上游参数没有默认值）")
        if isinstance(explicit, str):
            raise ScaleError("colours 必须是颜色序列，不是单个字符串")
        self._palette = gradient_n_pal(
            [str(colour) for colour in explicit],
            self._param("values"),
        )


class DistillerScale(GradientNScale):
    """`scale_*_distiller()`：Brewer 7 色 → 连续渐变（默认 `direction = -1`）。"""

    def _init_palette(self) -> None:
        self._palette = brewer_gradient(
            str(self._param("type", "seq")),
            self._param("palette", 1),
            float(self._param("direction", -1.0)),
            self._param("values"),
        )


class SizeScale(ContinuousScale):
    """连续 size：面积 / 半径 / 绝对值面积三种调色板。

    - `area`（`scale_size_continuous` / `scale_size`）：`rescale(sqrt(x), range)`，
      默认 1..6；
    - `radius`（`scale_radius`）：线性 `range`，默认 1..6；
    - `absolute_area`（`scale_size_area`）：`rescale_max` 后用 `abs_area(max_size)`，
      即 `sqrt(x / max(x)) * max_size`。
    """

    default_na_value = float("nan")
    mode = "area"

    def __init__(self, aesthetic: str, params: Mapping[str, Any] | None = None) -> None:
        super().__init__(aesthetic, params)
        self._size_range = self._resolve_range("range")
        if self.mode == "absolute_area":
            self._rescaler = "rescale_max"

    def _resolve_range(self, name: str) -> tuple[float, float]:
        value = self._param(name)
        if value is None:
            return (1.0, 6.0)
        return _pair(value)

    def _size_palette(self, positions: np.ndarray) -> np.ndarray:
        if self.mode == "linear":
            return _rescale(positions, self._size_range, (0.0, 1.0))
        if self.mode == "absolute_area":
            max_size = float(self._param("max_size", 6.0))
            return np.sqrt(np.abs(positions)) * max_size
        return _rescale(np.sqrt(positions), self._size_range, (0.0, 1.0))

    def map(self, column: Column) -> Column:
        rescaled, _ = self._rescaled(column)
        values = self._size_palette(rescaled)
        values = self._na_fill(values, float("nan"))
        return _float_column(values)


class RadiusScale(SizeScale):
    """`scale_radius()`：线性映射到 `range`（默认 1..6）。"""

    mode = "linear"


class SizeScaleAbsolute(SizeScale):
    """`scale_size_area()`：`rescale_max` + `abs_area(max_size)`。"""

    mode = "absolute_area"


class AlphaScale(ContinuousScale):
    """连续 alpha：线性映射到 `range`（默认 0.1..1）。"""

    default_na_value = float("nan")
    default_range = (0.1, 1.0)

    def __init__(self, aesthetic: str, params: Mapping[str, Any] | None = None) -> None:
        super().__init__(aesthetic, params)
        value = self._param("range")
        self._alpha_range = self.default_range if value is None else _pair(value)

    def _alpha_palette(self, positions: np.ndarray) -> np.ndarray:
        return _rescale(positions, self._alpha_range, (0.0, 1.0))

    def map(self, column: Column) -> Column:
        rescaled, _ = self._rescaled(column)
        values = self._alpha_palette(rescaled)
        values = self._na_fill(values, float("nan"))
        return _float_column(values)


class LinewidthScale(AlphaScale):
    """连续 linewidth：线性映射到 `range`（默认 1..6，上游 fallback 口径）。"""

    default_range = (1.0, 6.0)


# ---------------------------------------------------------------------------
# 分箱标度（ScaleBinned）
# ---------------------------------------------------------------------------


def _cut_codes(values: np.ndarray, edges: Sequence[float], *, right: bool) -> np.ndarray:
    """R 的 `cut(x, breaks, labels = FALSE, include.lowest = TRUE)`。

    返回 1 起的箱号；`NaN` / 落在最外边界之外的值给 0（调用方再落 NA）。
    """
    edge_array = np.asarray(edges, dtype=np.float64)
    out = np.zeros(values.shape, dtype=np.int64)
    if edge_array.size < 2:
        return out
    missing = np.isnan(values)
    if right:
        # 区间 (b[i], b[i+1]]，最低值并入第一箱。
        index = np.searchsorted(edge_array, values, side="left")
        codes = index.astype(np.int64)
        codes = np.where(values <= edge_array[0], 1, codes)
        codes = np.where(values > edge_array[-1], 0, codes)
    else:
        # 区间 [b[i], b[i+1])，最高值并入最后一箱。
        index = np.searchsorted(edge_array, values, side="right")
        codes = index.astype(np.int64)
        codes = np.where(values < edge_array[0], 0, codes)
        codes = np.where(values == edge_array[-1], edge_array.size - 1, codes)
    codes = np.where((codes < 1) | (codes > edge_array.size - 1), 0, codes)
    return np.where(missing, 0, codes)


class BinnedScale(ContinuousScale):
    """分箱标度基类（上游 `ScaleBinned`）。

    断点口径逐条照 `ScaleBinned$get_breaks()`：

    - 变换后的 limits 先反变换到数据空间，`nice.breaks = TRUE` 时走变换自己的
      断点函数（默认 `extended_breaks`），否则按 `n.breaks` 等距切；
    - 用户没给 limits 时，把两端补齐到等宽的箱（必要时改写 limits）；
    - 断点结果缓存（上游 `self$breaks`），后续 `breaks()` / `map()` 共用同一份。

    `bins()` 给出「分箱边界 / 每箱颜色 / 图例断点」三件套（issue 验收）。
    """

    default_oob = "squish"
    default_na_value: Any = float("nan")

    def __init__(self, aesthetic: str, params: Mapping[str, Any] | None = None) -> None:
        super().__init__(aesthetic, params)
        self.nice_breaks = bool(self._param("nice_breaks", True))
        self.right = bool(self._param("right", True))
        self.show_limits = bool(self._param("show_limits", False))
        self._breaks_cache: tuple[float, ...] | None = None
        self._limits_override: tuple[float, float] | None = None
        self._palette_cache: list[Any] | None = None

    def limits(self) -> tuple[float, float]:
        if self._limits_override is not None:
            return self._limits_override
        return super().limits()

    # -- 断点 -------------------------------------------------------------

    def _compute_breaks(self, limits: Sequence[float]) -> tuple[float, ...]:
        if self._range is None and self._limits_param() is None:
            return ()
        data_limits = [float(value) for value in self.transform_.inverse(np.asarray(list(limits)))]
        reversed_limits = data_limits[1] < data_limits[0]
        low, high = sorted(data_limits)
        requested = self._param("breaks")
        has_breaks = self._has_param("breaks")
        n_breaks = self._n_breaks()

        if has_breaks and requested is None:
            return ()
        if has_breaks and callable(requested):
            if n_breaks is not None:
                try:
                    values = tuple(requested(np.array([low, high]), n=n_breaks))
                except TypeError:
                    values = tuple(requested(np.array([low, high]), n_breaks))
            else:
                values = tuple(requested(np.array([low, high])))
        elif has_breaks:
            values = tuple(float(value) for value in requested)
        else:
            if self.nice_breaks:
                values = self.transform_.breaks(low, high, n_breaks or 5)
            else:
                count = n_breaks if n_breaks is not None else 5
                step = (high - low) / (count + 1)
                values = tuple(low + step * index for index in range(1, count + 1))
            values = tuple(value for value in values if low <= value <= high)
            if self._limits_param() is None:
                values = tuple(value for value in values if value not in (low, high))
                count = len(values)
                if count >= 2:
                    new_low = values[0] + (values[0] - values[1])
                    new_high = values[-1] + (values[-1] - values[-2])
                    kept = list(values)
                    if values[-1] > high:
                        new_high = values[-1]
                        kept = kept[:-1]
                    if values[0] < low:
                        new_low = values[0]
                        kept = kept[1:]
                    values = tuple(kept)
                elif count == 1:
                    size = max(values[0] - low, high - values[0])
                    new_low, new_high = values[0] - size, values[0] + size
                else:
                    new_low, new_high = low, high
                    if _zero_range(new_low, new_high):
                        new_low, new_high = new_low - 0.05, new_high + 0.05
                    values = (new_low, new_high)
                new_limits = [new_low, new_high]
                transformed, _ = self.transform_.transform(np.asarray(new_limits))
                if reversed_limits:
                    self._limits_override = (float(transformed[1]), float(transformed[0]))
                else:
                    self._limits_override = (float(transformed[0]), float(transformed[1]))

        transformed, _ = self.transform_.transform(np.asarray(values, dtype=np.float64))
        return tuple(float(value) for value in transformed)

    def _get_breaks(self, limits: Sequence[float]) -> tuple[float, ...]:
        if self._breaks_cache is None:
            self._breaks_cache = self._compute_breaks(limits)
        return self._breaks_cache

    def _bin_info(self) -> tuple[tuple[float, float], tuple[float, ...]]:
        """`(limits, breaks)`：数据驱动的 limits 已扩张到相邻断点的那一对。

        与 `_compute_breaks()` 同一份缓存（上游 `ScaleBinned$get_breaks()` 的
        limits 改写副作用在第一次调用时写回 `_limits_override`）。
        """
        self._get_breaks(self.limits())
        limits = self.limits()
        breaks = tuple(value for value in self._get_breaks(limits) if math.isfinite(value))
        return (float(limits[0]), float(limits[1])), breaks

    def breaks(self) -> tuple[float | None, ...]:
        if self._range is None and self._limits_param() is None:
            return ()
        limits = self.expanded_limits() if self.is_position else self.limits()
        if limits is None:
            limits = self.limits()
        values = list(self._get_breaks(limits))
        if self.show_limits:
            values = sorted(set(values) | {float(limits[0]), float(limits[1])})
        # view_scale_primary() 会把断点 censor 到面板范围（越界 → NA）。
        low, high = sorted((float(limits[0]), float(limits[1])))
        return tuple(
            None if not math.isfinite(value) or value < low or value > high else float(value)
            for value in values
        )

    def minor_breaks(self) -> tuple[float, ...]:
        return ()

    def labels(self) -> tuple[str | None, ...]:
        if self.labels_disabled:
            return ()
        breaks = self.breaks()
        requested = self._param("labels")
        if requested is not None:
            return _apply_labels(requested, breaks, inverse=self.transform_.inverse)
        data_values = [
            None if value is None else float(self.transform_.inverse(np.array([value]))[0])
            for value in breaks
        ]
        date_labels = self._param("date_labels")
        if date_labels is not None and self.transform_.date_kind is not None:
            formatter = scales_date.date_formatter(self.transform_.date_kind, str(date_labels))
            return tuple(None if value is None else formatter([value])[0] for value in data_values)
        return tuple(self.transform_.label(data_values))

    # -- 分箱 -------------------------------------------------------------

    def _edges(self, limits: Sequence[float] | None = None) -> tuple[float, ...]:
        limits = self.limits() if limits is None else limits
        breaks = self._get_breaks(limits)
        return tuple(sorted(set([float(limits[0]), *breaks, float(limits[1])])))

    def _bin_codes(self, values: np.ndarray, limits: Sequence[float] | None = None) -> np.ndarray:
        """值 → 1 起的箱号（0 = 缺失 / 越界）。"""
        limits = self.limits() if limits is None else limits
        clipped = _apply_oob(values, (float(limits[0]), float(limits[1])), self.oob)
        return _cut_codes(clipped, self._edges(limits), right=self.right)

    def _bin_centres(self, limits: Sequence[float] | None = None) -> np.ndarray:
        """每箱的中心（变换后的空间，位置标度直接用它）。"""
        edges = np.asarray(self._edges(limits), dtype=np.float64)
        if edges.size < 2:
            return np.array([0.5])
        return (edges[:-1] + edges[1:]) / 2.0

    def _bin_midpoints(self, limits: Sequence[float] | None = None) -> np.ndarray:
        """每箱中心按 `rescaler` 重标 —— 与 R 的 `palette(midpoints)` 同一口径。

        R 在 `map()` 里对箱边界用的是 `self$rescale()`（默认 `rescale`，
        `size_area` 用 `rescale_max`，`steps2` 用 `rescale_mid`），所以颜色 /
        数值的停靠位置也必须走同一个 rescaler。
        """
        limits = self.limits() if limits is None else limits
        centres = self._bin_centres(limits)
        return _apply_rescaler(self._rescaler, centres, (float(limits[0]), float(limits[1])), self)

    def _palette_values(self, positions: np.ndarray) -> np.ndarray:  # type: ignore[override]
        raise ScaleError("分箱标度没有调色板；请用具体的颜色 / 数值分箱类")

    def _bin_outputs(self) -> list[Any]:
        """每箱的输出值（颜色或数值），按箱序。"""
        if self._palette_cache is None:
            self._palette_cache = list(self._palette_values(self._bin_midpoints()))
        return self._palette_cache

    def bin_edges(self) -> tuple[float, ...]:
        """分箱边界（变换后的空间，含最外两个 limits）。"""
        return self._edges()

    def bins(self) -> Mapping[str, Any]:
        """「分箱边界 / 每箱颜色（或数值）/ 图例断点」——issue 要求的三件套。"""
        return MappingProxyType(
            {
                "edges": self.bin_edges(),
                "values": tuple(self._bin_outputs()),
                "breaks": tuple(value for value in self.breaks() if value is not None),
            }
        )

    def _mapped_by_bin(self, column: Column) -> tuple[list[Any], np.ndarray]:
        limits = self.limits()
        values = _numeric_values(column)
        codes = self._bin_codes(values, limits)
        outputs = self._bin_outputs()
        out: list[Any] = []
        for code in codes.tolist():
            out.append(outputs[int(code) - 1] if 1 <= int(code) <= len(outputs) else None)
        return out, codes


class BinnedPositionScale(BinnedScale):
    """`scale_x_binned()` / `scale_y_binned()`：连续位置 → 箱号 / 箱中心。

    与上游 `ScaleBinnedPosition` 一样分两段：

    - 第一次 `map()`（stat 之前）返回 **1 起的箱号**（R 的整数形态，stat 因此
      把位置当离散处理）；
    - `reset()` 翻到 `after_stat` 之后，`map()` 把箱号换回**箱中心**的数值位置。

    `ggcore.build` 在 stat / position 之后、第二段训练之前调用 `reset()`，
    与上游 `layout$reset_scales()` 的位置一致。
    """

    is_position = True

    def __init__(self, aesthetic: str, params: Mapping[str, Any] | None = None) -> None:
        super().__init__(aesthetic, params)
        self.after_stat = False

    def _palette_values(self, positions: np.ndarray) -> np.ndarray:  # type: ignore[override]
        return positions

    def reset(self) -> None:
        self.after_stat = True

    def map(self, column: Column) -> Column:
        limits = self.limits()
        codes = self._bin_codes(_numeric_values(column), limits)
        if not self.after_stat:
            values = np.where(codes > 0, codes.astype(np.float64), np.nan)
            return _float_column(values)
        centres = self._bin_centres(limits)
        # stat 之后的数据里存的就是第一次 map 的箱号（上游 `x_binned`），
        # 这里按箱号取中心——不再 cut 一次。
        raw = _numeric_values(column)
        values = np.full(raw.shape, np.nan)
        for code in np.unique(raw[~np.isnan(raw)]):
            index = int(code) - 1
            if 0 <= index < len(centres):
                values[raw == code] = centres[index]
        return _float_column(values)


class BinnedGradientScale(BinnedScale, GradientScale):
    """分箱 colour / fill（`scale_*_binned` / `steps`）。"""

    default_na_value = "grey50"

    def _palette_values(self, positions: np.ndarray) -> np.ndarray:  # type: ignore[override]
        return np.asarray(self._palette(positions.tolist()), dtype=object)

    def map(self, column: Column) -> Column:
        outputs, _ = self._mapped_by_bin(column)
        na_value = self._na_value(self.default_na_value)
        return _str_column([na_value if value is None else str(value) for value in outputs])


class BinnedGradient2Scale(BinnedScale, Gradient2Scale):
    """分箱发散渐变（`scale_*_steps2`）。"""

    default_na_value = "grey50"

    def _palette_values(self, positions: np.ndarray) -> np.ndarray:  # type: ignore[override]
        return np.asarray(self._palette(positions.tolist()), dtype=object)

    def map(self, column: Column) -> Column:
        outputs, _ = self._mapped_by_bin(column)
        na_value = self._na_value(self.default_na_value)
        return _str_column([na_value if value is None else str(value) for value in outputs])


class BinnedGradientNScale(BinnedScale, GradientNScale):
    """分箱 n 色渐变（`scale_*_stepsn` / `fermenter`）。"""

    default_na_value = "grey50"

    def _palette_values(self, positions: np.ndarray) -> np.ndarray:  # type: ignore[override]
        return np.asarray(self._palette(positions.tolist()), dtype=object)

    def map(self, column: Column) -> Column:
        outputs, _ = self._mapped_by_bin(column)
        na_value = self._na_value(self.default_na_value)
        return _str_column([na_value if value is None else str(value) for value in outputs])


class FermenterScale(BinnedGradientNScale):
    """`scale_*_fermenter()`：Brewer 分箱渐变（`pal_binned(pal_brewer(...))`）。"""

    def _init_palette(self) -> None:
        self._palette = brewer_binned(
            str(self._param("type", "seq")),
            self._param("palette", 1),
            float(self._param("direction", -1.0)),
        )


class BinnedSizeScale(BinnedScale, SizeScale):
    """分箱 size（`scale_size_binned` / `scale_size_binned_area`）。"""

    def _palette_values(self, positions: np.ndarray) -> np.ndarray:  # type: ignore[override]
        return self._size_palette(positions)

    def map(self, column: Column) -> Column:
        outputs, _ = self._mapped_by_bin(column)
        values = np.asarray([np.nan if value is None else float(value) for value in outputs])
        return _float_column(values)


class BinnedSizeScaleAbsolute(BinnedSizeScale):
    """`scale_size_binned_area()`：分箱 + `rescale_max` + `abs_area`。"""

    mode = "absolute_area"


class BinnedAlphaScale(BinnedScale, AlphaScale):
    """分箱 alpha（`scale_alpha_binned`）。"""

    def _palette_values(self, positions: np.ndarray) -> np.ndarray:  # type: ignore[override]
        return self._alpha_palette(positions)

    def map(self, column: Column) -> Column:
        outputs, _ = self._mapped_by_bin(column)
        values = np.asarray([np.nan if value is None else float(value) for value in outputs])
        return _float_column(values)


class BinnedLinewidthScale(BinnedScale, LinewidthScale):
    """分箱 linewidth（`scale_linewidth_binned`）。"""

    def _palette_values(self, positions: np.ndarray) -> np.ndarray:  # type: ignore[override]
        return self._alpha_palette(positions)

    def map(self, column: Column) -> Column:
        outputs, _ = self._mapped_by_bin(column)
        values = np.asarray([np.nan if value is None else float(value) for value in outputs])
        return _float_column(values)


class BinnedColourScale(BinnedScale):
    """`scale_colour_viridis_b()`：分箱 viridis（`pal_binned(pal_viridis())`）。"""

    default_na_value = "grey50"

    def __init__(self, aesthetic: str, params: Mapping[str, Any] | None = None) -> None:
        super().__init__(aesthetic, params)
        self._discrete_palette = viridis_pal(
            alpha=float(self._param("alpha", 1.0)),
            begin=float(self._param("begin", 0.0)),
            end=float(self._param("end", 1.0)),
            direction=float(self._param("direction", 1.0)),
            option=str(self._param("option", "D")),
        )

    def _palette_values(self, positions: np.ndarray) -> np.ndarray:  # type: ignore[override]
        return np.asarray(self._discrete_palette(len(positions)), dtype=object)

    def map(self, column: Column) -> Column:
        outputs, _ = self._mapped_by_bin(column)
        na_value = self._na_value(self.default_na_value)
        return _str_column([na_value if value is None else str(value) for value in outputs])


class BinnedShapeScale(BinnedScale):
    """`scale_shape_binned()`：分箱形状。"""

    default_na_value = float("nan")

    def __init__(self, aesthetic: str, params: Mapping[str, Any] | None = None) -> None:
        super().__init__(aesthetic, params)
        self._discrete_palette = shape_pal(bool(self._param("solid", True)))

    def _palette_values(self, positions: np.ndarray) -> np.ndarray:  # type: ignore[override]
        return np.asarray(self._discrete_palette(len(positions)), dtype=object)

    def map(self, column: Column) -> Column:
        outputs, _ = self._mapped_by_bin(column)
        na_value = self._na_value(self.default_na_value)
        values = np.asarray(
            [float(na_value) if value is None else float(value) for value in outputs], dtype=float
        )
        return _float_column(values)


class BinnedLinetypeScale(BinnedScale):
    """`scale_linetype_binned()`：分箱线型。"""

    default_na_value = None

    def _palette_values(self, positions: np.ndarray) -> np.ndarray:  # type: ignore[override]
        return np.asarray(linetype_pal(len(positions)), dtype=object)

    def map(self, column: Column) -> Column:
        outputs, _ = self._mapped_by_bin(column)
        return _str_column([None if value is None else str(value) for value in outputs])


class DiscreteScale(ScaleBase):
    """离散标度：水平 → 1..n（位置）或色板 / 形状码。"""

    discrete = True
    default_expansion = DISCRETE_EXPANSION
    default_na_value: Any = None
    #: True 时把「未知水平」也当 NA 处理（位置标度）；False 时用 na.value。
    unknown_is_missing = False

    def __init__(self, aesthetic: str, params: Mapping[str, Any] | None = None) -> None:
        super().__init__(aesthetic, params)
        self._seen: dict[str, None] = {}
        self._categorical: tuple[str, ...] = ()
        self._has_missing = False
        self._drop = bool(self._param("drop", True))

    # -- 训练 -------------------------------------------------------------

    def train(self, column: Column) -> None:
        if not column.is_discrete and column.kind != "bool":
            # 数值列不进离散位置标度的训练（上游 train 走 `range_c`）。
            return
        if column.kind == "categorical" and column.levels and not self._categorical:
            self._categorical = column.levels
        values = _string_values(column)
        for item in values.tolist():
            if item is not None:
                self._seen.setdefault(item, None)
        if bool(column.na_mask.any()):
            self._has_missing = True
        self._trained = True

    # -- 范围 -------------------------------------------------------------

    def limits(self) -> tuple[str | None, ...]:
        explicit = self._limits_param()
        if explicit is not None:
            return tuple(None if item is None else str(item) for item in explicit)
        levels = list(self.levels)
        if self._has_missing:
            levels.append(None)
        return tuple(levels)

    @property
    def levels(self) -> tuple[str, ...]:
        if not self._seen:
            return ()
        base = [level for level in self._categorical if level in self._seen]
        base_set = set(base)
        rest = sorted(level for level in self._seen if level not in base_set)
        ordered = base + rest
        if not self._drop and self._categorical:
            # drop = FALSE：factor 的未出现水平也保留（按 levels 顺序）。
            ordered = list(self._categorical)
        return tuple(ordered)

    def expanded_limits(self) -> tuple[float, float] | None:
        if not self.is_position:
            return None
        limits = self.limits()
        if not limits:
            return expand_range(1.0, 1.0, 0.0, 0.6)
        return expand_range(1.0, float(len(limits)), 0.0, 0.6)

    def breaks(self) -> tuple[str | None, ...]:
        return self.limits()

    def labels(self) -> tuple[str | None, ...]:
        breaks = self.breaks()
        requested = self._param("labels")
        if requested is None:
            return breaks
        return _apply_labels(requested, breaks)

    # -- 映射 -------------------------------------------------------------

    def codes(self, column: Column, *, na_as_level: bool = True) -> np.ndarray:
        """离散值 → 1 起的水平号。

        na_as_level：位置标度里 NA 本身是一个水平（上游把 NA 放进 limits，映射成
        「最后一个水平」）；colour / shape 的 NA 走 na.value，不是水平。
        """
        limits = self.limits()
        position = {level: index + 1 for index, level in enumerate(limits) if level is not None}
        na_position = None
        for index, level in enumerate(limits):
            if level is None:
                na_position = index + 1
                break
        values = _string_values(column)
        out = np.full(column.size, np.nan)
        for index, item in enumerate(values.tolist()):
            if item is None:
                out[index] = na_position if (na_as_level and na_position is not None) else np.nan
            else:
                out[index] = position.get(_level_key(item), np.nan)
        return out

    def map(self, column: Column) -> Column:
        raise NotImplementedError


class PositionDiscreteScale(DiscreteScale):
    """离散位置标度：水平 → 1..n（`mapped_discrete`，即 float）。"""

    is_position = True

    def map(self, column: Column) -> Column:
        if not column.is_discrete and column.kind != "bool":
            # 数值列原样通过（上游 `ScaleDiscrete$map` 只处理离散值），
            # 柱子的 xmin/xmax 就靠这条规则保持数值。
            return column
        return _float_column(self.codes(column))


class HueScale(DiscreteScale):
    """离散 colour / fill：`hue_pal()`（上游 `scale_colour_hue`）。

    `values=` 与 R 的 `scale_colour_manual()` 同一套口径：

    - 序列 → 按**水平顺序**逐位取色，长度不够时报错（上游同样不循环补齐）；
    - 映射（dict）→ 按**水平名**取色（`values = {"a": "red", "b": "blue"}`），
      没有对应名字的水平用 `na.value`（上游的 named manual palette）。

    子类只替换 :meth:`_default_palette`（brewer / viridis / grey / ordinal），
    手动值与映射的处理完全共用。
    """

    default_na_value = "grey50"

    def __init__(self, aesthetic: str, params: Mapping[str, Any] | None = None) -> None:
        super().__init__(aesthetic, params)
        self._values: list[Any] | None = None
        self._value_map: Mapping[str, Any] | None = None
        self._palette: Callable[[int], Sequence[str | None]] | None = None
        explicit = self._param("values")
        if explicit is not None:
            if isinstance(explicit, Mapping):
                self._value_map = MappingProxyType(
                    {str(name): _fill_value(value) for name, value in explicit.items()}
                )
            else:
                self._values = [_fill_value(value) for value in explicit]
        else:
            custom = self._param("palette")
            if callable(custom):
                self._palette = custom
            elif isinstance(custom, Sequence) and not isinstance(custom, (str, bytes)):
                self._values = [str(value) for value in custom]
            else:
                # `palette` 也可能是 brewer 的名字（"Set1"）或编号（2），那是
                # 家族自己的参数，交给 `_default_palette()` 解释。
                self._palette = self._default_palette()

    def _default_palette(self) -> Callable[[int], Sequence[str | None]]:
        return hue_pal(
            h=self._param("h", (15.0, 375.0)),
            chroma=float(self._param("c", 100.0)),
            luminance=float(self._param("l", 65.0)),
            h_start=float(self._param("h.start", 0.0)),
            direction=float(self._param("direction", 1.0)),
        )

    @property
    def has_fill_specs(self) -> bool:
        """`values` 里有没有渐变 / 图案（`scale_fill_manual(values = <FillSpec>)`）。

        这类值不是颜色串，落不进 `Column`；调用方（`build._assemble` / guide 的
        键提取）要走「逐行对象」那条路（SIL-833）。颜色项仍然按 `str()` 存
        （`colours()` 的返回值因此是混合类型），`map()` 遇到 FillSpec 会写占位色。
        """
        from ggcore.fills import FillSpec

        values = list(self._values or ())
        if self._value_map is not None:
            values += list(self._value_map.values())
        return any(isinstance(value, FillSpec) for value in values)

    def colours(self, levels: Sequence[str]) -> list[Any]:
        """按水平名给颜色；`None` = 该水平没有颜色（调用方落 `na.value`）。

        渐变 / 图案（`has_fill_specs`）原样返回，不折成字符串。
        """
        if self._value_map is not None:
            colours = [self._value_map.get(level) for level in levels]
            if levels and all(colour is None for colour in colours):
                # 上游同样会警告（「No shared levels found ...」）：名字与数据
                # 里的水平完全对不上，整列都会是 na.value。
                warnings.warn(
                    "values 的名字与数据里的水平没有交集，整列都会用 na.value",
                    UserWarning,
                    stacklevel=3,
                )
            return colours
        if self._values is not None:
            if len(self._values) < len(levels):
                raise ScaleError(
                    f"values 里有 {len(self._values)} 个颜色，但需要 {len(levels)} 个"
                    "（上游 manual scale 不允许循环补齐）"
                )
            return list(self._values[: len(levels)])
        assert self._palette is not None
        return list(self._palette(len(levels)))

    def palette(self, n: int) -> list[Any]:
        """前 n 个水平用的颜色（位置口径；命名 values 按插入序取）。"""
        if self._value_map is not None:
            return list(self._value_map.values())[:n]
        if self._values is not None:
            if len(self._values) < n:
                raise ScaleError(
                    f"values 里有 {len(self._values)} 个颜色，但需要 {n} 个"
                    "（上游 manual scale 不允许循环补齐）"
                )
            return list(self._values[:n])
        assert self._palette is not None
        return list(self._palette(n))

    def map(self, column: Column) -> Column:
        limits = self.limits()
        levels = [level for level in limits if level is not None]
        colours = self.colours(levels)
        na_value = self._na_value(self.default_na_value)
        codes = self.codes(column, na_as_level=False)
        out: list[str | None] = []
        for code in codes.tolist():
            colour: Any = None
            if not math.isnan(code) and int(code) - 1 < len(colours):
                colour = colours[int(code) - 1]
            out.append(str(na_value) if colour is None and na_value is not None else colour)
        if self.has_fill_specs:
            # 渐变 / 图案落不进字符串列：这一列只是占位（真正的填充由
            # `build._assemble` 摊成 `layer.params["fill"]`，见 `has_fill_specs`）。
            out = [
                None if item is None else (item if isinstance(item, str) else "black")
                for item in out
            ]
        return _str_column(out)


class BrewerScale(HueScale):
    """`scale_*_brewer()`：RColorBrewer 的逐 n 表（`pal_brewer()`）。

    `na.value` 缺省是 `NA`（hue 是 `"grey50"`，grey 是 `"red"`）——上游三个
    色板函数的签名不同，别统一成同一个缺省。
    """

    default_na_value = None

    def _default_palette(self) -> Callable[[int], Sequence[str | None]]:
        return brewer_pal(
            type=str(self._param("type", "seq")),
            palette=self._param("palette", 1),
            direction=float(self._param("direction", 1.0)),
        )


class ViridisScale(HueScale):
    """`scale_*_viridis_d()`：viridis 的离散色板（`pal_viridis()`），`na.value = NA`。"""

    default_na_value = None

    def _default_palette(self) -> Callable[[int], Sequence[str | None]]:
        return viridis_pal(
            alpha=float(self._param("alpha", 1.0)),
            begin=float(self._param("begin", 0.0)),
            end=float(self._param("end", 1.0)),
            direction=float(self._param("direction", 1.0)),
            option=str(self._param("option", "D")),
        )


class OrdinalColourScale(ViridisScale):
    """`scale_*_ordinal()`：缺省是 viridis 离散色板（4.0.3 的新口径）。

    `type =` 给一串颜色时走上游的 `pal_ordinal()`（`colour_ramp()` 在 0..1 上
    等距取样）；给函数/其它形态不在 gg4py 的表达范围内，构造时报错。
    """

    def _default_palette(self) -> Callable[[int], Sequence[str | None]]:
        custom = self._param("type")
        if custom is None:
            return super()._default_palette()
        if isinstance(custom, str) or callable(custom):
            raise ScaleError(
                f"scale_*_ordinal(type = {custom!r}) 未实现：需要一串颜色"
                "（或省略 type 用 viridis 缺省）"
            )
        ramp = colour_ramp([str(colour) for colour in custom])
        return lambda n: ramp(list(np.linspace(0.0, 1.0, num=n)) if n > 1 else [0.0])


class GreyScale(HueScale):
    """`scale_*_grey()`：`pal_grey(start, end)`；`na.value` 缺省是 `"red"`。"""

    default_na_value = "red"

    def _default_palette(self) -> Callable[[int], Sequence[str | None]]:
        return grey_pal(start=float(self._param("start", 0.2)), end=float(self._param("end", 0.8)))


# ---------------------------------------------------------------------------
# 离散 size / alpha / linewidth / linetype / shape
# ---------------------------------------------------------------------------


class NumericDiscreteScale(DiscreteScale):
    """离散水平 → 数值（size / alpha / linewidth 的 ordinal / manual）。

    与 :class:`HueScale` 共用 `values=` 的三种口径（序列 / 映射 / 缺省色板），
    区别只是产物是数值列而不是颜色列。默认 `na.value = NA`。
    """

    default_na_value: Any = float("nan")

    def __init__(self, aesthetic: str, params: Mapping[str, Any] | None = None) -> None:
        super().__init__(aesthetic, params)
        self._values: list[Any] | None = None
        self._value_map: Mapping[str, Any] | None = None
        self._palette: Callable[[int], Sequence[Any]] | None = None
        explicit = self._param("values")
        if explicit is not None:
            if isinstance(explicit, Mapping):
                self._value_map = MappingProxyType(
                    {str(name): value for name, value in explicit.items()}
                )
            else:
                self._values = list(explicit)
        else:
            self._palette = self._default_palette()

    def _default_palette(self) -> Callable[[int], Sequence[Any]]:
        raise NotImplementedError

    def values_for(self, levels: Sequence[str]) -> list[Any]:
        if self._value_map is not None:
            values = [self._value_map.get(level) for level in levels]
            if levels and all(value is None for value in values):
                warnings.warn(
                    "values 的名字与数据里的水平没有交集，整列都会用 na.value",
                    UserWarning,
                    stacklevel=3,
                )
            return values
        if self._values is not None:
            if len(self._values) < len(levels):
                raise ScaleError(
                    f"values 里有 {len(self._values)} 个值，但需要 {len(levels)} 个"
                    "（上游 manual scale 不允许循环补齐）"
                )
            return list(self._values[: len(levels)])
        assert self._palette is not None
        return list(self._palette(len(levels)))

    def _make_column(self, values: Sequence[Any]) -> Column:
        na_value = self._na_value(self.default_na_value)
        out = np.full(len(values), np.nan)
        for index, value in enumerate(values):
            if value is None:
                out[index] = float(na_value) if na_value is not None else np.nan
            else:
                out[index] = float(value)
        return _float_column(out)

    def map(self, column: Column) -> Column:
        levels = [level for level in self.limits() if level is not None]
        values = self.values_for(levels)
        codes = self.codes(column, na_as_level=False)
        out: list[Any] = []
        for code in codes.tolist():
            value: Any = None
            if not math.isnan(code) and int(code) - 1 < len(values):
                value = values[int(code) - 1]
            out.append(value)
        return self._make_column(out)


class SizeOrdinalScale(NumericDiscreteScale):
    """`scale_size_ordinal()`：`sqrt(seq(4, 36, length.out = n))`。"""

    def _default_palette(self) -> Callable[[int], Sequence[Any]]:
        return size_ordinal_pal(self._param("range"))


class AlphaOrdinalScale(NumericDiscreteScale):
    """`scale_alpha_ordinal()`：`seq(0.1, 1, length.out = n)`。"""

    def _default_palette(self) -> Callable[[int], Sequence[Any]]:
        return alpha_ordinal_pal(self._param("range"))


class LinewidthOrdinalScale(NumericDiscreteScale):
    """`scale_linewidth_ordinal()`：`seq(2, 6, length.out = n)`。"""

    def _default_palette(self) -> Callable[[int], Sequence[Any]]:
        return linewidth_ordinal_pal(self._param("range"))


class LinetypeScale(NumericDiscreteScale):
    """离散 linetype：`pal_linetype()` 的 13 种线型串（manual 值照收）。

    映射结果是 R 的 lty 串（`"solid"` / `"22"` / `"42"` …）；手动值可以是数字
    （1..6），两种都原样进列——渲染期 `gpar(lty=)` 两种都认。
    """

    default_na_value = None

    def _default_palette(self) -> Callable[[int], Sequence[Any]]:
        return linetype_pal

    def _make_column(self, values: Sequence[Any]) -> Column:
        if all(value is None or isinstance(value, str) for value in values):
            return _str_column([None if value is None else str(value) for value in values])
        out = np.full(len(values), np.nan)
        for index, value in enumerate(values):
            if value is not None:
                out[index] = float(value)
        return _float_column(out)


class ShapeScale(NumericDiscreteScale):
    """离散 shape：默认实心形状 16/17/15/3/7/8（上游 `pal_shape()`）。

    超过 6 个水平时上游发 warning 并把多出来的水平映射成 NA；这里同样落成 NA
    （不报错），并发一条 `UserWarning`。
    """

    default_na_value = float("nan")

    def _default_palette(self) -> Callable[[int], Sequence[Any]]:
        return shape_pal(bool(self._param("solid", True)))


# ---------------------------------------------------------------------------
# 分箱标度（shape / linetype / size_area / linewidth / viridis_b）
# ---------------------------------------------------------------------------


def _apply_labels(
    requested: Any,
    breaks: Sequence[Any],
    *,
    inverse: Callable[[np.ndarray], np.ndarray] | None = None,
) -> tuple[str | None, ...]:
    """`labels=` 的三种形态：序列（按位置）/ 映射（按断点值）/ 字符串格式。"""
    data_values: list[Any]
    if inverse is None:
        data_values = list(breaks)
    else:
        data_values = [
            None if value is None else float(inverse(np.array([value]))[0]) for value in breaks
        ]

    if callable(requested):
        # 上游 `Scale$get_labels()`：回调只收**未 censor** 的断点，NA 位置留空。
        present = [value for value in data_values if value is not None]
        labels = list(requested(present)) if present else []
        if len(labels) != len(present):
            raise ScaleError(
                f"labels 回调返回 {len(labels)} 项，断点有 {len(present)} 项（上游要求等长）"
            )
        out: list[str | None] = []
        for value in data_values:
            # `plotmath.MathText` 是 `str` 子类：保留标记（`label_math()` 的回调
            # 返回 plotmath 源串，`str()` 会把多段 run 的信息抹掉）。
            out.append(None if value is None else _as_label(labels.pop(0)))
        return tuple(out)
    if isinstance(requested, Mapping):
        out: list[str | None] = []
        for value in data_values:
            if value is None:
                out.append(None)
                continue
            key = value
            if key not in requested and str(key) in requested:
                key = str(key)
            label = requested.get(key)
            out.append(None if label is None else str(label))
        return tuple(out)
    if isinstance(requested, str):
        if "%" not in requested:
            return tuple(None if value is None else requested for value in data_values)
        return tuple(None if value is None else requested % value for value in data_values)
    values = list(requested)
    if len(values) != len(breaks):
        raise ScaleError(f"labels 有 {len(values)} 项，breaks 有 {len(breaks)} 项（上游要求等长）")
    return tuple(None if value is None else _as_label(value) for value in values)


def _as_label(value: Any) -> str:
    """标签取值 → `str`；`MathText` 原样保留（不把 plotmath 标记抹成普通文本）。"""
    return value if isinstance(value, str) else str(value)


def label_math(
    expr: Any = "10^.x",
    format: Any = None,
) -> Callable[[Sequence[Any]], list[str]]:
    """`scales::label_math()`：断点 → plotmath 表达式（缺省 `10^.x`）。

    - `expr` 是 plotmath 源串模板，`.x` 换成格式化后的断点（`10^.x` + 断点 2
      → `10^2`）；也可以给回调 `f(值文本) -> 源串`。
    - `format` 是逐值的格式化回调（上游 `format = force` 即 R 的 `format()`）；
      不给时按 R 的 `format()` 口径取 7 位有效数字。

    返回的每一项都带 `plotmath.MathText` 标记，轴带 / strip 因此按多段 run 落字
    （底数与指数两个字号），量宽与占高也按 run 之和走（`ggcore.axis`）。
    """

    def format_labels(values: Sequence[Any]) -> list[str]:
        out: list[str] = []
        for value in values:
            text = _math_value(value, format)
            source = str(expr(text)) if callable(expr) else str(expr).replace(".x", text)
            out.append(plotmath.wrap(source))
        return out

    return format_labels


def _math_value(value: Any, formatter: Any = None) -> str:
    """plotmath 模板里的值文本：R 的 `format()` 口径（7 位有效数字、整数不带 `.0`）。"""
    if formatter is not None and callable(formatter):
        return str(formatter(value))
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isfinite(number) and number.is_integer():
        return str(int(number))
    return f"{number:.7g}"


# ---------------------------------------------------------------------------
# 组件 → 实现
# ---------------------------------------------------------------------------

#: 标度参数里没有实现的项：点名报错，不静默忽略。M2-1 起 `sec.axis` 已实现
#: （`sec_axis()` / `dup_axis()`，见 `ggcore.axis`），这里只剩空表——保留入口
#: 是为了后续标度任务继续往这里登记。
_UNIMPLEMENTED_SCALE_PARAMS: Mapping[str, str] = MappingProxyType({})


def reject_unimplemented_scale_params(name: str, params: Mapping[str, Any]) -> None:
    """标度参数的校验（构造与解析两条路径都调用）。

    现在只剩两件事：登记表里的未实现项（暂时为空）与 `sec.axis` 的类型检查
    ——`sec_axis()` / `dup_axis()` 之外的值不能静默吞掉（M2-1）。
    """
    for key, what in _UNIMPLEMENTED_SCALE_PARAMS.items():
        if key in params:
            raise ScaleError(
                f"{name}({key} = ...) 未实现：{what}（见 docs/notes/guide.md「未实现」）"
            )
    secondary = params.get("sec.axis", params.get("sec_axis"))
    if secondary is not None:
        from ggcore.axis import SecondaryAxis

        if not isinstance(secondary, SecondaryAxis):
            raise ScaleError(
                f"{name}(sec.axis = ...) 必须是 sec_axis() / dup_axis() 的结果，"
                f"收到 {secondary!r}（见 docs/notes/coord.md「次轴」）"
            )


#: 实现族 → 具体类（分箱族用 MRO 把「断点/分箱」与「调色板」拼起来）。
_FAMILY_BUILDERS: Mapping[str, type[ScaleBase]] = MappingProxyType(
    {
        "position": PositionContinuousScale,
        "position_binned": BinnedPositionScale,
        "gradient": GradientScale,
        "gradient2": Gradient2Scale,
        "gradientn": GradientNScale,
        "binned": BinnedGradientScale,
        "binned2": BinnedGradient2Scale,
        "binnedn": BinnedGradientNScale,
        "distiller": DistillerScale,
        "fermenter": FermenterScale,
        "alpha": AlphaScale,
        "alpha_binned": BinnedAlphaScale,
        "size_area": SizeScale,
        "size_area_absolute": SizeScaleAbsolute,
        "size_binned": BinnedSizeScale,
        "size_binned_absolute": BinnedSizeScaleAbsolute,
        "radius": RadiusScale,
        "linewidth": LinewidthScale,
        "linewidth_binned": BinnedLinewidthScale,
        "shape": ShapeScale,
    }
)


class DiscreteIdentityScale(DiscreteScale):
    """`scale_*_identity()`（离散）：映射**原样通过**（上游 `pal_identity()`）。

    上游的 identity 标度挂在**连续** Range 上，字符 / 颜色值训练不进去，所以
    `get_limits()` 恒为 `(0, 1)`、`get_breaks()` 为空——图例也默认关闭
    （`guide = "none"`）。`ggcore` 照抄这个口径：`limits()` / `breaks()` 不反映
    数据，`map()` 才是唯一有意义的出口。
    """

    default_na_value = None

    def train(self, column: Column) -> None:
        self._trained = True

    @property
    def levels(self) -> tuple[str, ...]:
        return ()

    def limits(self) -> tuple[float, float]:
        return (0.0, 1.0)

    def breaks(self) -> tuple[Any, ...]:
        return ()

    def labels(self) -> tuple[Any, ...]:
        return ()

    def map(self, column: Column) -> Column:
        return column


class ContinuousIdentityScale(ScaleBase):
    """`scale_*_identity()`（连续）：值原样通过（上游 `ScaleContinuousIdentity`）。"""

    default_na_value = float("nan")

    def train(self, column: Column) -> None:
        # 与离散 identity 同口径：上游的 identity 标度不训练范围（`get_limits()`
        # 恒为 `(0, 1)`、断点为空），map() 原样返回。
        self._trained = True

    def limits(self) -> tuple[float, float]:
        explicit = self._limits_param()
        return (0.0, 1.0) if explicit is None else _pair(explicit)

    def expanded_limits(self) -> tuple[float, float] | None:
        return None

    def breaks(self) -> tuple[float, ...]:
        return ()

    def labels(self) -> tuple[str, ...]:
        return ()

    def map(self, column: Column) -> Column:
        return column


def scale_type(value: Any) -> tuple[str, ...]:
    """上游 `scale_type()`：一个向量该用哪类标度（R 返回字符向量，这里是元组）。

    `ordered` factor → `("ordinal", "discrete")`；`Date` → `("date", "continuous")`；
    `POSIXct` → `("datetime", "continuous")`；其余数值 → `("continuous",)`，
    字符 / 逻辑 / 普通 factor → `("discrete",)`。
    """
    if isinstance(value, Column):
        kind = value.kind
        if kind in ("int", "float"):
            return ("continuous",)
        if kind == "date":
            return ("date", "continuous")
        if kind == "datetime":
            return ("datetime", "continuous")
        if kind == "timedelta":
            return ("continuous",)
        return ("discrete",)
    if isinstance(value, (str, bytes)) or isinstance(value, Mapping):
        return ("discrete",)
    if isinstance(value, bool):
        return ("discrete",)
    if isinstance(value, (int, float)):
        return ("continuous",)
    items = list(value) if not isinstance(value, (int, float)) else []
    if items and all(isinstance(item, _dt.datetime) for item in items):
        return ("datetime", "continuous")
    if items and all(isinstance(item, _dt.date) for item in items):
        return ("date", "continuous")
    if items and all(isinstance(item, str) for item in items):
        return ("discrete",)
    if items and all(isinstance(item, bool) for item in items):
        return ("discrete",)
    numbers = all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in items)
    if items and numbers:
        return ("continuous",)
    return ("continuous",)


#: R 里直接 abort 的标度名：连续变量不能映射到 shape / linetype。上游是
#: `cli_abort()`，这里在构造与解析两条路径上都报错（消息照抄上游英文）。
_UNSUPPORTED_SCALE_NAMES: Mapping[str, str] = MappingProxyType(
    {
        "shape_continuous": (
            "A continuous variable cannot be mapped to the shape aesthetic. "
            "Choose a different aesthetic or use scale_shape_binned()."
        ),
        "linetype_continuous": (
            "A continuous variable cannot be mapped to the linetype aesthetic. "
            "Choose a different aesthetic or use scale_linetype_binned()."
        ),
    }
)


def reject_unsupported_scale(name: str) -> None:
    """R 里直接 abort 的标度名（连续 → shape / linetype）→ `ScaleError`。"""
    message = _UNSUPPORTED_SCALE_NAMES.get(name)
    if message is not None:
        raise ScaleError(f"{name}(): {message}")


def _warn_ordinal(name: str, message: str) -> None:
    warnings.warn(f"{name}(): {message}", UserWarning, stacklevel=4)


def _viridis_continuous(aesthetic: str, params: Mapping[str, Any]) -> ScaleBase:
    """`scale_*_viridis_c()`：viridis 6 色 → 连续渐变（上游 `pal_viridis()` 插值）。"""
    colours = viridis_pal(
        alpha=float(params.get("alpha", 1.0)),
        begin=float(params.get("begin", 0.0)),
        end=float(params.get("end", 1.0)),
        direction=float(params.get("direction", 1.0)),
        option=str(params.get("option", "D")),
    )(6)
    return GradientNScale(aesthetic, {**params, "colours": [str(c) for c in colours if c]})


def _size_ordinal_scale(aesthetic: str, params: Mapping[str, Any]) -> ScaleBase:
    _warn_ordinal("size_discrete", "Using size for a discrete variable is not advised.")
    return SizeOrdinalScale(aesthetic, params)


def _alpha_ordinal_scale(aesthetic: str, params: Mapping[str, Any]) -> ScaleBase:
    _warn_ordinal("alpha_discrete", "Using alpha for a discrete variable is not advised.")
    return AlphaOrdinalScale(aesthetic, params)


def _linewidth_ordinal_scale(aesthetic: str, params: Mapping[str, Any]) -> ScaleBase:
    _warn_ordinal("linewidth_discrete", "Using linewidth for a discrete variable is not advised.")
    return LinewidthOrdinalScale(aesthetic, params)


def _shape_ordinal_scale(aesthetic: str, params: Mapping[str, Any]) -> ScaleBase:
    _warn_ordinal("shape_ordinal", "Using shapes for an ordinal variable is not advised")
    return ShapeScale(aesthetic, params)


def _manual_scale_for(aesthetic: str, params: Mapping[str, Any]) -> ScaleBase:
    """`scale_discrete_manual(aesthetics = ...)`：按美学挑 manual 实现。"""
    if aesthetic in ("colour", "fill"):
        return HueScale(aesthetic, params)
    if aesthetic == "shape":
        return ShapeScale(aesthetic, params)
    if aesthetic == "linetype":
        return LinetypeScale(aesthetic, params)
    if aesthetic == "size":
        return SizeOrdinalScale(aesthetic, params)
    if aesthetic == "alpha":
        return AlphaOrdinalScale(aesthetic, params)
    if aesthetic == "linewidth":
        return LinewidthOrdinalScale(aesthetic, params)
    raise ScaleError(
        f"scale_discrete_manual 不认识 aesthetics = {aesthetic!r}"
        "（支持 colour / fill / shape / linetype / size / alpha / linewidth）"
    )


#: 实现族 → 具体类（分箱族用 MRO 把「断点/分箱」与「调色板」拼起来）。
#: 家族名是 `ggcore.scale_specs` 里的声明，A 段（连续侧）与 B 段（离散 / 色板）
#: 共用这一张表。
_FAMILY_BUILDERS: Mapping[str, Any] = MappingProxyType(
    {
        "position": PositionContinuousScale,
        "position_binned": BinnedPositionScale,
        "gradient": GradientScale,
        "gradient2": Gradient2Scale,
        "gradientn": GradientNScale,
        "binned": BinnedGradientScale,
        "binned2": BinnedGradient2Scale,
        "binnedn": BinnedGradientNScale,
        "distiller": DistillerScale,
        "fermenter": FermenterScale,
        "alpha": AlphaScale,
        "alpha_binned": BinnedAlphaScale,
        "size_area": SizeScale,
        "size_area_absolute": SizeScaleAbsolute,
        "size_binned": BinnedSizeScale,
        "size_binned_absolute": BinnedSizeScaleAbsolute,
        "radius": RadiusScale,
        "linewidth": LinewidthScale,
        "linewidth_binned": BinnedLinewidthScale,
        "shape": ShapeScale,
        "shape_binned": BinnedShapeScale,
        "linetype": LinetypeScale,
        "linetype_binned": BinnedLinetypeScale,
        # --- B 段（M2-4 B）：离散 / 色板 ---------------------------------
        "hue": HueScale,
        "manual_colour": HueScale,
        "brewer": BrewerScale,
        "grey": GreyScale,
        "ordinal_colour": OrdinalColourScale,
        "viridis_d": ViridisScale,
        "viridis_c": _viridis_continuous,
        "viridis_b": BinnedColourScale,
        "size_ordinal": SizeOrdinalScale,
        "size_discrete": _size_ordinal_scale,
        "alpha_ordinal": AlphaOrdinalScale,
        "alpha_discrete": _alpha_ordinal_scale,
        "linewidth_ordinal": LinewidthOrdinalScale,
        "linewidth_discrete": _linewidth_ordinal_scale,
        "shape_ordinal": _shape_ordinal_scale,
        "manual_generic": _manual_scale_for,
        "identity_discrete": DiscreteIdentityScale,
        "identity_continuous": ContinuousIdentityScale,
    }
)


def scale_from_component(spec: Scale) -> ScaleBase:
    """`components.Scale`（注册名 + 参数）→ 具体的标度实现。

    名字 → 实现族 → 构造默认值的唯一来源是 `ggcore.scale_specs`（与注册表同一
    张表）。`scale_color_*` / `scale_colour_*` / `scale_fill_*` 落到同一族。
    """
    name = spec.name
    aesthetic = spec.aesthetic
    params = dict(spec.params)
    reject_unimplemented_scale_params(name, params)
    reject_unsupported_scale(name)
    family = SCALE_FAMILIES.get(name)
    if family is None:
        builder = getattr(spec, "build_scale", None)
        if callable(builder) and getattr(type(spec), "build_scale", None) is not Scale.build_scale:
            return builder()
        raise ScaleError(f"未知的标度名 {name!r}（registry.SCALE_SPECS 里没有）")
    merged = {**SCALE_DEFAULTS[name], **params}
    if family == "discrete":
        # M1-4 的 15 个基础名字：位置离散 / shape 各有实现，其余是 hue 色板。
        if name in ("x_discrete", "y_discrete"):
            return PositionDiscreteScale(aesthetic, merged)
        if name == "shape_discrete":
            return ShapeScale(aesthetic, merged)
        return HueScale(aesthetic, merged)
    if family == "manual_generic":
        return _manual_scale_for(aesthetic, merged)
    builder = _FAMILY_BUILDERS.get(family)
    if builder is None:  # pragma: no cover - 表与实现漂移时立刻炸
        raise ScaleError(f"标度族 {family!r} 没有实现（{name}）")
    return builder(aesthetic, merged)


def _default_scale(aesthetic: str, column: Column | None) -> ScaleBase | None:
    """默认标度解析（上游 `ggplot_add.defaults` / `plot@scales$add_missing`）。

    日期时间列按**日历单位**选变换：`Date`（`kind = "date"`，天）→
    `trans = "date"`，`POSIXct`（`kind = "datetime"`，秒）→ `trans = "time"`。
    R 的 `find_scale()` 会为这两类找 `scale_<aes>_date` / `_datetime`，所以
    日期列不写 `scale_*_date()` 时断点 / 标签也走 `pretty.Date()`，而不是数值的
    `extended_breaks()`。
    """
    kind = column.kind if column is not None else "float"
    discrete = column.is_discrete if column is not None else False
    if kind == "bool":
        discrete = True
    calendar_trans = {"date": "date", "datetime": "time"}.get(kind)
    params = {"trans": calendar_trans} if calendar_trans is not None else None
    if aesthetic in POSITION_AESTHETICS:
        if discrete:
            return PositionDiscreteScale(aesthetic)
        return PositionContinuousScale(aesthetic, params)
    if aesthetic in ("colour", "fill"):
        if discrete:
            return HueScale(aesthetic)
        return GradientScale(aesthetic, params)
    if aesthetic == "size":
        return SizeScale(aesthetic, params)
    if aesthetic == "alpha":
        return AlphaScale(aesthetic, params)
    if aesthetic == "shape":
        return ShapeScale(aesthetic)
    if aesthetic == "linetype":
        return LinetypeScale(aesthetic)
    if aesthetic == "linewidth":
        return LinewidthScale(aesthetic, params)
    return None


class ScaleSet:
    """一组按美学索引的标度（`plot.scales` + 默认标度的解析结果）。

    `train(values, aesthetic)` / `map(values, aesthetic)` 是流水线接触标度的两个
    入口（`tests/test_build.py` 用自定义子类证明六阶段没有写死线性映射）。新增的
    `transform` 复现上游 `scales$transform_df()`：位置数据在训练与映射之前先做变换
    （`scale_x_log10()` 的 `$data$x` 因此是 log10 空间的值）。

    解析顺序：`plot.scales` 里的显式标度（按注册名建实现）优先；没有就按列类型
    建默认标度（位置 / colour / fill 看列是离散还是数值，size / alpha 连续，
    shape 离散）。`xmin/xmax/xend` 共用 x 标度，`ymin/ymax/yend` 共用 y 标度。
    """

    def __init__(self, specs: Mapping[str, Scale] | None = None) -> None:
        self._specs: dict[str, Scale] = dict(specs or {})
        self._scales: dict[str, ScaleBase] = {}
        self._explicit: dict[str, ScaleBase] = {
            self._canonical(name): scale_from_component(spec) for name, spec in self._specs.items()
        }
        #: 离散位置标度训练到的**连续**范围（上游 `scale$range_c$range`）：
        #: `geom_bar()` 的 `xmin` / `xmax` 是 0.55 / 1.45 这样的数值列，离散标度
        #: 不吃它们训练水平，但面板范围要把这段并进去（见 `docs/notes/coord.md`
        #: 「离散轴的连续范围」）。
        self._continuous: dict[str, tuple[float, float]] = {}

    # -- 解析 -------------------------------------------------------------

    @staticmethod
    def _canonical(aesthetic: str) -> str:
        if aesthetic in _X_ALIASES:
            return "x"
        if aesthetic in _Y_ALIASES:
            return "y"
        return aesthetic

    def _ensure(self, aesthetic: str, column: Column | None = None) -> ScaleBase | None:
        name = self._canonical(aesthetic)
        if name in self._explicit:
            return self._explicit[name]
        if name in self._scales:
            return self._scales[name]
        if column is None and name not in POSITION_AESTHETICS | frozenset(
            {"colour", "fill", "size", "alpha", "shape"}
        ):
            return None
        scale = _default_scale(name, column)
        if scale is not None:
            self._scales[name] = scale
        return scale

    def scale(self, aesthetic: str) -> ScaleBase | None:
        """某个美学的标度（没有就返回 None，不建默认标度）。"""
        name = self._canonical(aesthetic)
        if name in self._explicit:
            return self._explicit[name]
        return self._scales.get(name)

    # -- 流水线入口 -------------------------------------------------------

    def train(self, values: Any, aesthetic: str) -> None:
        column = values if isinstance(values, Column) else _column_from_array(values)
        scale = self._ensure(aesthetic, column)
        if scale is None:
            return
        if getattr(scale, "discrete", False) and not column.is_discrete and column.kind != "bool":
            # 上游 `ScaleDiscretePosition$train()` 把数值列记进 `range_c`：面板范围
            # 是「离散水平展开」与这段连续范围的并集（`expand_limits_discrete_trans()`）。
            numeric = _numeric_values(column)
            finite = numeric[np.isfinite(numeric)]
            if finite.size:
                name = self._canonical(aesthetic)
                low = float(finite.min())
                high = float(finite.max())
                current = self._continuous.get(name)
                if current is not None:
                    low = min(low, current[0])
                    high = max(high, current[1])
                self._continuous[name] = (low, high)
        scale.train(column)

    def continuous_range(self, aesthetic: str) -> tuple[float, float] | None:
        """离散位置标度的连续范围（`scale$range_c$range`）；没有就是 None。"""
        return self._continuous.get(self._canonical(aesthetic))

    def transform(self, values: Any, aesthetic: str) -> Any:
        """先做变换（上游 `scales$transform_df()`）；非连续标度原样返回。"""
        column = values if isinstance(values, Column) else _column_from_array(values)
        scale = self._ensure(aesthetic, column)
        if scale is None:
            return values
        out = scale.transform(column)
        return out if isinstance(values, Column) else out.values

    def transform_table(self, table: ColumnTable) -> ColumnTable:
        if table.nrows == 0:
            return table
        return ColumnTable(
            [
                (name, _as_column(self.transform(column, name)))
                for name, column in zip(table.names, table.columns(), strict=True)
            ],
            nrows=table.nrows,
        )

    def map(self, values: Any, aesthetic: str) -> Any:
        column = values if isinstance(values, Column) else _column_from_array(values)
        scale = self._ensure(aesthetic, column)
        if scale is None:
            return values
        mapped = scale.map(column)
        return mapped if isinstance(values, Column) else mapped.values

    # -- 查询 -------------------------------------------------------------

    @property
    def trained(self) -> Mapping[str, tuple[str, ...]]:
        """已训练的离散水平（按解析后的顺序；只读视图，不含 NA）。"""
        out: dict[str, tuple[str, ...]] = {}
        for name, scale in self._all_scales().items():
            if scale.discrete:
                levels = scale.levels
                if levels:
                    out[name] = levels
        return MappingProxyType(out)

    def levels(self, aesthetic: str) -> tuple[str, ...]:
        scale = self.scale(aesthetic)
        return () if scale is None else scale.levels

    def limits(self, aesthetic: str) -> Any:
        scale = self._ensure(aesthetic)
        return None if scale is None else scale.limits()

    def expanded_limits(self, aesthetic: str) -> Any:
        scale = self._ensure(aesthetic)
        return None if scale is None else scale.expanded_limits()

    def breaks(self, aesthetic: str) -> tuple[Any, ...]:
        scale = self._ensure(aesthetic)
        return () if scale is None else scale.breaks()

    def labels(self, aesthetic: str) -> tuple[Any, ...]:
        scale = self._ensure(aesthetic)
        return () if scale is None else scale.labels()

    def aesthetics(self) -> tuple[str, ...]:
        """当前有标度的美学（解析顺序 = 创建顺序）。"""
        return tuple(self._all_scales())

    @property
    def specs(self) -> Mapping[str, Scale]:
        """构造这张图时的显式标度组件（只读）；分面复制面板标度要用它。"""
        return MappingProxyType(dict(self._specs))

    def _all_scales(self) -> dict[str, ScaleBase]:
        merged: dict[str, ScaleBase] = {}
        for name, scale in self._explicit.items():
            merged[name] = scale
        for name, scale in self._scales.items():
            merged.setdefault(name, scale)
        return merged

    def reset(self) -> None:
        """`layout$reset_scales()`：第二段训练前让标度翻到 stat 之后的语义。

        连续位置标度清空范围（第二段训练用 stat / position 之后的数据重填）；
        离散位置标度只清「连续部分」（上游 `ScaleDiscretePosition$reset()` 只
        `range_c$reset()`——离散水平没法从数值列恢复，所以留着）。分箱位置标度
        在这里把 `map()` 从「箱号」切到「箱中心」。
        """
        self._continuous.clear()
        for scale in self._all_scales().values():
            scale.reset()


def _as_column(value: Any) -> Column:
    return value if isinstance(value, Column) else _column_from_array(value)

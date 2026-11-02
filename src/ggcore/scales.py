"""`ggcore.scales` —— ggplot2 4.0.3 的标度实现（M1-4）。

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
4. **越界 → NA**（`oob = censor`），离散标度里 NA 本身是一个水平（排在最后）。

本模块只用标准库 + numpy（X1），不 import pandas / 绘图库。
"""

from __future__ import annotations

import itertools
import math
import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import numpy as np

from ggcore.components import Scale
from ggcore.data import Column, ColumnTable

__all__ = [
    "CONTINUOUS_AESTHETICS",
    "DISCRETE_AESTHETICS",
    "POSITION_AESTHETICS",
    "Expansion",
    "ScaleError",
    "ScaleSet",
    "expand_range",
    "extended_breaks",
    "gradient_pal",
    "hex_to_lab",
    "hue_pal",
    "lab_to_hex",
    "scale_from_component",
]

#: 位置美学：x 与 y 两条通道。`xmin/xmax/xend` 共用 x 标度，`ymin/ymax/yend` 共用
#: y 标度（上游 `ggplot_global$x_aes` / `$y_aes`）。
POSITION_AESTHETICS = frozenset({"x", "y", "xmin", "xmax", "xend", "ymin", "ymax", "yend"})

#: 连续标度覆盖的美学（默认解析里位置按列类型二选一）。
CONTINUOUS_AESTHETICS = frozenset({"size", "alpha", "colour", "fill"})

#: 离散标度覆盖的美学。
DISCRETE_AESTHETICS = frozenset({"shape", "colour", "fill"})

_X_ALIASES = frozenset({"xmin", "xmax", "xend"})
_Y_ALIASES = frozenset({"ymin", "ymax", "yend"})


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
    """表示一个数至少需要几位小数（按 7 位有效数字的容差）。"""
    if value == 0 or float(value).is_integer():
        return 0
    tolerance = abs(value) * 1e-7
    for decimals in range(1, 11):
        if abs(round(value, decimals) - value) <= tolerance:
            return decimals
    return 10


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
# 颜色空间：HCL / Lab ↔ sRGB
#
# 与 R 的 farver::encode_colour()/decode_colour() 同一套常量：D65 白点、
# Lindbloom 的 XYZ↔sRGB 矩阵、sRGB 伽马。hue_pal() 的十六进制值逐字节对齐
# （n = 2/3/6 在 tests/test_scales.py 里钉死），gradient 的 Lab 插值同样逐字节。
# ---------------------------------------------------------------------------

_WHITE = (0.95047, 1.0, 1.08883)
_XYZ_TO_RGB = (
    3.2404542,
    -1.5371385,
    -0.4985314,
    -0.9692660,
    1.8760108,
    0.0415560,
    0.0556434,
    -0.2040259,
    1.0572252,
)
_RGB_TO_XYZ = (
    0.4124564,
    0.3575761,
    0.1804375,
    0.2126729,
    0.7151522,
    0.0721750,
    0.0193339,
    0.1191920,
    0.9503041,
)


def _gamma(value: float) -> float:
    return 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055


def _ungamma(value: float) -> float:
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _channel(value: float) -> int:
    return min(255, max(0, math.floor(_gamma(value) * 255 + 0.5)))


def _rgb_to_xyz(rgb: Sequence[float]) -> tuple[float, float, float]:
    r, g, b = (_ungamma(channel) for channel in rgb)
    matrix = _RGB_TO_XYZ
    return (
        matrix[0] * r + matrix[1] * g + matrix[2] * b,
        matrix[3] * r + matrix[4] * g + matrix[5] * b,
        matrix[6] * r + matrix[7] * g + matrix[8] * b,
    )


def _xyz_to_rgb(xyz: Sequence[float]) -> tuple[float, float, float]:
    x, y, z = xyz
    matrix = _XYZ_TO_RGB
    return (
        matrix[0] * x + matrix[1] * y + matrix[2] * z,
        matrix[3] * x + matrix[4] * y + matrix[5] * z,
        matrix[6] * x + matrix[7] * y + matrix[8] * z,
    )


def _xyz_to_lab(xyz: Sequence[float]) -> tuple[float, float, float]:
    white_x, white_y, white_z = _WHITE

    def pivot(value: float) -> float:
        if value > (6 / 29) ** 3:
            return value ** (1 / 3)
        return value / (3 * (6 / 29) ** 2) + 4 / 29

    fx = pivot(xyz[0] / white_x)
    fy = pivot(xyz[1] / white_y)
    fz = pivot(xyz[2] / white_z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def _lab_to_xyz(lab: Sequence[float]) -> tuple[float, float, float]:
    white_x, white_y, white_z = _WHITE
    fy = (lab[0] + 16) / 116
    fx = fy + lab[1] / 500
    fz = fy - lab[2] / 200

    def unpivot(value: float) -> float:
        if value > 6 / 29:
            return value**3
        return 3 * (6 / 29) ** 2 * (value - 4 / 29)

    return (unpivot(fx) * white_x, unpivot(fy) * white_y, unpivot(fz) * white_z)


def _hex_to_rgb(text: str) -> tuple[float, float, float]:
    value = text.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(channel * 2 for channel in value)
    if len(value) == 8:
        value = value[:6]
    if len(value) != 6:
        raise ScaleError(f"不是合法的十六进制颜色：{text!r}")
    try:
        return tuple(int(value[index : index + 2], 16) / 255 for index in (0, 2, 4))  # type: ignore[return-value]
    except ValueError as exc:
        raise ScaleError(f"不是合法的十六进制颜色：{text!r}") from exc


def _rgb_to_hex(rgb: Sequence[float]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(_channel(channel) for channel in rgb))


def hex_to_lab(text: str) -> tuple[float, float, float]:
    """`#RRGGBB` → CIELAB（D65）。"""
    return _xyz_to_lab(_rgb_to_xyz(_hex_to_rgb(text)))


def lab_to_hex(lab: Sequence[float]) -> str:
    """CIELAB（D65）→ `#RRGGBB`（越界通道钳到 0..255）。"""
    return _rgb_to_hex(_xyz_to_rgb(_lab_to_xyz(lab)))


def _hcl_to_hex(hue: float, chroma: float, luminance: float) -> str:
    """polar-LUV（R 的 `hcl()` / farver 的 `from = "hcl"`）→ `#RRGGBB`。"""
    white_x, white_y, white_z = _WHITE
    denominator = white_x + 15 * white_y + 3 * white_z
    u_white = 4 * white_x / denominator
    v_white = 9 * white_y / denominator
    if luminance <= 0:
        return "#000000"
    if luminance <= 8:
        y = white_y * luminance / 903.3
    else:
        y = white_y * ((luminance + 16) / 116) ** 3
    u = chroma * math.cos(math.radians(hue))
    v = chroma * math.sin(math.radians(hue))
    u_prime = u / (13 * luminance) + u_white
    v_prime = v / (13 * luminance) + v_white
    x = 9 * y * u_prime / (4 * v_prime)
    z = y * (12 - 3 * u_prime - 20 * v_prime) / (4 * v_prime)
    return _rgb_to_hex(_xyz_to_rgb((x, y, z)))


def hue_pal(
    h: Sequence[float] = (15.0, 375.0),
    chroma: float = 100.0,
    luminance: float = 65.0,
    h_start: float = 0.0,
    direction: float = 1.0,
) -> Callable[[int], list[str]]:
    """上游 `hue_pal()`：等距 HCL 色板，十六进制值与 R 逐字节相同。"""
    start, end = float(h[0]), float(h[1])

    def palette(n: int) -> list[str]:
        if n <= 0:
            raise ScaleError("hue 色板至少要一个颜色")
        upper = end
        if (upper - start) % 360 < 1:
            upper = upper - 360 / n
        if n == 1:
            hues = [start]
        else:
            hues = [start + index * (upper - start) / (n - 1) for index in range(n)]
        colours = [_hcl_to_hex((value + h_start) % 360, chroma, luminance) for value in hues]
        return colours[::-1] if direction == -1 else colours

    return palette


def gradient_pal(
    low: str = "#132B43", high: str = "#56B1F7"
) -> Callable[[Sequence[float]], list[str]]:
    """上游 `pal_seq_gradient(low, high, space = "Lab")`：Lab 空间线性插值。"""
    lab_low = hex_to_lab(low)
    lab_high = hex_to_lab(high)

    def palette(positions: Sequence[float]) -> list[str]:
        out: list[str] = []
        for position in positions:
            ratio = float(position)
            lab = tuple(a + (b - a) * ratio for a, b in zip(lab_low, lab_high, strict=True))
            out.append(lab_to_hex(lab))
        return out

    return palette


#: `scale_shape_discrete()` 的默认实心形状（上游 `pal_shape(solid = TRUE)`）。
_SHAPE_CODES = (16.0, 17.0, 15.0, 3.0, 7.0, 8.0)


def _rescale(
    values: np.ndarray, to: tuple[float, float], source: tuple[float, float]
) -> np.ndarray:
    """`scales::rescale(x, to, from)`（NA 保持 NA；退化区间取 to 的中点）。"""
    low, high = source
    if _zero_range(low, high) or _zero_range(*to):
        return np.where(np.isnan(values), np.nan, (to[0] + to[1]) / 2)
    return (values - low) / (high - low) * (to[1] - to[0]) + to[0]


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
    if column.kind in ("float", "int", "datetime", "timedelta"):
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


def _str_column(values: Sequence[str | None]) -> Column:
    items = list(values)
    missing = np.array([item is None for item in items], dtype=bool)
    data = np.array(["" if item is None else str(item) for item in items], dtype=object)
    return Column("str", data, na_mask=missing)


# ---------------------------------------------------------------------------
# transform（上游 `scales$transform_df`）
# ---------------------------------------------------------------------------


class _Transform:
    """连续标度的变换：`identity` / `log10`。"""

    name: str = "identity"

    def transform(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        raise NotImplementedError

    def inverse(self, values: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    @property
    def domain(self) -> tuple[float, float]:
        return (-math.inf, math.inf)

    def breaks(self, low: float, high: float, n: int = 5) -> tuple[float, ...]:
        return extended_breaks(low, high, n)


class _Identity(_Transform):
    name = "identity"

    def transform(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return values, np.isnan(values)

    def inverse(self, values: np.ndarray) -> np.ndarray:
        return values


class _Log10(_Transform):
    name = "log10"

    def transform(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """0 与负值 → NA（并计数）。

        上游把 0 落成 `-Inf`（`censor()` 只 censor 有限值），绘制时会画出无限远
        的点；这里按本任务的要求统一记 NA 并计数，见 `docs/notes/scales.md`。
        """
        invalid = ~(values > 0) | ~np.isfinite(values)
        out = np.full(values.shape, np.nan)
        valid = ~invalid
        out[valid] = np.log10(values[valid])
        return out, invalid

    def inverse(self, values: np.ndarray) -> np.ndarray:
        return np.power(10.0, values)

    @property
    def domain(self) -> tuple[float, float]:
        return (1e-100, math.inf)

    def breaks(self, low: float, high: float, n: int = 5) -> tuple[float, ...]:
        """上游 `breaks_log()`：整十次幂，必要时用 `log_sub_breaks` 补细分。"""
        if not (high > 0):
            return ()
        span_low = math.log10(max(low, 1e-300))
        span_high = math.log10(high)
        minimum = math.floor(span_low)
        maximum = math.ceil(span_high)
        if maximum == minimum:
            return (10.0**minimum,)
        step = math.floor((maximum - minimum) / n) + 1
        while step >= 1:
            breaks = [10.0**exponent for exponent in range(minimum, maximum + 1, step)]
            relevant = [value for value in breaks if low <= value <= high]
            if len(relevant) >= n - 2:
                return tuple(breaks)
            step -= 1
        return _log_sub_breaks(low, high, n)


def _log_sub_breaks(low: float, high: float, n: int = 5, base: int = 10) -> tuple[float, ...]:
    """上游 `scales:::log_sub_breaks()`（整十次幂给不出足够断点时）。"""
    minimum = math.floor(math.log10(low))
    maximum = math.ceil(math.log10(high))
    if base <= 2:
        return tuple(base**exponent for exponent in range(minimum, maximum + 1))

    def delta(step: int, steps: Sequence[int]) -> float:
        values = sorted([*steps, step, float(base)])
        return min(math.log(b / a, base) for a, b in itertools.pairwise(values))

    steps = [1]
    candidates = [value for value in range(1, base) if 1 < value < base]
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
    }
)

#: 尚未实现的变换：报错时点名后续任务，不静默当 identity。
_UNSUPPORTED_TRANSFORMS: Mapping[str, str] = MappingProxyType(
    {
        "reverse": "M1-5（coord 翻转）",
        "sqrt": "后续标度任务",
        "log2": "后续标度任务",
        "log": "后续标度任务",
        "log1p": "后续标度任务",
        "exp": "后续标度任务",
        "pseudo_log": "后续标度任务",
        "reciprocal": "后续标度任务",
    }
)


def _trans_for(name: Any) -> _Transform:
    if isinstance(name, _Transform):
        return name
    key = "identity" if name is None else str(name)
    if key in _TRANSFORMS:
        return _TRANSFORMS[key]()
    if key in _UNSUPPORTED_TRANSFORMS:
        raise ScaleError(f"trans = {key!r} 尚未实现（留给 {_UNSUPPORTED_TRANSFORMS[key]}）")
    raise ScaleError(f"未知的 trans：{key!r}（已实现 identity / log10）")


def _squish(values: Sequence[float], domain: tuple[float, float]) -> tuple[float, float]:
    return tuple(  # type: ignore[return-value]
        min(max(float(value), domain[0]), domain[1]) for value in values
    )


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

    def labels(self) -> tuple[Any, ...]:
        raise NotImplementedError

    @property
    def levels(self) -> tuple[str, ...]:
        """离散标度的水平（不含 NA）；连续标度给空元组。"""
        return ()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(aesthetic={self.aesthetic!r})"


class ContinuousScale(ScaleBase):
    """连续标度：`trans` → 训练范围 → `oob = censor` → 断点 / 标签 → 调色板。"""

    discrete = False
    default_expansion = CONTINUOUS_EXPANSION
    default_na_value: Any = float("nan")

    def __init__(self, aesthetic: str, params: Mapping[str, Any] | None = None) -> None:
        super().__init__(aesthetic, params)
        if self._param("oob", "censor") not in ("censor", None):
            raise ScaleError(
                f"oob = {self._param('oob')!r} 尚未实现；M1-4 只有 censor"
                "（oob = squish 留给后续标度任务）"
            )
        self.transform_ = _trans_for(self._param("trans", "identity"))
        self._range: tuple[float, float] | None = None
        self.non_finite_count = 0

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

    # -- 范围 -------------------------------------------------------------

    def limits(self) -> tuple[float, float]:
        explicit = self._limits_param()
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

    def _raw_breaks(self) -> tuple[float, ...]:
        # 位置标度用 expand 后的范围（面板 / guide 看到的那一套），其余用 limits。
        limits = self.expanded_limits() or self.limits()
        # 上游先把 domain 变换到当前空间，再 squish 到 domain（见 get_breaks()）。
        transformed_domain, _ = self.transform_.transform(
            np.asarray(self.transform_.domain, dtype=np.float64)
        )
        if all(math.isfinite(value) for value in limits):
            squish_domain = (float(transformed_domain[0]), float(transformed_domain[1]))
            low, high = _squish(limits, squish_domain)
        else:
            low, high = limits
        if _zero_range(low, high):
            return (low,)
        n_breaks = self._n_breaks()
        requested = self._breaks_param()
        if requested is None:
            data_low, data_high = self.transform_.inverse(np.array([low, high])).tolist()
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
        else:
            values = tuple(float(value) for value in requested)
        transformed, _ = self.transform_.transform(np.asarray(values, dtype=np.float64))
        return tuple(float(value) for value in transformed)

    def breaks(self) -> tuple[float | None, ...]:
        """面板断点（变换后的空间）；越界项是 `None`（R 的 `NA`）。"""
        low, high = sorted(self.expanded_limits() or self.limits())
        out: list[float | None] = []
        for value in self._raw_breaks():
            if not math.isfinite(value) or value < low or value > high:
                out.append(None)
            else:
                out.append(float(value))
        return tuple(out)

    def labels(self) -> tuple[str | None, ...]:
        breaks = self.breaks()
        requested = self._param("labels")
        if requested is not None:
            return _apply_labels(requested, breaks, inverse=self.transform_.inverse)
        data_values = [
            None if value is None else float(self.transform_.inverse(np.array([value]))[0])
            for value in breaks
        ]
        return tuple(format_numbers(data_values))

    # -- 映射 -------------------------------------------------------------

    def _censor(self, values: np.ndarray) -> np.ndarray:
        low, high = self.limits()
        out = np.array(values, dtype=np.float64, copy=True)
        finite = np.isfinite(out)
        out[finite & (out < low)] = np.nan
        out[finite & (out > high)] = np.nan
        return out

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
        """`rescale(oob(x), limits) → 0..1`；返回 (values, missing)。"""
        values = self._censor(_numeric_values(column))
        limits = self.limits()
        rescaled = _rescale(values, (0.0, 1.0), limits)
        missing = np.isnan(rescaled)
        return rescaled, missing


class PositionContinuousScale(ContinuousScale):
    """连续位置标度：映射结果就是变换后的坐标值。"""

    is_position = True


class GradientScale(ContinuousScale):
    """连续 colour / fill：Lab 插值的两端渐变（上游 `scale_colour_gradient`）。"""

    default_na_value = "grey50"

    def __init__(self, aesthetic: str, params: Mapping[str, Any] | None = None) -> None:
        super().__init__(aesthetic, params)
        space = self._param("space", "Lab")
        if str(space).lower() != "lab":
            raise ScaleError(f"渐变插值空间 {space!r} 尚未实现（上游 4.0.3 只支持 Lab）")
        self._palette = gradient_pal(
            str(self._param("low", "#132B43")), str(self._param("high", "#56B1F7"))
        )

    def palette(self, positions: Sequence[float]) -> list[str]:
        return self._palette(positions)

    def map(self, column: Column) -> Column:
        rescaled, missing = self._rescaled(column)
        na_value = self._na_value(self.default_na_value)
        out: list[str | None] = []
        for value, is_missing in zip(rescaled.tolist(), missing.tolist(), strict=True):
            out.append(na_value if is_missing else self._palette([value])[0])
        return _str_column(out)


class SizeScale(ContinuousScale):
    """连续 size：面积标度（`rescale(sqrt(x), 1..6, 0..1)`）。"""

    default_na_value = float("nan")

    def __init__(self, aesthetic: str, params: Mapping[str, Any] | None = None) -> None:
        super().__init__(aesthetic, params)
        self._size_range = self._resolve_range("range")

    def _resolve_range(self, name: str) -> tuple[float, float]:
        value = self._param(name)
        if value is None:
            return (1.0, 6.0)
        items = _pair(value)
        return items

    def map(self, column: Column) -> Column:
        rescaled, _ = self._rescaled(column)
        values = _rescale(np.sqrt(rescaled), self._size_range, (0.0, 1.0))
        values = self._na_fill(values, float("nan"))
        return _float_column(values)


class AlphaScale(ContinuousScale):
    """连续 alpha：线性映射到 0.1..1。"""

    default_na_value = float("nan")

    def __init__(self, aesthetic: str, params: Mapping[str, Any] | None = None) -> None:
        super().__init__(aesthetic, params)
        value = self._param("range")
        self._alpha_range = (0.1, 1.0) if value is None else _pair(value)

    def map(self, column: Column) -> Column:
        rescaled, _ = self._rescaled(column)
        values = _rescale(rescaled, self._alpha_range, (0.0, 1.0))
        values = self._na_fill(values, float("nan"))
        return _float_column(values)


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

    不认识的形态（例如把 dict 当成颜色列表迭代）会静默产出错误颜色，所以这里
    显式区分，映射按名字查。
    """

    default_na_value = "grey50"

    def __init__(self, aesthetic: str, params: Mapping[str, Any] | None = None) -> None:
        super().__init__(aesthetic, params)
        self._values: list[str] | None = None
        self._value_map: Mapping[str, str] | None = None
        self._palette: Callable[[int], Sequence[str]] | None = None
        explicit = self._param("values")
        if explicit is not None:
            if isinstance(explicit, Mapping):
                self._value_map = MappingProxyType(
                    {str(name): str(value) for name, value in explicit.items()}
                )
            else:
                self._values = [str(value) for value in explicit]
        else:
            custom = self._param("palette")
            if callable(custom):
                self._palette = custom
            elif custom is not None:
                self._values = [str(value) for value in custom]
            else:
                self._palette = hue_pal(
                    h=self._param("h", (15.0, 375.0)),
                    chroma=float(self._param("c", 100.0)),
                    luminance=float(self._param("l", 65.0)),
                    h_start=float(self._param("h.start", 0.0)),
                    direction=float(self._param("direction", 1.0)),
                )

    def colours(self, levels: Sequence[str]) -> list[str | None]:
        """按水平名给颜色；`None` = 该水平没有颜色（调用方落 `na.value`）。"""
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

    def palette(self, n: int) -> list[str]:
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
            colour: str | None = None
            if not math.isnan(code):
                colour = colours[int(code) - 1]
            out.append(str(na_value) if colour is None and na_value is not None else colour)
        return _str_column(out)


class ShapeScale(DiscreteScale):
    """离散 shape：默认实心形状 16/17/15/3/7/8（上游 `pal_shape()`）。

    超过 6 个水平时上游发 warning 并把多出来的水平映射成 NA；这里同样落成 NA
    （不报错），并发一条 `UserWarning`。
    """

    default_na_value = float("nan")

    def map(self, column: Column) -> Column:
        codes = self.codes(column, na_as_level=False)
        na_value = self._na_value(self.default_na_value)
        out = np.full(column.size, np.nan)
        overflow = False
        for index, code in enumerate(codes.tolist()):
            if math.isnan(code):
                out[index] = float(na_value) if na_value is not None else np.nan
            elif int(code) > len(_SHAPE_CODES):
                overflow = True
                out[index] = np.nan
            else:
                out[index] = _SHAPE_CODES[int(code) - 1]
        if overflow:
            warnings.warn(
                "shape 标度最多 6 个离散水平（上游同样只给 6 个），多出来的水平记 NA；"
                "需要更多形状请显式传 values",
                UserWarning,
                stacklevel=3,
            )
        return _float_column(out)


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
    return tuple(None if value is None else str(value) for value in values)


# ---------------------------------------------------------------------------
# 组件 → 实现
# ---------------------------------------------------------------------------


def scale_from_component(spec: Scale) -> ScaleBase:
    """`components.Scale`（注册名 + 参数）→ 具体的标度实现。"""
    name = spec.name
    aesthetic = spec.aesthetic
    params = dict(spec.params)
    if name in ("x_continuous", "y_continuous"):
        return PositionContinuousScale(aesthetic, params)
    if name in ("x_discrete", "y_discrete"):
        return PositionDiscreteScale(aesthetic, params)
    if name in ("x_log10", "y_log10"):
        return PositionContinuousScale(aesthetic, {**params, "trans": "log10"})
    if name in ("colour_continuous", "fill_continuous"):
        return GradientScale(aesthetic, params)
    if name in ("colour_discrete", "fill_discrete"):
        return HueScale(aesthetic, params)
    if name == "size_continuous":
        return SizeScale(aesthetic, params)
    if name == "shape_discrete":
        return ShapeScale(aesthetic, params)
    if name == "alpha_continuous":
        return AlphaScale(aesthetic, params)
    raise ScaleError(f"未知的标度名 {name!r}（registry.SCALE_SPECS 里没有）")


def _default_scale(aesthetic: str, column: Column | None) -> ScaleBase | None:
    """默认标度解析（上游 `ggplot_add.defaults` / `plot@scales$add_missing`）。"""
    kind = column.kind if column is not None else "float"
    discrete = column.is_discrete if column is not None else False
    if kind == "bool":
        discrete = True
    if aesthetic in POSITION_AESTHETICS:
        if discrete:
            return PositionDiscreteScale(aesthetic)
        return PositionContinuousScale(aesthetic)
    if aesthetic in ("colour", "fill"):
        if discrete:
            return HueScale(aesthetic)
        return GradientScale(aesthetic)
    if aesthetic == "size":
        return SizeScale(aesthetic)
    if aesthetic == "alpha":
        return AlphaScale(aesthetic)
    if aesthetic == "shape":
        return ShapeScale(aesthetic)
    return None


# ---------------------------------------------------------------------------
# ScaleSet
# ---------------------------------------------------------------------------


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
        if scale is not None:
            scale.train(column)

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

    def _all_scales(self) -> dict[str, ScaleBase]:
        merged: dict[str, ScaleBase] = {}
        for name, scale in self._explicit.items():
            merged[name] = scale
        for name, scale in self._scales.items():
            merged.setdefault(name, scale)
        return merged


def _as_column(value: Any) -> Column:
    return value if isinstance(value, Column) else _column_from_array(value)

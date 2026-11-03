"""`ggcore.palettes` —— 色板与颜色空间（ggplot2 4.0.3 / scales 1.4.0 口径）。

两类东西：

1. **颜色空间**：HCL / Lab ↔ sRGB。两条路径都是逐字节对齐 R 的，但**不是同一套
   常量**，别混用：

   - `hex_to_lab` / `lab_to_hex` / `hcl_to_hex`：farver 口径（D65、Lindbloom 矩阵），
     对应 `scales::colour_ramp()` / `farver::encode_colour()`。`hue_pal()`、
     `gradient_pal()`、`colour_ramp()` 全走这一条。
   - `srgb_to_lab_gd` / `lab_to_srgb_gd`：R `grDevices::convertColor()` 口径
     （sRGB 矩阵与白点取 R 的常量），只给 `viridis_pal()` 用——viridisLite 的
     `colorRamp(space = "Lab")` 走的是 grDevices，不是 farver。两条路径的
     Lab 值差 1e-2 量级，混用会让 viridis 的颜色差一位。

2. **色板**：`brewer_pal` / `viridis_pal` / `grey_pal` / `hue_pal` /
   `linetype_pal` / `shape_pal`，以及数值型离散调色板（`size_ordinal` 等）。
   取值表在 :mod:`ggcore.palette_data`（由 `tools/refs/palettes_ref.R` 生成，
   逐色入库），本模块只负责 R 侧那层「怎么从表里取」的逻辑。

口径全文见 `docs/notes/scales.md` §6。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from functools import lru_cache
from types import MappingProxyType

import numpy as np

from ggcore.palette_data import (
    BREWER_INFO,
    BREWER_PALETTES,
    VIRIDIS_MAP,
)

__all__ = [
    "BREWER_INFO",
    "BREWER_NAMES",
    "BREWER_PALETTES",
    "MUTED",
    "VIRIDIS_MAP",
    "abs_area_pal",
    "alpha_ordinal_pal",
    "area_pal",
    "brewer_pal",
    "colour_ramp",
    "gradient_n_pal",
    "gradient_pal",
    "grey_pal",
    "hcl_to_hex",
    "hex_to_lab",
    "hue_pal",
    "lab_to_hex",
    "lab_to_srgb_gd",
    "linetype_pal",
    "linewidth_ordinal_pal",
    "rescale_pal",
    "resolve_colour",
    "shape_pal",
    "size_ordinal_pal",
    "srgb_to_lab_gd",
    "viridis_pal",
]

Palette = Callable[..., "list"]

#: `pal_div_gradient()` 的两个端点色（ggplot2 里的 `muted("red")` /
#: `muted("blue")`，不是 R 生成的数据表，所以留在本模块而不是 `palette_data`）。
MUTED: Mapping[str, str] = MappingProxyType({"red": "#832424", "blue": "#3A3A98"})


class PaletteError(ValueError):
    """色板参数不合法（未登记的 palette / 取值个数超出表长）。"""


# ---------------------------------------------------------------------------
# farver 口径：Lab / HCL ↔ sRGB
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


_NAMED_COLOURS: Mapping[str, str] = MappingProxyType(
    {
        "white": "#FFFFFF",
        "black": "#000000",
        "red": "#FF0000",
        "green": "#00FF00",
        "blue": "#0000FF",
        "yellow": "#FFFF00",
        "cyan": "#00FFFF",
        "magenta": "#FF00FF",
        "orange": "#FFA500",
        "purple": "#A020F0",
        "pink": "#FFC0CB",
        "brown": "#A52A2A",
        "grey": "#BEBEBE",
        "gray": "#BEBEBE",
        "navy": "#000080",
        "darkgreen": "#006400",
        "darkblue": "#00008B",
        "darkred": "#8B0000",
        "darkgrey": "#A9A9A9",
        "darkgray": "#A9A9A9",
        "lightgrey": "#D3D3D3",
        "lightgray": "#D3D3D3",
    }
)


def resolve_colour(text: str) -> str:
    """R 颜色 → `#RRGGBB`：十六进制原样，`greyNN` / 常用名字查表。

    完整的 657 个 R 颜色名表归 M2-4 B 的长尾（`scale_*_manual` 之外还会用到），
    这里只收默认值会用到的常见名字；不认识的名字明确报错，不静默当黑色。
    """
    value = text.strip()
    if value.startswith("#"):
        return value
    lowered = value.lower()
    if lowered in _NAMED_COLOURS:
        return _NAMED_COLOURS[lowered]
    for prefix in ("grey", "gray"):
        if lowered.startswith(prefix) and lowered[len(prefix) :].isdigit():
            level = min(100, max(0, int(lowered[len(prefix) :])))
            channel = round(255 * level / 100)
            return f"#{channel:02X}{channel:02X}{channel:02X}"
    raise PaletteError(f"不支持的颜色名：{text!r}（请用 #RRGGBB 或常见 R 颜色名）")


def _hex_to_rgb(text: str) -> tuple[float, float, float]:
    value = resolve_colour(text).lstrip("#")
    if len(value) == 3:
        value = "".join(channel * 2 for channel in value)
    if len(value) == 8:
        value = value[:6]
    if len(value) != 6:
        raise PaletteError(f"不是合法的十六进制颜色：{text!r}")
    try:
        return (
            int(value[0:2], 16) / 255,
            int(value[2:4], 16) / 255,
            int(value[4:6], 16) / 255,
        )
    except ValueError as exc:
        raise PaletteError(f"不是合法的十六进制颜色：{text!r}") from exc


def _rgb_to_hex(rgb: Sequence[float]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(_channel(channel) for channel in rgb))


def hex_to_lab(text: str) -> tuple[float, float, float]:
    """`#RRGGBB` → CIELAB（farver 口径，D65）。"""
    return _xyz_to_lab(_rgb_to_xyz(_hex_to_rgb(text)))


def lab_to_hex(lab: Sequence[float]) -> str:
    """CIELAB（farver 口径，D65）→ `#RRGGBB`（越界通道钳到 0..255）。"""
    return _rgb_to_hex(_xyz_to_rgb(_lab_to_xyz(lab)))


def hcl_to_hex(hue: float, chroma: float, luminance: float) -> str:
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


# ---------------------------------------------------------------------------
# grDevices 口径：只给 viridis 用
#
# R 的 convertColor() 把 sRGB 矩阵与白点写成了自己的常量（白点 = 矩阵列和，
# 不是 CIE 的 0.95047/1.08883），下面这组值是从 R 4.5.3 的
# `convertColor(unit, from = "sRGB", to = "XYZ")` 读回来的原值。换成 farver 那套
# 常量会让 viridis 的 Lab 坐标差 1e-2，量化到 8 位就会掉色。
# ---------------------------------------------------------------------------

_GD_RGB_TO_XYZ = (
    (0.41682134188531705, 0.35657671707797467, 0.17980765358608541),
    (0.2149235044096166, 0.7131534341559493, 0.07192306143443417),
    (0.01953850040087425, 0.11885890569265833, 0.9469869755533833),
)
#: `_GD_RGB_TO_XYZ` 的数值逆（R 的 convertColor 也是这么求逆的，不是另抄一套
#: Lindbloom 常量：两者在第 3 位小数就分岔，混用会让 viridis 掉一位色）。
_GD_XYZ_TO_RGB = (
    (3.206520517144463, -1.5210417837736554, -0.4933108487914558),
    (-0.9719825462012319, 1.8812686516084869, 0.0416724845995893),
    (0.0558383385930979, -0.20474057484135894, 1.0609284332688589),
)
_GD_WHITE = (0.9532057125493771, 1.0, 1.0853843816469158)


def _gd_expand(value: np.ndarray) -> np.ndarray:
    """sRGB 伽马解码（R 的 `srgb2rgb`）。"""
    return np.where(value <= 0.04045, value / 12.92, ((value + 0.055) / 1.055) ** 2.4)


def _gd_compress(value: np.ndarray) -> np.ndarray:
    """sRGB 伽马编码（R 的 `rgb2srgb`）。"""
    positive = np.maximum(value, 0.0)
    return np.where(value <= 0.0031308, value * 12.92, 1.055 * positive ** (1 / 2.4) - 0.055)


def srgb_to_lab_gd(rgb: np.ndarray) -> np.ndarray:
    """`grDevices::convertColor(from = "sRGB", to = "Lab")`（输入 0..1 的 Nx3）。"""
    linear = _gd_expand(np.asarray(rgb, dtype=float))
    xyz = linear @ np.array(_GD_RGB_TO_XYZ).T
    scaled = xyz / np.array(_GD_WHITE)
    f = np.where(scaled > 0.008856, np.cbrt(scaled), 7.787 * scaled + 16 / 116)
    return np.stack(
        [116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], axis=1
    )


def lab_to_srgb_gd(lab: np.ndarray) -> np.ndarray:
    """`grDevices::convertColor(from = "Lab", to = "sRGB")`（结果可能越界，由调用方钳）。"""
    values = np.asarray(lab, dtype=float)
    fy = (values[:, 0] + 16) / 116
    fx = fy + values[:, 1] / 500
    fz = fy - values[:, 2] / 200
    f = np.stack([fx, fy, fz], axis=1)
    xyz_scaled = np.where(f > 6 / 29, f**3, 3 * (6 / 29) ** 2 * (f - 4 / 29))
    xyz = xyz_scaled * np.array(_GD_WHITE)
    linear = xyz @ np.array(_GD_XYZ_TO_RGB).T
    # R 的 convertColor 只在 **to = "sRGB"** 这条路上把结果四舍五入到 5 位小数
    # （`convertColor(Lab, "Lab", "sRGB")` 实测 0.123456… → 0.00568），其他方向
    # 都是全精度。不补这一步，viridis 会在个别通道上差 1/255。
    return np.round(_gd_compress(linear), 5)


def _gd_hex(rgb: np.ndarray, alpha: float) -> str:
    """`grDevices::rgb(r, g, b, alpha)`：钳到 0..1 后按 8 位四舍五入。"""
    channels = [min(255, max(0, math.floor(float(value) * 255 + 0.5))) for value in rgb]
    alpha_channel = min(255, max(0, math.floor(alpha * 255 + 0.5)))
    return "#{:02X}{:02X}{:02X}{:02X}".format(*channels, alpha_channel)


# ---------------------------------------------------------------------------
# 连续色带
# ---------------------------------------------------------------------------


def _map_stops(values: Sequence[float], stops: Sequence[float]) -> list[float]:
    """R 的 `approxfun(values, seq(0, 1, length.out = length(values)))`。

    `pal_gradient_n(colours, values)` 用它在把颜色停靠点放到指定的数据位置上；
    范围外的点给 `nan`（R 的 `approxfun` 默认 `rule = 1`，外推为 NA）。
    """
    xs = [index / (len(values) - 1) if len(values) > 1 else 0.0 for index in range(len(values))]
    if len(values) < 2:
        return [xs[0] for _ in stops]
    out: list[float] = []
    for value in stops:
        if value < values[0] or value > values[-1]:
            out.append(float("nan"))
            continue
        for index in range(1, len(values)):
            low, high = values[index - 1], values[index]
            if low <= value <= high:
                ratio = 0.0 if high == low else (value - low) / (high - low)
                out.append(xs[index - 1] + (xs[index] - xs[index - 1]) * ratio)
                break
        else:  # pragma: no cover - 上面已经处理了越界
            out.append(float("nan"))
    return out


def colour_ramp(
    colours: Sequence[str],
    positions: Sequence[float] | None = None,
) -> Callable[[Sequence[float]], list[str]]:
    """`scales::colour_ramp()`：Lab 空间逐段线性插值。

    与 R 同一条路径（`decode_colour(to = "lab")` + 逐通道 `approxfun`），所以
    首尾与中间点逐字节相等；`positions` 是 0..1 上的停靠位置，默认等距。
    """
    if not colours:
        raise PaletteError("colour_ramp 至少需要一个颜色")
    stops = [hex_to_lab(str(colour)) for colour in colours]
    if positions is None:
        anchors = (
            [index / (len(stops) - 1) for index in range(len(stops))] if len(stops) > 1 else [0.0]
        )
    else:
        anchors = [float(value) for value in positions]

    def palette(values: Sequence[float]) -> list[str]:
        out: list[str] = []
        for value in values:
            ratio = float(value)
            if math.isnan(ratio):
                out.append("grey50")
                continue
            ratio = min(1.0, max(0.0, ratio))
            if len(stops) == 1:
                out.append(str(colours[0]))
                continue
            for index in range(1, len(stops)):
                low, high = anchors[index - 1], anchors[index]
                if ratio <= high or index == len(stops) - 1:
                    share = 0.0 if high == low else (ratio - low) / (high - low)
                    share = min(1.0, max(0.0, share))
                    lab = tuple(
                        a + (b - a) * share
                        for a, b in zip(stops[index - 1], stops[index], strict=True)
                    )
                    out.append(lab_to_hex(lab))
                    break
        return out

    return palette


def gradient_pal(
    low: str = "#132B43", high: str = "#56B1F7"
) -> Callable[[Sequence[float]], list[str]]:
    """上游 `pal_seq_gradient(low, high, space = "Lab")`：Lab 空间线性插值。"""
    return colour_ramp((low, high))


def gradient_n_pal(
    colours: Sequence[str], values: Sequence[float] | None = None
) -> Callable[[Sequence[float]], list[str]]:
    """上游 `pal_gradient_n(colours, values)`：`values` 指定颜色停靠的数据位置。"""
    ramp = colour_ramp(colours)
    if values is None:
        return ramp
    stops = [float(value) for value in values]

    def palette(positions: Sequence[float]) -> list[str]:
        return ramp(_map_stops(stops, positions))

    return palette


# ---------------------------------------------------------------------------
# 离散色板
# ---------------------------------------------------------------------------


def _brewer_categories() -> dict[str, list[str]]:
    categories: dict[str, list[str]] = {"div": [], "qual": [], "seq": []}
    for name, (_max, kind) in BREWER_INFO.items():
        categories[kind].append(name)
    return categories


_BREWER_BY_CATEGORY = _brewer_categories()

#: 类别 → 该类的 brewer 名字（按表的顺序，`pal_name()` 的数字编号就是这里的下标 + 1）。
BREWER_NAMES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {kind: tuple(names) for kind, names in _BREWER_BY_CATEGORY.items()}
)


def brewer_name(palette: int | str, kind: str = "seq") -> str:
    """`scales::pal_name()`：数字按类别取，字符串直接用（不认识就回落 Greens）。"""
    if isinstance(palette, str):
        if palette not in BREWER_PALETTES:
            import warnings

            warnings.warn(
                f"未知的 brewer palette：{palette!r}，回落 Greens", UserWarning, stacklevel=3
            )
            return "Greens"
        return palette
    if kind not in _BREWER_BY_CATEGORY:
        raise PaletteError(f"brewer type 只能是 div / qual / seq，收到 {kind!r}")
    names = _BREWER_BY_CATEGORY[kind]
    index = int(palette)
    if not 1 <= index <= len(names):
        raise PaletteError(f"type = {kind!r} 只有 {len(names)} 个 palette，收到 {palette!r}")
    return names[index - 1]


def brewer_pal(
    type: str = "seq", palette: int | str = 1, direction: float = 1
) -> Callable[[int], list[str | None]]:
    """上游 `pal_brewer()`：`RColorBrewer::brewer.pal()` 的逐 n 表。"""
    name = brewer_name(palette, type)
    max_n = BREWER_INFO[name][0]
    table = BREWER_PALETTES[name]

    def palette_fn(n: int) -> list[str | None]:
        count = int(n)
        if count <= 0:
            return []
        if count < 3:
            # brewer.pal(n < 3) 会警告并回落到 3 色表，再取前 n 个。
            colours: list[str | None] = list(table[3][:count])
        elif count > max_n:
            # 上游同样越界：brewer.pal() 只给 maxcolors 个，余下的索引是 NA。
            colours = [*table[max_n], *([None] * (count - max_n))]
        else:
            colours = list(table[count])
        return colours[::-1] if direction == -1 else colours

    return palette_fn


_VIRIDIS_ALIASES = {
    "A": "A",
    "magma": "A",
    "B": "B",
    "inferno": "B",
    "C": "C",
    "plasma": "C",
    "D": "D",
    "viridis": "D",
    "E": "E",
    "cividis": "E",
    "F": "F",
    "rocket": "F",
    "G": "G",
    "mako": "G",
    "H": "H",
    "turbo": "H",
}


def _viridis_option(option: str) -> str:
    try:
        return _VIRIDIS_ALIASES[str(option)]
    except KeyError:
        import warnings

        warnings.warn(
            f"viridis option {option!r} 不存在，回落 viridis（D）", UserWarning, stacklevel=4
        )
        return "D"


def _fmm_coefficients(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, ...]:
    """R `stats::splinefun(method = "fmm")` 的三次样条系数 (b, c, d)。

    R 的 `spline.c`：结点 x（等距或不等距）上解三对角方程组求二阶导 M，
    两端的 M 由「端点区间的三阶导等于前/后 4 点的三阶差商」定（Forsythe-
    Malcolm-Moler 的 fmm 条件），不是 natural（M = 0）。`c = M/2`、
    `d = (M[i+1] - M[i]) / (6h)`、`b = 斜率 - h(2M[i] + M[i+1])/6`。
    """
    n = int(x.size)
    h = np.diff(x)
    slopes = np.diff(y) / h
    second = np.zeros(n)
    if n == 2:
        b = np.array([slopes[0], slopes[0]])
        return b, np.zeros(2), np.zeros(2)

    def third(left: int) -> float:
        """区间 left 起点处的三阶导（由 left..left+3 的三阶差商估计）。"""
        d0 = (y[left + 1] - y[left]) / h[left]
        d1 = (y[left + 2] - y[left + 1]) / h[left + 1]
        d2 = (y[left + 3] - y[left + 2]) / h[left + 2]
        dd0 = (d1 - d0) / (h[left] + h[left + 1])
        dd1 = (d2 - d1) / (h[left + 1] + h[left + 2])
        return 6 * (dd1 - dd0) / (h[left] + h[left + 1] + h[left + 2])

    first = third(0)
    last = third(n - 4)

    # 未知量 M[1..n-2]；M[0] = M[1] - h[0] * first，M[n-1] = M[n-2] + h[-1] * last。
    k = n - 2
    lower = np.zeros(k)
    diag = np.zeros(k)
    upper = np.zeros(k)
    rhs = np.zeros(k)
    for offset, index in enumerate(range(1, n - 1)):
        low = h[index - 1]
        high = h[index]
        if index - 1 == 0:
            diag[offset] += low
            rhs[offset] += low * h[0] * first
        else:
            lower[offset] = low
        diag[offset] += 2 * (low + high)
        if index + 1 == n - 1:
            diag[offset] += high
            rhs[offset] -= high * h[-1] * last
        else:
            upper[offset] = high
        rhs[offset] += 6 * (slopes[index] - slopes[index - 1])

    # Thomas 算法（三对角，O(n)）。
    for offset in range(1, k):
        factor = lower[offset] / diag[offset - 1]
        diag[offset] -= factor * upper[offset - 1]
        rhs[offset] -= factor * rhs[offset - 1]
    solution = np.zeros(k)
    solution[-1] = rhs[-1] / diag[-1]
    for offset in range(k - 2, -1, -1):
        solution[offset] = (rhs[offset] - upper[offset] * solution[offset + 1]) / diag[offset]
    second[1 : n - 1] = solution
    second[0] = second[1] - h[0] * first
    second[-1] = second[-2] + h[-1] * last

    b = np.zeros(n)
    c = second / 2
    d = np.zeros(n)
    for index in range(n - 1):
        b[index] = slopes[index] - h[index] * (2 * second[index] + second[index + 1]) / 6
        d[index] = (second[index + 1] - second[index]) / (6 * h[index])
    b[-1] = slopes[-1] - h[-1] * (2 * second[-1] + second[-1]) / 6
    d[-1] = d[-2]
    return b, c, d


@lru_cache(maxsize=8)
def _viridis_spline(
    option: str,
) -> tuple[np.ndarray, np.ndarray, tuple[np.ndarray, ...]]:
    """一次算好某档 viridis 的 Lab 结点与三个通道的样条系数（有缓存）。"""
    hexes = VIRIDIS_MAP[option]
    rgb = np.array([_hex_to_rgb(value) for value in hexes], dtype=float)
    lab = srgb_to_lab_gd(rgb)
    x = np.arange(len(hexes), dtype=float) * (1.0 / (len(hexes) - 1))
    coefficients = tuple(_fmm_coefficients(x, lab[:, channel]) for channel in range(3))
    return x, lab, coefficients


def _viridis_positions(n: int, begin: float, end: float) -> np.ndarray:
    """R 的 `seq(begin, end, length.out = n)`：末项**强制**等于 end（实测 R 4.5.3）。"""
    return np.linspace(begin, end, num=n) if n > 1 else np.array([begin], dtype=float)


def viridis_pal(
    alpha: float = 1.0,
    begin: float = 0.0,
    end: float = 1.0,
    direction: float = 1.0,
    option: str = "D",
) -> Callable[[int], list[str]]:
    """上游 `pal_viridis()`：`viridisLite::viridis()` 的逐色复刻。

    viridisLite 的算法：取该档 256 个量化色 → `colorRamp(space = "Lab",
    interpolate = "spline")`（grDevices 的 convertColor + fmm 样条）→ 在
    `seq(begin, end, length.out = n)` 上采样 → `rgb()` 量化。这里的每一步都
    复刻了，所以十六进制值（含 alpha 的两位）与 R 逐字节相同。
    """
    if not 0 <= begin <= 1 or not 0 <= end <= 1:
        raise PaletteError("viridis 的 begin / end 必须在 [0, 1]")
    if abs(direction) != 1:
        raise PaletteError("viridis 的 direction 只能是 1 或 -1")
    resolved = _viridis_option(option)
    start, stop = (end, begin) if direction == -1 else (begin, end)
    knots, knot_lab, coefficients = _viridis_spline(resolved)

    def palette(n: int) -> list[str]:
        count = int(n)
        if count <= 0:
            return []
        positions = _viridis_positions(count, start, stop)
        index = np.clip(np.searchsorted(knots, positions, side="right") - 1, 0, knots.size - 2)
        offset = positions - knots[index]
        labs = np.column_stack(
            [
                coefficient[0][index] * offset
                + coefficient[1][index] * offset**2
                + coefficient[2][index] * offset**3
                for coefficient in coefficients
            ]
        )
        # 加上结点的 y：样条函数 = y[i] + b t + c t² + d t³，y 是结点上的 Lab 值。
        labs += knot_lab[index]
        rgb = lab_to_srgb_gd(labs)
        return [_gd_hex(row, alpha) for row in rgb]

    return palette


def grey_pal(start: float = 0.2, end: float = 0.8) -> Callable[[int], list[str]]:
    """上游 `pal_grey()`：`grDevices::grey.colors(n, start, end)`（gamma = 2.2）。"""
    gamma = 2.2

    def palette(n: int) -> list[str]:
        count = int(n)
        if count <= 0:
            return []
        if count == 1:
            values = [start**gamma]
        else:
            first = start**gamma
            last = end**gamma
            values = [first + index * (last - first) / (count - 1) for index in range(count)]
        # grey 的取值已经是 sRGB（不是线性光），直接量化；`gray()` 走 rgb() 同一条
        # 四舍五入，不要再过一遍 `_rgb_to_hex()` 的伽马。
        return [
            "#{0:02X}{0:02X}{0:02X}".format(
                min(255, max(0, math.floor(value ** (1 / gamma) * 255 + 0.5)))
            )
            for value in values
        ]

    return palette


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
            raise PaletteError("hue 色板至少要一个颜色")
        upper = end
        if (upper - start) % 360 < 1:
            upper = upper - 360 / n
        if n == 1:
            hues = [start]
        else:
            hues = [start + index * (upper - start) / (n - 1) for index in range(n)]
        colours = [hcl_to_hex((value + h_start) % 360, chroma, luminance) for value in hues]
        return colours[::-1] if direction == -1 else colours

    return palette


# ---------------------------------------------------------------------------
# 形状 / 线型 / 数值型离散色板
# ---------------------------------------------------------------------------

#: `pal_shape(solid = TRUE/FALSE)` 的形状码（上游只给 6 个）。
SHAPE_CODES_SOLID = (16.0, 17.0, 15.0, 3.0, 7.0, 8.0)
SHAPE_CODES_OPEN = (1.0, 2.0, 0.0, 3.0, 7.0, 8.0)

#: `pal_linetype()` 的 13 种线型（R 的 lty 串）。
LINETYPE_CODES = (
    "solid",
    "22",
    "42",
    "44",
    "13",
    "1343",
    "73",
    "2262",
    "12223242",
    "F282",
    "F4448444",
    "224282F2",
    "F1",
)


def shape_pal(solid: bool = True) -> Callable[[int], list[float | None]]:
    """上游 `pal_shape()`：最多 6 个水平，多的记 None（R 是 NA + warning）。"""
    codes = SHAPE_CODES_SOLID if solid else SHAPE_CODES_OPEN

    def palette(n: int) -> list[float | None]:
        count = int(n)
        if count <= len(codes):
            return list(codes[:count])
        import warnings

        warnings.warn(
            f"shape 色板最多 {len(codes)} 个离散水平（上游同样只给 {len(codes)} 个），"
            "多出来的水平记 NA；需要更多形状请显式传 values",
            UserWarning,
            stacklevel=3,
        )
        return [*codes, *([None] * (count - len(codes)))]

    return palette


def linetype_pal(n: int) -> list[str | None]:
    """上游 `pal_linetype()`：13 种线型，超出报错（上游 manual_pal 同样 abort）。"""
    count = int(n)
    if count > len(LINETYPE_CODES):
        raise PaletteError(f"linetype 色板最多 {len(LINETYPE_CODES)} 个水平，收到 {count}")
    return list(LINETYPE_CODES[:count])


def size_ordinal_pal(
    area_range: Sequence[float] | None = None,
) -> Callable[[int], list[float]]:
    """上游 `scale_size_ordinal()` 的 fallback：`sqrt(seq(4, 36, length.out = n))`。"""
    low, high = (
        (4.0, 36.0)
        if area_range is None
        else (
            float(area_range[0]),
            float(area_range[1]),
        )
    )

    def palette(n: int) -> list[float]:
        count = int(n)
        if count == 0:
            return []
        if count == 1:
            return [math.sqrt(low)]
        step = (high - low) / (count - 1)
        values = [low + index * step for index in range(count)]
        values[-1] = high
        return [math.sqrt(value) for value in values]

    return palette


def alpha_ordinal_pal(
    value_range: Sequence[float] | None = None,
) -> Callable[[int], list[float]]:
    """上游 `scale_alpha_ordinal()` 的 fallback：`seq(0.1, 1, length.out = n)`。"""
    low, high = (
        (0.1, 1.0)
        if value_range is None
        else (
            float(value_range[0]),
            float(value_range[1]),
        )
    )
    return _linear_ordinal_pal(low, high)


def linewidth_ordinal_pal(
    value_range: Sequence[float] | None = None,
) -> Callable[[int], list[float]]:
    """上游 `scale_linewidth_ordinal()` 的 fallback：`seq(2, 6, length.out = n)`。"""
    low, high = (
        (2.0, 6.0)
        if value_range is None
        else (
            float(value_range[0]),
            float(value_range[1]),
        )
    )
    return _linear_ordinal_pal(low, high)


def _linear_ordinal_pal(low: float, high: float) -> Callable[[int], list[float]]:
    def palette(n: int) -> list[float]:
        count = int(n)
        if count == 0:
            return []
        if count == 1:
            return [low]
        # R 的 `seq(low, high, length.out = n)`：末项强制等于 high。
        step = (high - low) / (count - 1)
        values = [low + index * step for index in range(count)]
        values[-1] = high
        return values

    return palette


def area_pal(size_range: Sequence[float] | None = None) -> Callable[[float], float]:
    """上游 `pal_area(range)`：(0..1) → `range`，先开方（面积标度）。"""
    low, high = (
        (1.0, 6.0)
        if size_range is None
        else (
            float(size_range[0]),
            float(size_range[1]),
        )
    )

    def palette(value: float) -> float:
        return low + (high - low) * math.sqrt(max(0.0, float(value)))

    return palette


def rescale_pal(value_range: Sequence[float] | None = None) -> Callable[[float], float]:
    """上游 `pal_rescale(range)`：(0..1) → `range`（线性，`scale_radius` / linewidth）。"""
    low, high = (
        (0.1, 1.0)
        if value_range is None
        else (
            float(value_range[0]),
            float(value_range[1]),
        )
    )

    def palette(value: float) -> float:
        return low + (high - low) * float(value)

    return palette


def abs_area_pal(max_size: float = 6.0) -> Callable[[float], float]:
    """上游 `abs_area(max_size)`：(0..1) → `max_size * sqrt(x)`（`scale_size_area`）。"""
    top = float(max_size)

    def palette(value: float) -> float:
        return top * math.sqrt(max(0.0, float(value)))

    return palette

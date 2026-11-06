"""grob 模型与场景遍历（SIL-594 / M0-6）。

`ggcore.grobs` 是 R `grid` grob 系统的 Python 对等物。计数只有一个口径
（`docs/notes/grobs.md` §1）：

- **grob 构造器 18 个** = 13 种可绘制原语（`rect` / `circle` / `lines` /
  `segments` / `polyline` / `polygon` / `path` / `points` / `text` / `raster` /
  `xspline` / `bezier` / `curve`）+ `clipPath` + `nullGrob` + `zeroGrob` +
  `gTree` + `gtable` 的 grob 视图；
- **IR 节点 18 种**（3 个容器 + 15 个叶子 kind，含 `null` / `zero`）；
- **`Scene.to_ir_scene()` 实际产出 14 种 kind**：13 种可绘制原语 + `viewport`。

三层结构，与 grid 一一对应：

1. **grob 规格**（本模块的 `*Grob` / `*_grob()`）：坐标是单位对象（M0-3），
   gpar 是增量（M0-4 的 `Gpar`），`vp` 是可选视口（M0-4 的 `Viewport`）。
2. **场景遍历**（:func:`scene`）：在 :class:`~ggcore.viewport.ViewportTree` 里
   深度优先走一遍，逐指令产出 :class:`Instruction`。到这一步，单位已换算、
   gpar 已解析、视口变换已累积成**一个**仿射、`clip` 已消解成页面坐标的矩形。
3. **IR**（:meth:`Scene.to_ir_scene`）：扁平指令重排成 `viewport` + 叶子的
   `ir.Scene`，float32 的舍入就在这里一次做完。
4. **设备**（M0-8）：只认 `ir.Scene`（不是本模块的 :class:`Scene`），不再做继承、
   查表或视口导航。

坐标口径（与 IR 一致，见 `docs/notes/ir.md`）：

- 每条指令的几何在**本视口坐标系**里，单位 pt、y 向下、原点在视口左上角；
- :attr:`Instruction.transform` 是这份局部坐标 → **页面坐标**（pt、y 向下、
  原点页面左上）的 2×3 仿射，已经乘完父视口链与 y 翻转；
- :attr:`Instruction.clip` 是**页面绝对坐标**的裁剪矩形（pt、y 向下），
  与 `viewport.ir_clip_rect()` 同一口径——设备在页面空间裁剪。

`NA` 与 `None` 在 gpar 里是两件事（`docs/notes/grobs.md` §2）：`None` 清空回
grid 缺省值，`NA` 是“透明 / 不画”；写 IR 时两者都折成“不描边 / 不填充”，
但 :attr:`Instruction.resolved` 保留解析后的原值，便于判定与对拍。

向量 gp 不扩 `Gpar`（字段只能标量）：grob 构造器接受 `gp={"col": […]}` 这种
**向量写法**，构造时按元素摊成逐元素增量，遍历时把**连续同值**的元素合成一个
IR 节点（R 的 `pointsGrob` 传向量 `col` → N 个点一个节点，见 §4）。
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

from ggcore import fills, ir
from ggcore.arrow import Arrow, arrow_node_params
from ggcore.gtable import GTable, gtable_height, gtable_width, is_gtable
from ggcore.ir import Blob, BlobTable, NodeKind
from ggcore.units import (
    BIGPOINTS_PER_INCH,
    Unit,
    UnitContext,
    UnitError,
    convert_unit,
    unit,
    unit_max,
)
from ggcore.viewport import (
    GPAR_FIELDS,
    NA,
    Affine,
    Clip,
    Device,
    Gpar,
    ResolvedGpar,
    RotatedClipWarning,
    Viewport,
    ViewportTree,
    VpNode,
    normalize_just,
    viewport,
)

__all__ = [
    "DEFAULT_FONT_KEY",
    "BezierGrob",
    "CircleGrob",
    "ClipPathGrob",
    "CurveGrob",
    "GTableGrob",
    "GTreeGrob",
    "Grob",
    "GrobError",
    "Instruction",
    "LinesGrob",
    "NullGrob",
    "PathGrob",
    "PointsGrob",
    "PolygonGrob",
    "PolylineGrob",
    "RasterGrob",
    "RectGrob",
    "Scene",
    "SegmentsGrob",
    "TextGrob",
    "XSplineGrob",
    "ZeroGrob",
    "bezier_grob",
    "circle_grob",
    "clip_path",
    "curve_grob",
    "g_table_grob",
    "g_tree",
    "height_details",
    "is_absolute_size",
    "lines_grob",
    "null_grob",
    "path_grob",
    "points_grob",
    "polygon_grob",
    "polyline_grob",
    "raster_grob",
    "rect_grob",
    "scene",
    "segments_grob",
    "text_grob",
    "width_details",
    "xspline_grob",
    "zero_grob",
]

#: 文本节点在 `gpar.fontfamily` 为空时用的字族 key（M0-7 的字体目录再细化）。
DEFAULT_FONT_KEY = "sans"

#: R 的 `lwd` 单位（1/96 inch）→ pt（1/72 inch）。`docs/notes/ir.md` §6 的口径是
#: pt，所以 `grobs → IR` 这一步必须换算；不换的话所有描边粗 4/3 倍
#: （`lwd = 6` @150 ppi：R 9.4 px / 10 px 墨，未换算 12.5 px）。
_LWD_UNITS_TO_PT = 72.0 / 96.0


class GrobError(ValueError):
    """grob 构造或遍历失败（单位、坐标长度、IR 表达不了的东西都在这里报）。"""


# ---------------------------------------------------------------------------
# 颜色：R 的 col2rgb 口径
# ---------------------------------------------------------------------------

#: R `colors()` 里常用的具名颜色（值就是 R `col2rgb()` 的输出）。
#:
#: 刻意不做全表：R 的 657 个名字里有大量编号变体（`green3`、`purple4`…），
#: 本项目按需要增补；不认识的名字直接报错，不猜。`grey<k>` / `gray<k>`
#: 由 :func:`_grey` 按 `round(255 * k / 100)` 生成（与 R 的颜色表可能差 1 个灰阶，
#: 见 `docs/notes/grobs.md` §5）。
_NAMED_COLOURS: Mapping[str, tuple[int, int, int]] = {
    "aliceblue": (240, 248, 255),
    "aquamarine": (127, 255, 212),
    "beige": (245, 245, 220),
    "black": (0, 0, 0),
    "blue": (0, 0, 255),
    "blueviolet": (138, 43, 226),
    "brown": (165, 42, 42),
    "burlywood": (222, 184, 135),
    "cadetblue": (95, 158, 160),
    "chartreuse": (127, 255, 0),
    "chocolate": (210, 105, 30),
    "coral": (255, 127, 80),
    "cornflowerblue": (100, 149, 237),
    "corn silk": (255, 248, 220),
    "cornsilk": (255, 248, 220),
    "crimson": (220, 20, 60),
    "cyan": (0, 255, 255),
    "darkblue": (0, 0, 139),
    "darkcyan": (0, 139, 139),
    "darkgoldenrod": (184, 134, 11),
    "darkgray": (169, 169, 169),
    "darkgreen": (0, 100, 0),
    "darkgrey": (169, 169, 169),
    "darkkhaki": (189, 183, 107),
    "darkmagenta": (139, 0, 139),
    "darkolivegreen": (85, 107, 47),
    "darkorange": (255, 140, 0),
    "darkorchid": (153, 50, 204),
    "darkred": (139, 0, 0),
    "darksalmon": (233, 150, 122),
    "darkseagreen": (143, 188, 143),
    "darkslateblue": (72, 61, 139),
    "darkslategray": (47, 79, 79),
    "darkslategrey": (47, 79, 79),
    "darkturquoise": (0, 206, 209),
    "darkviolet": (148, 0, 211),
    "deeppink": (255, 20, 147),
    "deepskyblue": (0, 191, 255),
    "dimgray": (105, 105, 105),
    "dimgrey": (105, 105, 105),
    "dodgerblue": (30, 144, 255),
    "firebrick": (178, 34, 34),
    "forestgreen": (34, 139, 34),
    "gold": (255, 215, 0),
    "goldenrod": (218, 165, 32),
    "gray": (128, 128, 128),
    "green": (0, 255, 0),
    "greenyellow": (173, 255, 47),
    "grey": (128, 128, 128),
    "hotpink": (255, 105, 180),
    "indianred": (205, 92, 92),
    "indigo": (75, 0, 130),
    "ivory": (255, 255, 240),
    "khaki": (240, 230, 140),
    "lavender": (230, 230, 250),
    "lawngreen": (124, 252, 0),
    "lightblue": (173, 216, 230),
    "lightcoral": (240, 128, 128),
    "lightcyan": (224, 255, 255),
    "lightgoldenrodyellow": (250, 250, 210),
    "lightgray": (211, 211, 211),
    "lightgreen": (144, 238, 144),
    "lightgrey": (211, 211, 211),
    "lightpink": (255, 182, 193),
    "lightsalmon": (255, 160, 122),
    "lightseagreen": (32, 178, 170),
    "lightskyblue": (135, 206, 250),
    "lightslategray": (119, 136, 153),
    "lightslategrey": (119, 136, 153),
    "lightsteelblue": (176, 196, 222),
    "lightyellow": (255, 255, 224),
    "limegreen": (50, 205, 50),
    "magenta": (255, 0, 255),
    "maroon": (176, 48, 96),
    "mediumblue": (0, 0, 205),
    "mediumorchid": (186, 85, 211),
    "mediumpurple": (147, 112, 219),
    "mediumseagreen": (60, 179, 113),
    "mediumslateblue": (123, 104, 238),
    "mediumspringgreen": (0, 250, 154),
    "mediumturquoise": (72, 209, 204),
    "mediumvioletred": (199, 21, 133),
    "midnightblue": (25, 25, 112),
    "navy": (0, 0, 128),
    "olive": (128, 128, 0),
    "olivedrab": (107, 142, 35),
    "orange": (255, 165, 0),
    "orangered": (255, 69, 0),
    "orchid": (218, 112, 214),
    "palegreen": (152, 251, 152),
    "paleturquoise": (175, 238, 238),
    "palevioletred": (219, 112, 147),
    "peru": (205, 133, 63),
    "pink": (255, 192, 203),
    "plum": (221, 160, 221),
    "powderblue": (176, 224, 230),
    "purple": (160, 32, 240),
    "red": (255, 0, 0),
    "rosybrown": (188, 143, 143),
    "royalblue": (65, 105, 225),
    "saddlebrown": (139, 69, 19),
    "salmon": (250, 128, 114),
    "sandybrown": (244, 164, 96),
    "seagreen": (46, 139, 87),
    "sienna": (160, 82, 45),
    "skyblue": (135, 206, 235),
    "slateblue": (106, 90, 205),
    "slategray": (112, 128, 144),
    "slategrey": (112, 128, 144),
    "springgreen": (0, 255, 127),
    "steelblue": (70, 130, 180),
    "tan": (210, 180, 140),
    "thistle": (216, 191, 216),
    "tomato": (255, 99, 71),
    "turquoise": (64, 224, 208),
    "violet": (238, 130, 238),
    "violetred": (208, 32, 144),
    "wheat": (245, 222, 179),
    "white": (255, 255, 255),
    "whitesmoke": (245, 245, 245),
    "yellow": (255, 255, 0),
    "yellowgreen": (154, 205, 50),
}


#: R 命名色表里的 `grey0` … `grey100`（X11 `rgb.txt` 的取值，不是公式）。
#: 它与 `round(255 * k / 100)` 在 `.5` 处会差 1 个灰阶（`grey50` = 127 而不是
#: 128、`grey30` = 77 而不是 76），所以整张表照抄，避免 `greyNN` 写进主题后
#: 与 `col2rgb()` 对不上。
_GREY_LEVELS: tuple[int, ...] = (
    0, 3, 5, 8, 10, 13, 15, 18, 20, 23, 26, 28, 31, 33, 36, 38, 41, 43, 46, 48,
    51, 54, 56, 59, 61, 64, 66, 69, 71, 74, 77, 79, 82, 84, 87, 89, 92, 94, 97,
    99, 102, 105, 107, 110, 112, 115, 117, 120, 122, 125, 127, 130, 133, 135,
    138, 140, 143, 145, 148, 150, 153, 156, 158, 161, 163, 166, 168, 171, 173,
    176, 179, 181, 184, 186, 189, 191, 194, 196, 199, 201, 204, 207, 209, 212,
    214, 217, 219, 222, 224, 227, 229, 232, 235, 237, 240, 242, 245, 247, 250,
    252, 255,
)  # fmt: skip


def _grey(name: str) -> tuple[int, int, int] | None:
    """R 的 `grey<k>` / `gray<k>`：整数 k（0..100）查 R 色表，小数按公式取整。"""
    for prefix in ("grey", "gray"):
        if name.startswith(prefix):
            digits = name[len(prefix) :]
            if not digits:
                return (128, 128, 128)
            try:
                percent = float(digits)
            except ValueError:
                return None
            if not 0.0 <= percent <= 100.0:
                return None
            if percent.is_integer():
                channel = _GREY_LEVELS[int(percent)]
            else:
                channel = round(255.0 * percent / 100.0)
            return (channel, channel, channel)
    return None


def parse_colour(value: Any) -> tuple[int, int, int, int]:
    """R `col2rgb(col, alpha = TRUE)`：颜色名 / `#RGB` / `#RRGGBB` / `#RRGGBBAA`。

    `NA` / `"transparent"` 不给这里处理——它们的语义是“不画”，由
    :func:`_paint` 折成 IR 的 `None`。通道值原样返回 0..255，不做 gamma。
    """
    if isinstance(value, str):
        text = value.strip()
        lowered = text.lower()
        if lowered.startswith("#"):
            digits = lowered[1:]
            if len(digits) == 3:
                red, green, blue = (int(digit * 2, 16) for digit in digits)
                return (red, green, blue, 255)
            if len(digits) == 6:
                red, green, blue = (int(digits[index : index + 2], 16) for index in (0, 2, 4))
                return (red, green, blue, 255)
            if len(digits) == 8:
                red, green, blue, alpha = (
                    int(digits[index : index + 2], 16) for index in (0, 2, 4, 6)
                )
                return (red, green, blue, alpha)
            raise GrobError(f"invalid colour: {value!r}")
        named = _NAMED_COLOURS.get(lowered) or _grey(lowered)
        if named is None:
            raise GrobError(
                f"unknown colour name {value!r}；用 #RRGGBB 或已收录的 R 颜色名"
                "（见 docs/notes/grobs.md §5）"
            )
        return (named[0], named[1], named[2], 255)
    if isinstance(value, (tuple, list)) and not isinstance(value, (str, bytes)):
        channels = list(value)
        if len(channels) == 3:
            channels.append(255)
        if len(channels) != 4:
            raise GrobError(f"invalid colour: {value!r}")
        out: list[int] = []
        for channel in channels:
            if isinstance(channel, bool) or not isinstance(channel, (int, float)):
                raise GrobError(f"invalid colour: {value!r}")
            number = float(channel)
            if not math.isfinite(number) or not 0.0 <= number <= 255.0:
                raise GrobError(f"invalid colour: {value!r}")
            out.append(round(number))
        return (out[0], out[1], out[2], out[3])
    raise GrobError(f"invalid colour: {value!r}")


def _paint(value: Any) -> tuple[int, int, int, int] | fills.FillSpec | None:
    """解析后的颜色 → IR 的 `col` / `fill`：`None` = 不画。

    渐变 / 图案的**待解析**规格（`ggcore.fills`，SIL-751）原样透传：坐标要等被
    填充对象的包围盒，到 :meth:`Instruction.to_node` 才折成 IR 的最终几何。
    """
    if isinstance(value, fills.FillSpec):
        return value
    if value is None or value is NA:
        return None
    if isinstance(value, str) and value.strip().lower() == "transparent":
        return None
    return parse_colour(value)


# R `lty` 的编号形式（段长单位是 lwd，与 R `par(lty=)` 一致）。
_LTY_PATTERNS: Mapping[str, tuple[float, ...]] = {
    "solid": (),
    "dashed": (4.0, 4.0),
    "dotted": (1.0, 3.0),
    "dotdash": (1.0, 3.0, 4.0, 3.0),
    "longdash": (7.0, 3.0),
    "twodash": (2.0, 2.0, 6.0, 2.0),
    "blank": (),
}
_LTY_CODES: Mapping[int, str] = {
    0: "blank",
    1: "solid",
    2: "dashed",
    3: "dotted",
    4: "dotdash",
    5: "longdash",
    6: "twodash",
}


def _dash_pattern(lty: Any) -> tuple[float, ...] | None:
    """`lty` → 段长（`lwd` 的倍数，`lwd < 1` 时按 1 算）；`None` 表示不描边。"""
    if lty is None or lty is NA:
        return None
    if isinstance(lty, bool):
        raise GrobError(f"invalid lty: {lty!r}")
    if isinstance(lty, int):
        name = _LTY_CODES.get(lty)
        if name is None:
            raise GrobError(f"invalid lty: {lty!r}")
        return None if name == "blank" else _LTY_PATTERNS[name]
    if isinstance(lty, str):
        key = lty.strip().lower()
        if key == "blank":
            return None
        if key in _LTY_PATTERNS:
            return _LTY_PATTERNS[key]
        digits = key.replace(" ", "")
        if digits and all(digit in "0123456789abcdefABCDEF" for digit in digits):
            pattern = tuple(float(int(digit, 16)) for digit in digits)
            return pattern
        raise GrobError(f"invalid lty: {lty!r}")
    if isinstance(lty, (tuple, list, np.ndarray)):
        pattern = tuple(float(value) for value in lty)
        if any(value < 0 for value in pattern):
            raise GrobError(f"invalid lty: {lty!r}")
        return pattern
    raise GrobError(f"invalid lty: {lty!r}")


_LINEENDS: Mapping[str, ir.LineEnd] = {
    "round": ir.LineEnd.ROUND,
    "butt": ir.LineEnd.BUTT,
    "square": ir.LineEnd.SQUARE,
}
_LINEJOINS: Mapping[str, ir.LineJoin] = {
    "round": ir.LineJoin.ROUND,
    "miter": ir.LineJoin.MITER,
    "mitre": ir.LineJoin.MITER,
    "bevel": ir.LineJoin.BEVEL,
}
#: R 的 `font` 整数 → 字重/字形后缀（`fontface` 字符串的 `validGP()` 结果）。
_FONT_FACES: Mapping[int, str] = {1: "", 2: "bold", 3: "italic", 4: "bold-italic", 5: "symbol"}


def _font_key(gp: ResolvedGpar) -> str:
    """已解析的字体 key：`fontfamily` + `font` 折成的字重/字形后缀。

    M0-7 会把它换成真实字体目录里的 key（受管字体、回退栈在那一层切 run）；
    这里只保证 IR 的 `font` 是**单个**已解析 key，不是回退栈。
    """
    family = gp.fontfamily or DEFAULT_FONT_KEY
    face = _FONT_FACES.get(int(gp.font), "")
    return f"{family}:{face}" if face else family


def _ir_gpar(gp: ResolvedGpar) -> ir.Gpar:
    """解析后的 gpar → IR gpar（颜色 8 位 RGBA、虚线折成 pt 段长）。"""
    dashes = _dash_pattern(gp.lty)
    col = None if dashes is None else _paint(gp.col)
    # R 的 `gpar$lwd` 单位是 1/96 inch，IR 是 pt(1/72 inch)：乘 72/96 = 0.75
    # （不换就是 4/3 倍粗）。`lty` 的段长是 lwd 的倍数，跟着一起换算。
    lwd = float(gp.lwd) * _LWD_UNITS_TO_PT
    pattern: tuple[float, ...] = ()
    if dashes is not None:
        # 段长 = 模式 × max(lwd, 1)：R 的 `lwd` 是 1/96 inch，参考产线（svglite）
        # 把小于 1 的 lwd 按 1 算段长（`lty = "dashed"` 在 lwd < 1 时恒为 4,4 pt），
        # 用 lwd 本身会在细线上把虚线画密（SIL-737 的 abline 用例）。
        # 再乘 72/96：上面算出来的是 lwd 单位（1/96 inch）的段长，IR 的 `lty` 是 pt，
        # 渲染器随即乘 `DASH_UNIT = 4/3` 换回 lwd 单位写进 `stroke-dasharray`
        # （`pattern × max(lwd, 1)`，与参考产线同口径；SIL-763 / SIL-765）。
        scale = max(float(gp.lwd), 1.0) * _LWD_UNITS_TO_PT
        pattern = tuple(round(segment * scale, 6) for segment in dashes)
    return ir.Gpar(
        fill=_paint(gp.fill),
        col=col,
        lwd=lwd,
        lty=pattern,
        lineend=_LINEENDS[gp.lineend],
        linejoin=_LINEJOINS[gp.linejoin],
        linemitre=float(gp.linemitre),
        alpha=float(gp.alpha),
    )


# ---------------------------------------------------------------------------
# 单位：构造期的参数规整
# ---------------------------------------------------------------------------


def _as_unit(name: str, value: Any, default_units: str) -> Unit:
    """坐标参数：`Unit` 原样、数字按 `default_units`、数字序列按模摊成单位向量。"""
    if isinstance(value, Unit):
        if len(value) == 0:
            raise GrobError(f"'{name}' must have length > 0")
        return value
    if isinstance(value, bool):
        raise GrobError(f"'{name}' must be a unit or a number")
    if isinstance(value, (int, float)):
        return unit(float(value), default_units)
    if isinstance(value, (list, tuple, np.ndarray)) and not isinstance(value, (str, bytes)):
        if isinstance(value, np.ndarray):
            # 大批量几何走这里：数值数组直接交给 `unit()`，不先摊成 10 万个 Python
            # 标量再 `float()` 一遍（`docs/notes/performance.md`）。
            if value.ndim == 1 and value.dtype.kind in "iuf":
                return unit(value.astype(np.float64, copy=False), default_units)
            values = list(value)
        else:
            values = list(value)
        if not values:
            raise GrobError(f"'{name}' must have length > 0")
        try:
            return unit([float(item) for item in values], default_units)
        except (TypeError, ValueError):
            raise GrobError(f"'{name}' must be a unit or a number") from None
    raise GrobError(f"'{name}' must be a unit or a number, got {type(value).__name__}")


def _unit_length(value: Unit) -> int:
    return len(value)


def _count(*lengths: int) -> int:
    count = max(lengths)
    if count <= 0:
        raise GrobError("grob needs at least one element")
    return count


def _recycle(values: np.ndarray, count: int) -> np.ndarray:
    """R 的按模回收（`np.resize` 就是同一个语义）。"""
    values = np.asarray(values, dtype=np.float64)
    if values.size == count:
        return values
    return np.resize(values, count)


def _as_float_vector(name: str, value: Any) -> np.ndarray:
    if isinstance(value, bool):
        raise GrobError(f"'{name}' must be numeric")
    if isinstance(value, (int, float)):
        return np.asarray([float(value)], dtype=np.float64)
    if isinstance(value, (list, tuple, np.ndarray)) and not isinstance(value, (str, bytes)):
        try:
            return np.asarray([float(item) for item in value], dtype=np.float64)
        except (TypeError, ValueError):
            raise GrobError(f"'{name}' must be numeric") from None
    raise GrobError(f"'{name}' must be numeric, got {type(value).__name__}")


def _as_ids(value: Any, count: int) -> np.ndarray | None:
    """grid 的 `id`：每个顶点一个分组号（数字或字符串都行，按出现顺序编号）。"""
    if value is None:
        return None
    if isinstance(value, (str, bytes)):
        items: list[Any] = [value]
    elif isinstance(value, (list, tuple, np.ndarray)):
        items = list(value)
    else:
        items = [value]
    if not items:
        return None
    labels: dict[Any, int] = {}
    codes = []
    for item in items:
        if isinstance(item, float) and item.is_integer():
            item = int(item)
        labels.setdefault(item, len(labels))
        codes.append(labels[item])
    return np.resize(np.asarray(codes, dtype=np.int64), count)


def _just(grob: Any) -> tuple[float, float]:
    return (float(grob.hjust), float(grob.vjust))


# ---------------------------------------------------------------------------
# 逐元素 gpar：`gp={"col": [...]}` 的向量写法
# ---------------------------------------------------------------------------


def _is_vector(value: Any, name: str) -> bool:
    if isinstance(value, (str, bytes)) or value is None or value is NA:
        return False
    if name == "lty":  # 数字序列是“虚线样式”，不是向量 gpar
        return False
    return isinstance(value, (list, tuple, np.ndarray))


def _is_constant(items: Sequence[Any] | np.ndarray) -> bool:
    """向量 gp 的一个字段是否**逐元素同值**（含 `NA` 这类哨兵对象的同一个实例）。

    同值时整条向量等价于一个标量增量，遍历期不必建 `count` 个 `Gpar`——10 万点
    散点图的默认配色（整列 "black"）就靠这一条，见 `docs/notes/performance.md`。
    """
    if isinstance(items, np.ndarray):
        if items.size <= 1:
            return True
        try:
            return bool(np.all(items == items.reshape(-1)[0]))
        except (TypeError, ValueError):  # pragma: no cover - object 数组里的怪值
            return False
    try:
        return len(set(items)) == 1
    except TypeError:  # 不可哈希（渐变规格之类）：退回逐元素比较
        pass
    if len(items) <= 1:
        return True
    first = items[0]
    for item in items[1:]:
        if item is first or item == first:
            continue
        if isinstance(first, float) and isinstance(item, float):
            if math.isnan(first) and math.isnan(item):
                continue
        return False
    return True


def _gpar_deltas(raw: Gpar | Mapping[str, Any] | None, count: int) -> tuple[Gpar, ...]:
    """`Gpar` / 映射（值可以是向量）→ 逐元素增量。

    长度按 R 的按模回收到 `count`；所有字段都是标量时返回长度为 1 的元组，
    遍历时不拆节点。
    """
    if raw is None:
        return ()
    if isinstance(raw, Gpar):
        return (raw,)
    if not isinstance(raw, Mapping):
        raise GrobError(f"gp must be a Gpar or a mapping, got {type(raw).__name__}")
    known = {name for name, _ in GPAR_FIELDS}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise GrobError(f"unknown gpar fields: {', '.join(unknown)}")

    vectors: dict[str, np.ndarray | tuple[Any, ...]] = {}
    scalars = dict(raw)
    for name, value in raw.items():
        if _is_vector(value, name):
            items = list(value) if not isinstance(value, np.ndarray) else value
            length = int(items.size) if isinstance(items, np.ndarray) else len(items)
            if not length:
                raise GrobError(f"gpar.{name} vector must have length > 0")
            if length not in (1, count) and count % length != 0:
                raise GrobError(
                    f"gpar.{name} has length {length}, which does not recycle to {count} elements"
                )
            if length == 1:
                scalars[name] = items[0] if not isinstance(items, np.ndarray) else items[0].item()
                continue
            if _is_constant(items):
                # 逐元素同值：整条向量等价于一个标量增量，不必建 count 个 `Gpar`
                # （10 万点散点图的默认配色就是这种形状，见 performance.md）。
                scalars[name] = items[0] if not isinstance(items, np.ndarray) else items[0].item()
                continue
            vectors[name] = tuple(items.tolist()) if isinstance(items, np.ndarray) else tuple(items)
    if not vectors:
        return (Gpar(**scalars),)
    raw = scalars
    deltas: list[Gpar] = []
    for index in range(count):
        fields: dict[str, Any] = {}
        for name, value in raw.items():
            items = vectors.get(name)
            fields[name] = value if items is None else items[index % len(items)]
        deltas.append(Gpar(**fields))
    return tuple(deltas)


def _groups(deltas: tuple[Gpar, ...], count: int) -> tuple[tuple[Gpar, slice], ...]:
    """把逐元素增量按**连续同值**分组（一组 gp 一个 IR 节点）。"""
    if len(deltas) <= 1:
        return ((deltas[0] if deltas else Gpar(), slice(0, count)),)
    groups: list[tuple[Gpar, slice]] = []
    start = 0
    for index in range(1, count):
        if deltas[index] != deltas[start]:
            groups.append((deltas[start], slice(start, index)))
            start = index
    groups.append((deltas[start], slice(start, count)))
    return tuple(groups)


# ---------------------------------------------------------------------------
# grob 类型
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class Grob:
    """所有 grob 的公共部分：名字、逐元素 gpar 增量、可选视口。

    `vp` 与 grid 的 `grob(..., vp=viewport(...))` 同义：绘制这个 grob 期间把它
    push 进来，画完 pop。`gps` 是**逐元素**的 gpar 增量（长度 1 = 全元素同值）。

    `layer_tag` 是「整层 grob」的标记（SIL-833）：R 的 `pattern()` / 渐变内容按
    **被填充 grob** 的包围盒折 npc——ggplot2 的 `Geom*$draw_panel()` 把一层的
    全部元素画成**一个** grob，所以一层里逐元素的图案共用同一个包围盒。遍历期
    把这个标记继承给所有后代指令，写 IR 时同标记的指令取并集当填充 bbox。
    空串 = 不是图层几何（背景、网格、图例各自是一个 grob，按自己的 bbox 折）。
    """

    name: str = ""
    gps: tuple[Gpar, ...] = ()
    vp: Viewport | None = None
    count: int = 1
    layer_tag: str = ""

    @property
    def gp(self) -> Gpar:
        """统一的那个增量（向量 gp 时取第一个元素，仅供口径检查）。"""
        return self.gps[0] if self.gps else Gpar()

    def __post_init__(self) -> None:
        if self.vp is not None and not isinstance(self.vp, Viewport):
            raise GrobError(f"vp must be a Viewport, got {type(self.vp).__name__}")
        if self.count < 1:
            raise GrobError("grob needs at least one element")
        if len(self.gps) not in (0, 1, self.count):
            raise GrobError(
                f"grob {self.name!r}: {len(self.gps)} gpar values for {self.count} elements"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class RectGrob(Grob):
    x: Unit = field(default_factory=lambda: unit(0.5, "npc"))
    y: Unit = field(default_factory=lambda: unit(0.5, "npc"))
    width: Unit = field(default_factory=lambda: unit(1.0, "npc"))
    height: Unit = field(default_factory=lambda: unit(1.0, "npc"))
    hjust: float = 0.5
    vjust: float = 0.5


@dataclass(frozen=True, slots=True, kw_only=True)
class CircleGrob(Grob):
    x: Unit = field(default_factory=lambda: unit(0.5, "npc"))
    y: Unit = field(default_factory=lambda: unit(0.5, "npc"))
    r: Unit = field(default_factory=lambda: unit(0.5, "npc"))
    #: 半径按哪一根轴换算：grid 的 `circleGrob(r = unit(., "npc"))` 取较小边，
    #: `geom_dotplot` 取「非堆叠轴」（R 的 `convertX` / `convertY`）。IR 的
    #: circle 存绝对 r（pt），换算是遍历期一次性的，所以这里记轴就好。
    r_axis: str = "x"


@dataclass(frozen=True, slots=True, kw_only=True)
class LinesGrob(Grob):
    x: Unit = field(default_factory=lambda: unit([0.0, 1.0], "npc"))
    y: Unit = field(default_factory=lambda: unit([0.0, 1.0], "npc"))


@dataclass(frozen=True, slots=True, kw_only=True)
class SegmentsGrob(Grob):
    x0: Unit = field(default_factory=lambda: unit(0.0, "npc"))
    y0: Unit = field(default_factory=lambda: unit(0.0, "npc"))
    x1: Unit = field(default_factory=lambda: unit(1.0, "npc"))
    y1: Unit = field(default_factory=lambda: unit(1.0, "npc"))
    arrow: Arrow | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class PolylineGrob(Grob):
    x: Unit = field(default_factory=lambda: unit([0.0, 1.0], "npc"))
    y: Unit = field(default_factory=lambda: unit([0.0, 1.0], "npc"))
    id: Any = None
    arrow: Arrow | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class PolygonGrob(Grob):
    x: Unit = field(default_factory=lambda: unit([0.0, 1.0, 0.5], "npc"))
    y: Unit = field(default_factory=lambda: unit([0.0, 0.0, 1.0], "npc"))
    id: Any = None


@dataclass(frozen=True, slots=True, kw_only=True)
class PathGrob(Grob):
    x: Unit = field(default_factory=lambda: unit([0.0, 1.0, 0.5], "npc"))
    y: Unit = field(default_factory=lambda: unit([0.0, 0.0, 1.0], "npc"))
    id: Any = None
    rule: str = "winding"


@dataclass(frozen=True, slots=True, kw_only=True)
class PointsGrob(Grob):
    x: Unit = field(default_factory=lambda: unit(0.5, "npc"))
    y: Unit = field(default_factory=lambda: unit(0.5, "npc"))
    pch: int = 1
    size: Unit = field(default_factory=lambda: unit(1.0, "char"))


@dataclass(frozen=True, slots=True, kw_only=True)
class TextGrob(Grob):
    label: tuple[str, ...] = ("",)
    x: Unit = field(default_factory=lambda: unit(0.5, "npc"))
    y: Unit = field(default_factory=lambda: unit(0.5, "npc"))
    hjust: float = 0.5
    vjust: float = 0.5
    rot: float = 0.0


@dataclass(frozen=True, slots=True, kw_only=True)
class RasterGrob(Grob):
    data: bytes = b""
    width_px: int = 1
    height_px: int = 1
    mime: str = "image/png"
    x: Unit = field(default_factory=lambda: unit(0.5, "npc"))
    y: Unit = field(default_factory=lambda: unit(0.5, "npc"))
    width: Unit = field(default_factory=lambda: unit(1.0, "npc"))
    height: Unit = field(default_factory=lambda: unit(1.0, "npc"))
    hjust: float = 0.5
    vjust: float = 0.5
    interpolate: bool = True


@dataclass(frozen=True, slots=True, kw_only=True)
class XSplineGrob(Grob):
    x: Unit = field(default_factory=lambda: unit([0.0, 1.0], "npc"))
    y: Unit = field(default_factory=lambda: unit([0.0, 1.0], "npc"))
    id: Any = None
    shape: float = 0.0
    open: bool = True


@dataclass(frozen=True, slots=True, kw_only=True)
class BezierGrob(Grob):
    x: Unit = field(default_factory=lambda: unit([0.0, 0.3, 0.7, 1.0], "npc"))
    y: Unit = field(default_factory=lambda: unit([0.0, 1.0, 1.0, 0.0], "npc"))


@dataclass(frozen=True, slots=True, kw_only=True)
class CurveGrob(Grob):
    x1: Unit = field(default_factory=lambda: unit(0.0, "npc"))
    y1: Unit = field(default_factory=lambda: unit(0.0, "npc"))
    x2: Unit = field(default_factory=lambda: unit(1.0, "npc"))
    y2: Unit = field(default_factory=lambda: unit(1.0, "npc"))
    curvature: float = 1.0
    angle: float = 90.0
    ncp: int = 1
    shape: float = 0.5
    square: bool = True
    inflect: bool = False
    open: bool = True
    arrow: Arrow | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class NullGrob(Grob):
    """`nullGrob()`：不画、不占位。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class ZeroGrob(Grob):
    """`zeroGrob()`：不画，但参与布局（宽高都是 0）。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class ClipPathGrob(Grob):
    """矩形裁剪容器（`clipPath` 的对等物）：子节点只在本矩形内绘制。"""

    children: tuple[Grob, ...] = ()
    x: Unit = field(default_factory=lambda: unit(0.0, "npc"))
    y: Unit = field(default_factory=lambda: unit(0.0, "npc"))
    width: Unit = field(default_factory=lambda: unit(1.0, "npc"))
    height: Unit = field(default_factory=lambda: unit(1.0, "npc"))
    hjust: float = 0.0
    vjust: float = 0.0

    def __post_init__(self) -> None:
        Grob.__post_init__(self)
        object.__setattr__(self, "children", tuple(_as_grob(child) for child in self.children))


@dataclass(frozen=True, slots=True, kw_only=True)
class GTableGrob(Grob):
    """把一张 :class:`~ggcore.gtable.GTable` 当 grob 画（gtable 的 `vp` 决策点）。

    gtable 自己只管几何；绘制期的视口栈在这里建：先在当前视口里解析行列尺寸，
    再为每条 layout 记录 push 一个单元格视口 `<name>.<t>-<r>-<b>-<l>`，
    其 `clip` 原样来自 `Placement.clip`——`"inherit"` 因此取父视口的裁剪框，
    **不是** `"off"`（`docs/notes/gtable.md`）。
    """

    table: GTable = field(default_factory=GTable)

    def __post_init__(self) -> None:
        Grob.__post_init__(self)
        if not is_gtable(self.table):
            raise GrobError(f"table must be a GTable, got {type(self.table).__name__}")


@dataclass(frozen=True, slots=True, kw_only=True)
class GTreeGrob(Grob):
    """`gTree()`：子节点 + `childrenvp` + gpar 继承。

    绘制顺序照 R `preDraw.gTree()`：先把 gTree 的 `gp` 设成临时 gpar，再
    `pushViewport(childrenvp)`，画完**先 pop 回 gTree 层、再恢复 gpar**——
    否则会造出“当前视口与 gpar 短暂不一致”的状态（`docs/notes/grobs.md` §3）。
    """

    children: tuple[Grob, ...] = ()
    children_vp: tuple[Viewport, ...] = ()

    def __post_init__(self) -> None:
        Grob.__post_init__(self)
        object.__setattr__(self, "children", tuple(_as_grob(child) for child in self.children))
        vps: list[Viewport] = []
        for item in self.children_vp:
            if isinstance(item, Viewport):
                vps.append(item)
            else:
                raise GrobError(f"childrenvp must be Viewport, got {type(item).__name__}")
        object.__setattr__(self, "children_vp", tuple(vps))
        if len(self.gps) > 1:  # pragma: no cover - 由构造器挡住，双保险
            raise GrobError("gTree 的 gp 必须是标量：容器没有逐元素语义")


GrobLike = Grob | GTable


def _as_grob(value: Any) -> Grob:
    """gtable 也是合法子节点（gtable 的 grob 是任意对象），在这里包成 grob。"""
    if is_gtable(value):
        return GTableGrob(table=value, name=value.name, count=1)
    if isinstance(value, Grob):
        return value
    raise GrobError(f"expected a grob or gtable, got {type(value).__name__}")


def _require_scalar_gp(grob: Grob) -> Gpar:
    if len(grob.gps) > 1:
        raise GrobError(
            f"grob {grob.name!r}: {type(grob).__name__} 只有逐元素 gp；容器/布局 grob 需要标量 gp"
        )
    return grob.gp


# ---------------------------------------------------------------------------
# 构造器（grid 的 *Grob() 对等物）
# ---------------------------------------------------------------------------


def _name(value: str | None, prefix: str) -> str:
    return prefix if value is None else str(value)


def _scalar_just(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GrobError(f"'{name}' must be a number, got {value!r}")
    return float(value)


def rect_grob(
    x: Any = 0.5,
    y: Any = 0.5,
    width: Any = 1.0,
    height: Any = 1.0,
    just: Any = "centre",
    hjust: Any = None,
    vjust: Any = None,
    default_units: str = "npc",
    name: str | None = None,
    gp: Gpar | Mapping[str, Any] | None = None,
    vp: Viewport | None = None,
) -> RectGrob:
    """`rectGrob()`：`just` 折成 hjust/vjust，显式 `hjust`/`vjust` 优先（同 grid）。"""
    hj, vj = normalize_just(just)
    x_unit = _as_unit("x", x, default_units)
    y_unit = _as_unit("y", y, default_units)
    width_unit = _as_unit("width", width, default_units)
    height_unit = _as_unit("height", height, default_units)
    count = _count(
        _unit_length(x_unit),
        _unit_length(y_unit),
        _unit_length(width_unit),
        _unit_length(height_unit),
    )
    return RectGrob(
        name=_name(name, "rect"),
        gps=_gpar_deltas(gp, count),
        vp=vp,
        count=count,
        x=x_unit,
        y=y_unit,
        width=width_unit,
        height=height_unit,
        hjust=hj if hjust is None else _scalar_just("hjust", hjust),
        vjust=vj if vjust is None else _scalar_just("vjust", vjust),
    )


def circle_grob(
    x: Any = 0.5,
    y: Any = 0.5,
    r: Any = 0.5,
    default_units: str = "npc",
    name: str | None = None,
    gp: Gpar | Mapping[str, Any] | None = None,
    vp: Viewport | None = None,
    *,
    r_axis: str = "x",
) -> CircleGrob:
    """`circleGrob()`：`r` 在视口单位下，椭圆交给视口变换（IR 不做 rx/ry）。

    `r_axis` 决定 `npc` / `native` 半径按哪根轴换算（grid 的圆半径默认取较小边；
    `geom_dotplot` 要按「非堆叠轴」，所以显式给）。绝对单位（mm/pt/inches）与
    轴无关。
    """
    if r_axis not in ("x", "y"):
        raise GrobError(f"'r_axis' must be 'x' or 'y', got {r_axis!r}")
    x_unit = _as_unit("x", x, default_units)
    y_unit = _as_unit("y", y, default_units)
    r_unit = _as_unit("r", r, default_units)
    count = _count(_unit_length(x_unit), _unit_length(y_unit), _unit_length(r_unit))
    return CircleGrob(
        name=_name(name, "circle"),
        gps=_gpar_deltas(gp, count),
        vp=vp,
        count=count,
        x=x_unit,
        y=y_unit,
        r=r_unit,
        r_axis=r_axis,
    )


def lines_grob(
    x: Any,
    y: Any,
    default_units: str = "npc",
    name: str | None = None,
    gp: Gpar | Mapping[str, Any] | None = None,
    vp: Viewport | None = None,
) -> LinesGrob:
    """`linesGrob()`：单条折线（连成一笔）。"""
    x_unit = _as_unit("x", x, default_units)
    y_unit = _as_unit("y", y, default_units)
    count = _count(_unit_length(x_unit), _unit_length(y_unit))
    return LinesGrob(
        name=_name(name, "lines"),
        gps=_gpar_deltas(gp, count),
        vp=vp,
        count=count,
        x=x_unit,
        y=y_unit,
    )


def segments_grob(
    x0: Any,
    y0: Any,
    x1: Any,
    y1: Any,
    default_units: str = "npc",
    name: str | None = None,
    gp: Gpar | Mapping[str, Any] | None = None,
    vp: Viewport | None = None,
    arrow: Arrow | None = None,
) -> SegmentsGrob:
    """`segmentsGrob()`：互不相连的线段，每行一条。"""
    x0_unit = _as_unit("x0", x0, default_units)
    y0_unit = _as_unit("y0", y0, default_units)
    x1_unit = _as_unit("x1", x1, default_units)
    y1_unit = _as_unit("y1", y1, default_units)
    count = _count(*(_unit_length(item) for item in (x0_unit, y0_unit, x1_unit, y1_unit)))
    return SegmentsGrob(
        name=_name(name, "segments"),
        gps=_gpar_deltas(gp, count),
        vp=vp,
        count=count,
        x0=x0_unit,
        y0=y0_unit,
        x1=x1_unit,
        y1=y1_unit,
        arrow=arrow,
    )


def polyline_grob(
    x: Any,
    y: Any,
    id: Any = None,
    default_units: str = "npc",
    name: str | None = None,
    gp: Gpar | Mapping[str, Any] | None = None,
    vp: Viewport | None = None,
    arrow: Arrow | None = None,
) -> PolylineGrob:
    """`polylineGrob()`：`id` 变化即切一条折线（grid 的 `id` 语义）。"""
    x_unit = _as_unit("x", x, default_units)
    y_unit = _as_unit("y", y, default_units)
    count = _count(_unit_length(x_unit), _unit_length(y_unit))
    return PolylineGrob(
        name=_name(name, "polyline"),
        gps=_gpar_deltas(gp, count),
        vp=vp,
        count=count,
        x=x_unit,
        y=y_unit,
        id=id,
        arrow=arrow,
    )


def polygon_grob(
    x: Any,
    y: Any,
    id: Any = None,
    default_units: str = "npc",
    name: str | None = None,
    gp: Gpar | Mapping[str, Any] | None = None,
    vp: Viewport | None = None,
) -> PolygonGrob:
    """`polygonGrob()`：填充走 `gpar.fill`，描边走 `gpar.col`。"""
    x_unit = _as_unit("x", x, default_units)
    y_unit = _as_unit("y", y, default_units)
    count = _count(_unit_length(x_unit), _unit_length(y_unit))
    return PolygonGrob(
        name=_name(name, "polygon"),
        gps=_gpar_deltas(gp, count),
        vp=vp,
        count=count,
        x=x_unit,
        y=y_unit,
        id=id,
    )


def path_grob(
    x: Any,
    y: Any,
    id: Any = None,
    rule: str = "winding",
    default_units: str = "npc",
    name: str | None = None,
    gp: Gpar | Mapping[str, Any] | None = None,
    vp: Viewport | None = None,
) -> PathGrob:
    """`pathGrob()`：多条子路径 + 填充规则（对应 SVG 的 `path`）。"""
    if rule not in ("winding", "evenodd"):
        raise GrobError(f"rule must be 'winding' or 'evenodd', got {rule!r}")
    x_unit = _as_unit("x", x, default_units)
    y_unit = _as_unit("y", y, default_units)
    count = _count(_unit_length(x_unit), _unit_length(y_unit))
    return PathGrob(
        name=_name(name, "path"),
        gps=_gpar_deltas(gp, count),
        vp=vp,
        count=count,
        x=x_unit,
        y=y_unit,
        id=id,
        rule=rule,
    )


def points_grob(
    x: Any,
    y: Any,
    pch: int = 1,
    size: Any = 1.0,
    size_units: str = "char",
    default_units: str = "npc",
    name: str | None = None,
    gp: Gpar | Mapping[str, Any] | None = None,
    vp: Viewport | None = None,
) -> PointsGrob:
    """`pointsGrob()`：`size` 是单位对象（grid 缺省 `unit(1, "char")`），落 IR 时折成 pt。"""
    if isinstance(pch, bool) or not isinstance(pch, int):
        raise GrobError(f"'pch' must be an integer, got {pch!r}")
    x_unit = _as_unit("x", x, default_units)
    y_unit = _as_unit("y", y, default_units)
    size_unit = _as_unit("size", size, size_units)
    count = _count(_unit_length(x_unit), _unit_length(y_unit))
    if _unit_length(size_unit) not in (1, count):
        raise GrobError("'size' must be length 1 or match the number of points")
    return PointsGrob(
        name=_name(name, "points"),
        gps=_gpar_deltas(gp, count),
        vp=vp,
        count=count,
        x=x_unit,
        y=y_unit,
        pch=pch,
        size=size_unit,
    )


def text_grob(
    label: str | Sequence[str],
    x: Any = 0.5,
    y: Any = 0.5,
    just: Any = "centre",
    hjust: Any = None,
    vjust: Any = None,
    rot: float = 0.0,
    default_units: str = "npc",
    name: str | None = None,
    gp: Gpar | Mapping[str, Any] | None = None,
    vp: Viewport | None = None,
) -> TextGrob:
    """`textGrob()`：`label` 长度决定元素数（`x`/`y` 按模回收）。"""
    labels = (label,) if isinstance(label, str) else tuple(str(item) for item in label)
    if isinstance(label, str) is False and not all(isinstance(item, str) for item in labels):
        raise GrobError("label must be a string or a sequence of strings")
    if not labels:
        raise GrobError("label must have length > 0")
    x_unit = _as_unit("x", x, default_units)
    y_unit = _as_unit("y", y, default_units)
    count = _count(len(labels), _unit_length(x_unit), _unit_length(y_unit))
    hj, vj = normalize_just(just)
    if isinstance(rot, bool) or not isinstance(rot, (int, float)):
        raise GrobError(f"'rot' must be a number, got {rot!r}")
    return TextGrob(
        name=_name(name, "text"),
        gps=_gpar_deltas(gp, count),
        vp=vp,
        count=count,
        label=labels,
        x=x_unit,
        y=y_unit,
        hjust=hj if hjust is None else _scalar_just("hjust", hjust),
        vjust=vj if vjust is None else _scalar_just("vjust", vjust),
        rot=float(rot),
    )


#: 1 pt = 1/72 inch = 2.54/72 cm（`math_text_grobs()` 的 pt → cm）。
_PT_PER_CM_INV = 2.54 / 72.0


def math_text_grobs(
    label: str,
    x: float,
    y: float,
    *,
    size: float,
    metrics: Any,
    family: str = "",
    hjust: float = 0.5,
    vjust: float = 0.5,
    rot: float = 0.0,
    gp: Gpar | Mapping[str, Any] | None = None,
    name: str = "math",
) -> list[Grob]:
    """一段 plotmath 标签 → 一组 text grob（每个 run 自己一个字号 / 基线）。

    坐标是**页面 cm、y 向上**（轴带与 strip 用的就是这套坐标），整块的锚点按
    `(hjust, vjust)` 折：宽度 = 各 run 推进之和，高度 = 基线以上 + 基线以下
    （`plotmath.layout()` 的 em 数 × 字号）。每段落字用 `hjust = 0 / vjust = 0`
    ——`vjust = 0` 在本仓的 IR 里就是「基线落在给定 y」，所以不同字号的 run 互不
    影响。根号一类的折线走 polyline。

    IR 没有「一段文字多段 run」的表达，这里刻意输出**多个 text 节点**（每个 run
    一个），不新增 IR 字段（见 `docs/notes/ir.md` 的 text 节点）。
    """
    from ggcore import plotmath

    measure = plotmath.measure_from(metrics, family)
    layout = plotmath.layout(str(label), fontsize=size, measure=measure)
    width_pt = layout.width_em * size
    height_pt = layout.height_em * size
    # 锚点 → 整块左边界 + 主行基线（cm，y 向上）。
    left = x - hjust * width_pt * _PT_PER_CM_INV
    baseline = y - vjust * height_pt * _PT_PER_CM_INV + layout.descent_em * size * _PT_PER_CM_INV
    radians = math.radians(rot % 360.0)
    cos = math.cos(radians)
    sin = math.sin(radians)

    def place(dx_pt: float, dy_pt: float) -> tuple[float, float]:
        """沿基线偏移 `dx`、垂直偏移 `dy`（pt，向上为正）→ 页面 cm。"""
        dx = dx_pt * _PT_PER_CM_INV
        dy = dy_pt * _PT_PER_CM_INV
        return left + dx * cos - dy * sin, baseline + dx * sin + dy * cos

    grobs: list[Grob] = []
    for index, run in enumerate(layout.runs):
        px, py = place(run.x_em * size, run.rise_em * size)
        grobs.append(
            text_grob(
                run.text,
                px,
                py,
                hjust=0.0,
                vjust=0.0,
                rot=rot,
                default_units="cm",
                gp=_gpar_with(gp, fontsize=size * run.cex),
                name=f"{name}.run{index}",
            )
        )
    for index, rule in enumerate(layout.rules):
        xs = [place(px_em * size, py_em * size)[0] for px_em, py_em in rule.points]
        ys = [place(px_em * size, py_em * size)[1] for px_em, py_em in rule.points]
        grobs.append(
            polyline_grob(
                xs,
                ys,
                default_units="cm",
                gp=_gpar_with(
                    gp,
                    lwd=rule.lwd,
                    lineend="round",
                    linejoin="round",
                    **({"col": "black"} if _gpar_get(gp, "col") is None else {}),
                ),
                name=f"{name}.radical{index}",
            )
        )
    return grobs


def _gpar_with(raw: Gpar | Mapping[str, Any] | None, **overrides: Any) -> Gpar | Mapping[str, Any]:
    """在 `Gpar` / 映射上加几个字段（`math_text_grobs()` 只覆盖字号 / 线宽）。"""
    if isinstance(raw, Gpar):
        return replace(raw, **overrides)
    return {**(raw or {}), **overrides}


def _gpar_get(raw: Gpar | Mapping[str, Any] | None, name: str) -> Any:
    if raw is None:
        return None
    if isinstance(raw, Gpar):
        return getattr(raw, name, None)
    return raw.get(name)


def raster_grob(
    data: bytes,
    width_px: int,
    height_px: int,
    mime: str = "image/png",
    x: Any = 0.5,
    y: Any = 0.5,
    width: Any = 1.0,
    height: Any = 1.0,
    just: Any = "centre",
    hjust: Any = None,
    vjust: Any = None,
    interpolate: bool = True,
    default_units: str = "npc",
    name: str | None = None,
    gp: Gpar | Mapping[str, Any] | None = None,
    vp: Viewport | None = None,
) -> RasterGrob:
    """`rasterGrob()`：像素在 blob 表里，节点只说贴到哪、多大、是否插值。"""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise GrobError(f"'data' must be bytes, got {type(data).__name__}")
    for label, value in (("width_px", width_px), ("height_px", height_px)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise GrobError(f"'{label}' must be an integer >= 1, got {value!r}")
    if not isinstance(interpolate, bool):
        raise GrobError("'interpolate' must be a boolean")
    hj, vj = normalize_just(just)
    return RasterGrob(
        name=_name(name, "raster"),
        gps=_gpar_deltas(gp, 1),
        vp=vp,
        count=1,
        data=bytes(data),
        width_px=width_px,
        height_px=height_px,
        mime=mime,
        x=_as_unit("x", x, default_units),
        y=_as_unit("y", y, default_units),
        width=_as_unit("width", width, default_units),
        height=_as_unit("height", height, default_units),
        hjust=hj if hjust is None else _scalar_just("hjust", hjust),
        vjust=vj if vjust is None else _scalar_just("vjust", vjust),
        interpolate=interpolate,
    )


def xspline_grob(
    x: Any,
    y: Any,
    id: Any = None,
    shape: float = 0.0,
    open: bool = True,
    default_units: str = "npc",
    name: str | None = None,
    gp: Gpar | Mapping[str, Any] | None = None,
    vp: Viewport | None = None,
) -> XSplineGrob:
    """`xsplineGrob()`：`shape` 落在 [-1, 1]，0 是 Catmull-Rom 样条。"""
    if isinstance(shape, bool) or not isinstance(shape, (int, float)):
        raise GrobError(f"'shape' must be a number, got {shape!r}")
    if not -1.0 <= float(shape) <= 1.0:
        raise GrobError(f"'shape' must be in [-1, 1], got {shape!r}")
    if not isinstance(open, bool):
        raise GrobError("'open' must be a boolean")
    x_unit = _as_unit("x", x, default_units)
    y_unit = _as_unit("y", y, default_units)
    count = _count(_unit_length(x_unit), _unit_length(y_unit))
    return XSplineGrob(
        name=_name(name, "xspline"),
        gps=_gpar_deltas(gp, count),
        vp=vp,
        count=count,
        x=x_unit,
        y=y_unit,
        id=id,
        shape=float(shape),
        open=open,
    )


def bezier_grob(
    x: Any,
    y: Any,
    default_units: str = "npc",
    name: str | None = None,
    gp: Gpar | Mapping[str, Any] | None = None,
    vp: Viewport | None = None,
) -> BezierGrob:
    """`bezierGrob()`：每 4 个控制点一段三次贝塞尔（同 grid）。"""
    x_unit = _as_unit("x", x, default_units)
    y_unit = _as_unit("y", y, default_units)
    count = _count(_unit_length(x_unit), _unit_length(y_unit))
    if count % 4:
        raise GrobError(f"bezier 需要 4 的倍数组控制点，收到 {count} 个")
    return BezierGrob(
        name=_name(name, "bezier"),
        gps=_gpar_deltas(gp, count),
        vp=vp,
        count=count,
        x=x_unit,
        y=y_unit,
    )


def curve_grob(
    x1: Any,
    y1: Any,
    x2: Any,
    y2: Any,
    curvature: float = 1.0,
    angle: float = 90.0,
    ncp: int = 1,
    shape: float = 0.5,
    square: bool = True,
    inflect: bool = False,
    open: bool = True,
    default_units: str = "npc",
    name: str | None = None,
    gp: Gpar | Mapping[str, Any] | None = None,
    vp: Viewport | None = None,
    arrow: Arrow | None = None,
) -> CurveGrob:
    """`curveGrob()`：两端点 + 弯曲参数，曲线形状由设备按同一公式复现。"""
    if isinstance(ncp, bool) or not isinstance(ncp, int) or ncp < 1:
        raise GrobError(f"'ncp' must be an integer >= 1, got {ncp!r}")
    x1_unit = _as_unit("x1", x1, default_units)
    y1_unit = _as_unit("y1", y1, default_units)
    x2_unit = _as_unit("x2", x2, default_units)
    y2_unit = _as_unit("y2", y2, default_units)
    count = _count(*(_unit_length(item) for item in (x1_unit, y1_unit, x2_unit, y2_unit)))
    if count > 1:
        raise GrobError("curve 的逐元素 gp 与多段曲线一起用尚未支持：一次只画一条曲线")
    return CurveGrob(
        name=_name(name, "curve"),
        gps=_gpar_deltas(gp, count),
        vp=vp,
        count=count,
        x1=x1_unit,
        y1=y1_unit,
        x2=x2_unit,
        y2=y2_unit,
        curvature=float(curvature),
        angle=float(angle),
        ncp=ncp,
        shape=float(shape),
        square=bool(square),
        inflect=bool(inflect),
        open=bool(open),
        arrow=arrow,
    )


def null_grob(
    name: str | None = None,
    gp: Gpar | Mapping[str, Any] | None = None,
    vp: Viewport | None = None,
) -> NullGrob:
    """`nullGrob()`：不画、不占位。"""
    return NullGrob(name=_name(name, "null"), gps=_gpar_deltas(gp, 1), vp=vp, count=1)


def zero_grob(
    name: str | None = None,
    gp: Gpar | Mapping[str, Any] | None = None,
    vp: Viewport | None = None,
) -> ZeroGrob:
    """`zeroGrob()`：不画，但参与布局（宽高 0）。"""
    return ZeroGrob(name=_name(name, "zero"), gps=_gpar_deltas(gp, 1), vp=vp, count=1)


def clip_path(
    *children: GrobLike,
    x: Any = 0.0,
    y: Any = 0.0,
    width: Any = 1.0,
    height: Any = 1.0,
    just: Any = ("left", "bottom"),
    hjust: Any = None,
    vjust: Any = None,
    default_units: str = "npc",
    name: str | None = None,
    gp: Gpar | Mapping[str, Any] | None = None,
    vp: Viewport | None = None,
) -> ClipPathGrob:
    """`clipPath` 的对等物：子节点只在本矩形内绘制。

    IR 的 `clip` 节点还能表达多边形裁剪；扁平指令的 `clip` 只能是页面里的轴对齐
    矩形，所以这一层先只做矩形裁剪（见 `docs/notes/grobs.md` §6）。
    """
    hj, vj = normalize_just(just)
    return ClipPathGrob(
        name=_name(name, "clip"),
        gps=_gpar_deltas(gp, 1),
        vp=vp,
        count=1,
        children=tuple(children),
        x=_as_unit("x", x, default_units),
        y=_as_unit("y", y, default_units),
        width=_as_unit("width", width, default_units),
        height=_as_unit("height", height, default_units),
        hjust=hj if hjust is None else _scalar_just("hjust", hjust),
        vjust=vj if vjust is None else _scalar_just("vjust", vjust),
    )


def g_tree(
    *children: GrobLike,
    childrenvp: Viewport | Sequence[Viewport] | None = None,
    name: str | None = None,
    gp: Gpar | Mapping[str, Any] | None = None,
    vp: Viewport | None = None,
) -> GTreeGrob:
    """`gTree(children = gList(...), childrenvp = ...)`。

    `childrenvp` 在 gTree 的临时 gpar 下 push，所以子视口里 `lines` / `char`
    这类单位按**gTree 的 gp** 换算（R `preDraw.gTree()` 的顺序）。
    """
    if childrenvp is None:
        vps: tuple[Viewport, ...] = ()
    elif isinstance(childrenvp, Viewport):
        vps = (childrenvp,)
    else:
        vps = tuple(childrenvp)
    return GTreeGrob(
        name=_name(name, "gTree"),
        gps=_gpar_deltas(gp, 1),
        vp=vp,
        count=1,
        children=tuple(children),
        children_vp=vps,
    )


def g_table_grob(
    table: GTable,
    *,
    name: str | None = None,
    gp: Gpar | Mapping[str, Any] | None = None,
    vp: Viewport | None = None,
) -> GTableGrob:
    """把 gtable 当 grob 用（绘制期建单元格视口，`clip="inherit"` 在这里消解）。"""
    if not is_gtable(table):
        raise GrobError(f"table must be a GTable, got {type(table).__name__}")
    return GTableGrob(
        name=_name(name, table.name),
        gps=_gpar_deltas(gp, 1),
        vp=vp,
        count=1,
        table=table,
    )


# ---------------------------------------------------------------------------
# 局部坐标换算
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Frame:
    """一个视口里的换算助手：局部 pt（y 向下）+ 页面仿射。

    `gpar` 是**当前生效**的 gpar（含 gTree 的临时 gp 与本 grob 的 gp），
    `lines` / `char` / `strwidth` 这些单位按它换算——与 R 在 `drawDetails()`
    里看到的是同一个 `gc`（`docs/notes/grobs.md` §3）。不传时退回视口自己的。
    """

    node: VpNode
    gpar: ResolvedGpar | None = None

    @property
    def height_pt(self) -> float:
        return self.node.height_in * BIGPOINTS_PER_INCH

    @property
    def ctx(self) -> UnitContext:
        base = self.node.unit_context()
        if self.gpar is None:
            return base
        return replace(
            base,
            fontsize=float(self.gpar.fontsize),
            cex=float(self.gpar.cex),
            lineheight=float(self.gpar.lineheight),
        )

    def loc(self, value: Unit, axis: str) -> np.ndarray:
        """位置单位 → 局部 pt（y 向上的那段，调用方自己翻转 y）。"""
        try:
            return np.asarray(
                convert_unit(value, "bigpts", ctx=self.ctx, axis_from=axis, type_from="location"),
                dtype=np.float64,
            )
        except UnitError as exc:
            raise GrobError(str(exc)) from exc

    def dim(self, value: Unit, axis: str) -> np.ndarray:
        """尺寸单位 → 局部 pt。"""
        try:
            return np.asarray(
                convert_unit(value, "bigpts", ctx=self.ctx, axis_from=axis, type_from="dimension"),
                dtype=np.float64,
            )
        except UnitError as exc:
            raise GrobError(str(exc)) from exc

    def flip(self, y_pt: np.ndarray) -> np.ndarray:
        """y 向上（局部 pt）→ y 向下（IR 口径）。"""
        return self.height_pt - np.asarray(y_pt, dtype=np.float64)

    def xy(self, x: Unit, y: Unit, count: int | None = None) -> np.ndarray:
        """位置向量 → `(n, 2)` 局部 pt、y 向下。"""
        xs = self.loc(x, "x")
        ys = self.loc(y, "y")
        n = max(xs.size, ys.size) if count is None else count
        return np.column_stack([_recycle(xs, n), self.flip(_recycle(ys, n))])

    def page(self) -> Affine:
        """局部 pt（y 向下）→ 页面 pt（y 向下、原点页面左上）。"""
        local = Affine(
            a=1.0 / BIGPOINTS_PER_INCH, d=-1.0 / BIGPOINTS_PER_INCH, f=self.node.height_in
        )
        height_pt = self.node.device.height_in * BIGPOINTS_PER_INCH
        page = Affine(a=BIGPOINTS_PER_INCH, d=-BIGPOINTS_PER_INCH, f=height_pt)
        return local.then(self.node.transform).then(page)


def _rect_buf(
    x: np.ndarray, y: np.ndarray, w: np.ndarray, h: np.ndarray, hjust: float, vjust: float
) -> np.ndarray:
    """左下角 + 宽高 + just → `(n, 4)` 的 `(x0, y0, x1, y1)`（y 向下，已排序）。"""
    x0 = x - w * hjust
    x1 = x + w * (1.0 - hjust)
    # y 是 y 向下的位置；vjust=0 表示“y 是下边”，在 y 向下坐标里靠下（数值更大）。
    top = y - h * (1.0 - vjust)
    bottom = y + h * vjust
    return np.column_stack(
        [np.minimum(x0, x1), np.minimum(top, bottom), np.maximum(x0, x1), np.maximum(top, bottom)]
    )


def _intersect(
    left: tuple[float, float, float, float], right: tuple[float, float, float, float]
) -> tuple[float, float, float, float]:
    """两个页面矩形求交；空交集收成一个退化矩形（设备会裁掉一切）。"""
    x0 = max(left[0], right[0])
    y0 = max(left[1], right[1])
    x1 = min(left[2], right[2])
    y1 = min(left[3], right[3])
    if x0 > x1:
        x0 = x1 = (left[0] + left[2]) / 2.0
    if y0 > y1:
        y0 = y1 = (left[1] + left[3]) / 2.0
    return (x0, y0, x1, y1)


# ---------------------------------------------------------------------------
# 指令与场景
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Instruction:
    """一条扁平绘制指令（Device 只认这个）。

    - `bufs` 是局部坐标（本视口 pt、y 向下）的 float64 缓冲，行数与 `resolved` 的
      元素数一致；
    - `transform` 把它映射到页面坐标（pt、y 向下）；
    - `clip` 是页面绝对坐标的裁剪矩形（已把视口 clip 与 grob 级裁剪合起来）。
      **必填**：没有“空 / 未设置”这一态，零面积就是真的裁掉一切，设备不需要
      猜“这是 inherit 还是不裁”（SIL-634 收口掉的 `(0, 0, 0, 0)` 占位）；
    - `resolved` 保留解析后的 gpar（`NA` 与 `None` 的区别在这里还看得见），
      `gpar` 是折好的 IR gpar。

    `bufs` 是 float64（遍历期的几何精度），写 IR 时才一次性舍入到 float32
    （:meth:`to_node`）。设备只吃 `ir.Scene`，所以不存在第二份 float64 几何——
    见 `docs/notes/grobs.md` §7。
    """

    kind: NodeKind
    gpar: ir.Gpar
    resolved: ResolvedGpar
    clip: tuple[float, float, float, float]
    params: Mapping[str, Any] = field(default_factory=dict)
    bufs: Mapping[str, np.ndarray] = field(default_factory=dict)
    texts: tuple[str, ...] = ()
    transform: tuple[float, float, float, float, float, float] = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    vp: str = ""
    source: str = ""
    #: 所属图层的标记（`Grob.layer_tag` 的继承值）；空串 = 不在图层 grob 里。
    layer: str = ""

    @property
    def rows(self) -> int:
        for value in self.bufs.values():
            return int(value.shape[0])
        return len(self.texts)

    def to_node(self, *, fill_box: tuple[float, float, float, float] | None = None) -> ir.Node:
        """写成 IR 节点（float32 / int32 的唯一一次舍入在这里发生）。

        `fill_box` 是填充规格（渐变 / 图案）的解析包围盒（节点局部坐标）。
        缺省用本节点自己的几何（:func:`ggcore.fills.node_bbox`）；图层里逐元素
        的填充（`pattern-fills-*`）由 :meth:`Scene.to_ir_scene` 传**整层**的并集
        包围盒——R 的 `pattern()` 内容按整层 grob 的 bbox 折 npc（SIL-833）。
        """
        bufs: dict[str, Any] = {}
        for name, value in self.bufs.items():
            bufs[name] = ir.i32(value) if name == "id" else ir.f32(value)
        gpar = self.gpar
        if isinstance(gpar.fill, fills.FillSpec):
            # npc 口径要等几何定下来才能折成局部坐标（`ggcore.fills` 模块头）。
            bbox = (
                fill_box
                if fill_box is not None
                else fills.node_bbox(self.kind, self.bufs, self.params)
            )
            if bbox is None:
                raise GrobError(f"{self.kind} 没有可以量包围盒的几何，渐变 / 图案无从解析")
            gpar = replace(gpar, fill=gpar.fill.resolve(bbox))
        return ir.Node(
            kind=self.kind,
            gpar=gpar,
            params=dict(self.params),
            bufs=bufs,
            texts=self.texts,
        )


def _layer_boxes(
    instructions: Sequence[Instruction],
) -> dict[tuple[str, str], tuple[float, float, float, float]]:
    """按图层（+ 局部坐标系）求几何并集包围盒（SIL-833）。

    R 的 `pattern()` 内容与渐变的 npc 端点都按**被填充 grob** 的 bbox 折；ggplot2
    的 `Geom*$draw_panel()` 把一层的全部元素画成**一个** grob，所以一层只有一份
    bbox。IR 里一层可能拆成多条指令（逐元素 gpar、极坐标的逐柱多边形），这里按
    `layer_tag` + 视口路径取并集，逐条指令再各自用自己的 bbox 就会相位错位。

    并集统计的是**整个图层**的几何（不含 `group = FALSE` 的渐变：R 的
    `linearGradient(group = FALSE)` 每个元素各用各的 bbox，`pattern-fills-*`
    的形状）。先挑出「有 group 填充规格」的图层，其余图层不量包围盒——给一条
    几万点的 path 量包围盒是白花时间。键里带视口路径：一层的指令若被拆到不同
    局部坐标系，坐标不可比，只能各算各的。
    """
    wanted = {
        (item.layer, item.vp)
        for item in instructions
        if item.layer
        and isinstance(item.gpar.fill, fills.FillSpec)
        and getattr(item.gpar.fill, "group", True)
    }
    if not wanted:
        return {}
    boxes: dict[tuple[str, str], list[float]] = {}
    for item in instructions:
        key = (item.layer, item.vp)
        if key not in wanted:
            continue
        bbox = fills.node_bbox(item.kind, item.bufs, item.params)
        if bbox is None:
            continue
        current = boxes.get(key)
        if current is None:
            boxes[key] = list(bbox)
            continue
        current[0] = min(current[0], bbox[0])
        current[1] = min(current[1], bbox[1])
        current[2] = max(current[2], bbox[2])
        current[3] = max(current[3], bbox[3])
    return {key: (box[0], box[1], box[2], box[3]) for key, box in boxes.items()}


@dataclass(frozen=True, slots=True)
class Scene:
    """遍历结果：设备 + 扁平指令序列 + blob 表。

    **不是设备输入**：设备吃的是 :meth:`to_ir_scene` 产出的 `ir.Scene`。这里是
    遍历期的 float64 中间形态，写 IR 时一次舍入到 float32（`docs/notes/grobs.md` §7）。
    """

    device: Device
    instructions: tuple[Instruction, ...] = ()
    blobs: BlobTable = field(default_factory=BlobTable.empty)

    @property
    def size_pt(self) -> tuple[float, float]:
        return (
            self.device.width_in * BIGPOINTS_PER_INCH,
            self.device.height_in * BIGPOINTS_PER_INCH,
        )

    def by_kind(self, kind: NodeKind | str) -> tuple[Instruction, ...]:
        wanted = NodeKind(kind)
        return tuple(item for item in self.instructions if item.kind is wanted)

    def to_ir_scene(self) -> ir.Scene:
        """扁平指令 → IR `Scene`（viewtransform 已累积，每条指令一个 `viewport`）。

        连续且**变换、裁剪与视口名都相同**的指令合进同一个 `viewport`，`gtree` 不用：
        扁平序列已经是绘制顺序。IR 的 `viewport.clip_rect` 是页面坐标，正好是
        :attr:`Instruction.clip`（`docs/notes/ir.md` §4）。视口名取
        :attr:`Instruction.vp`（视口路径）的**最深一段**——`panel-1-1` /
        `guide-0-key-0` 这类名字是浏览器查看器唯一的分组依据（M1-13），
        名字本身不带几何，不影响画出来的东西。
        """
        width, height = self.size_pt
        page = (0.0, 0.0, width, height)
        boxes = _layer_boxes(self.instructions)
        groups: list[tuple[tuple[float, ...], tuple[float, ...], str, list[ir.Node]]] = []
        for item in self.instructions:
            # `VpPath` 用 `::` 分段，最后一截就是最深视口自己的名字。
            name = item.vp.rsplit("::", 1)[-1] if item.vp else ""
            key = (item.transform, item.clip, name)
            fill = item.gpar.fill
            grouped = isinstance(fill, fills.FillSpec) and getattr(fill, "group", True)
            node = item.to_node(
                fill_box=boxes.get((item.layer, item.vp)) if item.layer and grouped else None
            )
            if groups and groups[-1][:3] == key:
                groups[-1][3].append(node)
            else:
                groups.append((key[0], key[1], key[2], [node]))
        children = tuple(
            ir.Node(
                NodeKind.VIEWPORT,
                params={"name": name, "clip": True, "transform": transform},
                bufs={"clip_rect": ir.f32([list(clip)])},
                children=tuple(nodes),
            )
            for transform, clip, name, nodes in groups
        )
        root = ir.Node(
            NodeKind.VIEWPORT,
            params={"name": "page", "clip": True, "transform": (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)},
            bufs={"clip_rect": ir.f32([list(page)])},
            children=children,
        )
        return ir.Scene(root=root, size=(width, height), dpi=72.0, blobs=self.blobs)


# ---------------------------------------------------------------------------
# 遍历
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Resolved:
    """一种原语解出来的几何（未切片）：一个 IR 节点的全部字段。"""

    kind: NodeKind
    bufs: dict[str, np.ndarray]
    params: Callable[[ResolvedGpar], dict[str, Any]]
    texts: tuple[str, ...] = ()
    split: bool = True


class _Traverser:
    """深度优先遍历 grob 树，产出扁平指令（场景遍历）。"""

    def __init__(self, tree: ViewportTree, cache: Any = None) -> None:
        self.tree = tree
        self.out: list[Instruction] = []
        self.blobs: dict[str, Blob] = {}
        self._extra_clip: tuple[float, float, float, float] | None = None
        #: 当前所在的图层标记（`Grob.layer_tag`，SIL-833）：整层一个 bbox。
        self._layer = ""
        #: 指令缓存（`ggcore.perf.SceneInstructionCache`）：键是内容不是对象 id。
        self.cache = cache

    # -- 坐标 ---------------------------------------------------------------

    def _frame(self) -> _Frame:
        return _Frame(self.tree.current, self.tree.gpar)

    def _clip(self) -> tuple[float, float, float, float]:
        """当前生效的页面裁剪框：视口自己的 + grob 级裁剪的交集。"""
        rect = self.tree.current.ir_clip_rect()
        if self._extra_clip is not None:
            rect = _intersect(rect, self._extra_clip)
        return rect

    # -- 遍历 ---------------------------------------------------------------

    def visit(self, grob: GrobLike) -> None:
        item = _as_grob(grob)
        if isinstance(item, (NullGrob, ZeroGrob)):
            return  # 不产出绘制指令（zeroGrob 只在布局里有存在感）
        pushed = 0
        if item.vp is not None:
            self.tree.push(item.vp)
            pushed = 1
        saved_layer = self._layer
        if item.layer_tag:
            self._layer = item.layer_tag
        try:
            if isinstance(item, GTreeGrob):
                self._visit_tree(item)
            elif isinstance(item, ClipPathGrob):
                self._visit_clip(item)
            elif isinstance(item, GTableGrob):
                self._visit_table(item)
            else:
                self._visit_leaf(item)
        finally:
            self._layer = saved_layer
            if pushed:
                self.tree.pop(pushed)

    def _visit_tree(self, tree_grob: GTreeGrob) -> None:
        gp = _require_scalar_gp(tree_grob)
        with self.tree.temporary_gpar(gp):
            pushed = 0
            if tree_grob.children_vp:
                self.tree.push(*tree_grob.children_vp)
                pushed = len(tree_grob.children_vp)
            try:
                for child in tree_grob.children:
                    self.visit(child)
            finally:
                # R `preDraw.gTree()` 的顺序：先退回 gTree 层，再恢复 gpar。
                if pushed:
                    self.tree.pop(pushed)

    def _visit_clip(self, clip_grob: ClipPathGrob) -> None:
        gp = _require_scalar_gp(clip_grob)
        with self.tree.temporary_gpar(gp):
            frame = self._frame()
            count = clip_grob.count
            rect = self._local_rect(
                clip_grob.x,
                clip_grob.y,
                clip_grob.width,
                clip_grob.height,
                clip_grob.hjust,
                clip_grob.vjust,
                count,
                frame,
            )
            page = self._rect_to_page(rect, frame)
            saved = self._extra_clip
            self._extra_clip = page if saved is None else _intersect(saved, page)
            try:
                for child in clip_grob.children:
                    self.visit(child)
            finally:
                self._extra_clip = saved

    def _visit_table(self, table_grob: GTableGrob) -> None:
        gp = _require_scalar_gp(table_grob)
        with self.tree.temporary_gpar(gp):
            node = self.tree.current
            table = table_grob.table
            # 单元格尺寸用**当前生效**的 gpar 换算（`lines`/`char` 宽度要它），
            # 与 R 在 drawDetails 里看到的是同一份 gc。
            ctx = self._frame().ctx
            sizes = table.resolve(node.width_cm, node.height_cm, ctx=ctx)
            spec = table.layout_spec()
            for index in table.drawing_order():
                row = table.layout[index]
                box = spec.region_box(
                    row.t,
                    row.l,
                    row.b,
                    row.r,
                    width_cm=node.width_cm,
                    height_cm=node.height_cm,
                    sizes=sizes,
                )
                cell = viewport(
                    f"{row.name}.{row.t}-{row.r}-{row.b}-{row.l}",
                    x=unit(box.x_cm, "cm"),
                    y=unit(box.y_cm, "cm"),
                    width=unit(box.width_cm, "cm"),
                    height=unit(box.height_cm, "cm"),
                    just=("left", "bottom"),
                    # "inherit" 到这里才变成“取父视口的裁剪框”，不是 off。
                    clip=Clip(row.clip),
                )
                self.tree.push(cell)
                try:
                    self.visit(table.grobs[index])
                finally:
                    self.tree.pop(1)

    def _visit_leaf(self, grob: Grob) -> None:
        deltas = grob.gps or (Gpar(),)
        cache_key = self._instruction_key(grob)
        if cache_key is not None and self.cache is not None:
            cached = self.cache.get(cache_key, self.tree.metrics)
            if cached is not None:
                self.out.extend(cached)
                return
        start = len(self.out)
        resolved_cache: dict[tuple[float, float, float, str, int], _Resolved] = {}
        for delta, index in _groups(deltas, grob.count):
            with self.tree.temporary_gpar(delta):
                gpar = self.tree.gpar
                # 字体 key 也要进缓存键：同一个 leaf 的向量 gp 可以切粗体/斜体，
                # 只按字号缓存会把第一档的字面复用到后面的档上。
                key = (
                    float(gpar.fontsize),
                    float(gpar.cex),
                    float(gpar.lineheight),
                    gpar.fontfamily,
                    int(gpar.font),
                )
                resolved = resolved_cache.get(key)
                if resolved is None:
                    resolved = self._resolve(grob)
                    resolved_cache[key] = resolved
                if not resolved.split and len(deltas) > 1:
                    raise GrobError(
                        f"grob {grob.name!r}: {type(grob).__name__} 的向量 gp 表达不了——"
                        "路径型原语只能整条一个节点（IR 的 id 分组不切 gp）"
                    )
                bufs = {
                    name: np.ascontiguousarray(value[index])
                    for name, value in resolved.bufs.items()
                }
                texts = resolved.texts[index] if resolved.texts else ()
                self.out.append(
                    Instruction(
                        kind=resolved.kind,
                        gpar=_ir_gpar(gpar),
                        resolved=gpar,
                        params=resolved.params(gpar),
                        bufs=bufs,
                        texts=texts,
                        transform=self._frame().page().as_tuple(),
                        clip=self._clip(),
                        vp=str(self.tree.current.path),
                        source=grob.name,
                        layer=self._layer,
                    )
                )
        if cache_key is not None and self.cache is not None:
            self.cache.put(cache_key, tuple(self.out[start:]), self.tree.metrics)

    # -- 增量重算的键 -------------------------------------------------------

    def _instruction_key(self, grob: Grob) -> tuple[Any, ...] | None:
        """一条叶子的指令缓存键；这条叶子不适合缓存时返回 `None`。

        键是**内容**：grob 指纹 + 视口路径 + 页面仿射 + 裁剪框 + 生效 gpar。
        同样的内容必然产出同样的指令（`_resolve_*` 是纯函数），所以命中可以直接
        复用。下面几类刻意不进缓存：

        - `RasterGrob`：解析时往 blob 表里登记图片，命中会漏掉登记；
        - 逐元素 gpar（`len(grob.gps) > 64`）：给每个元素建 Gpar 本来就比缓存贵；
        - 缓存被关掉 / 没有缓存实例（见 `ggcore.perf`）。
        """
        if self.cache is None or isinstance(grob, RasterGrob):
            return None
        if len(grob.gps) > 64:
            return None
        from ggcore.perf import fingerprint

        return (
            fingerprint(grob),
            str(self.tree.current.path),
            self._frame().page().as_tuple(),
            self._clip(),
            repr(self.tree.gpar),
        )

    # -- 几何 ---------------------------------------------------------------

    def _local_rect(
        self,
        x: Unit,
        y: Unit,
        width: Unit,
        height: Unit,
        hjust: float,
        vjust: float,
        count: int,
        frame: _Frame,
    ) -> np.ndarray:
        xs = _recycle(frame.loc(x, "x"), count)
        ys = _recycle(frame.flip(frame.loc(y, "y")), count)
        ws = _recycle(frame.dim(width, "x"), count)
        hs = _recycle(frame.dim(height, "y"), count)
        return _rect_buf(xs, ys, ws, hs, hjust, vjust)

    def _rect_to_page(self, rect: np.ndarray, frame: _Frame) -> tuple[float, float, float, float]:
        """局部矩形 → 页面矩形（取变换后的外包框；旋转时按 bbox 退化）。"""
        page = frame.page()
        corners = np.array(
            [
                page.map(rect[0, 0], rect[0, 1]),
                page.map(rect[0, 2], rect[0, 1]),
                page.map(rect[0, 2], rect[0, 3]),
                page.map(rect[0, 0], rect[0, 3]),
            ]
        )
        if abs(page.b) > 1e-9 or abs(page.c) > 1e-9:
            warnings.warn(
                "clip rect on a rotated viewport degrades to its bounding box",
                RotatedClipWarning,
                stacklevel=2,
            )
        x0, y0 = corners[:, 0].min(), corners[:, 1].min()
        x1, y1 = corners[:, 0].max(), corners[:, 1].max()
        return (float(x0), float(y0), float(x1), float(y1))

    # -- 原语 ---------------------------------------------------------------

    def _resolve(self, grob: Grob) -> _Resolved:
        resolver = _RESOLVERS.get(type(grob))
        if resolver is None:  # pragma: no cover - 新增原语忘了注册
            raise GrobError(f"{type(grob).__name__} 不在原语名单里")
        return resolver(self, grob)

    def _resolve_rect(self, grob: RectGrob) -> _Resolved:
        frame = self._frame()
        rect = self._local_rect(
            grob.x, grob.y, grob.width, grob.height, grob.hjust, grob.vjust, grob.count, frame
        )
        return _Resolved(NodeKind.RECT, {"rect": rect}, lambda gp: {})

    def _resolve_circle(self, grob: CircleGrob) -> _Resolved:
        frame = self._frame()
        n = grob.count
        cx = _recycle(frame.loc(grob.x, "x"), n)
        cy = _recycle(frame.flip(frame.loc(grob.y, "y")), n)
        r = _recycle(frame.dim(grob.r, grob.r_axis), n)
        circle = np.column_stack([cx, cy, r])
        return _Resolved(NodeKind.CIRCLE, {"circle": circle}, lambda gp: {})

    def _path_points(self, grob: Any) -> tuple[np.ndarray, np.ndarray | None]:
        frame = self._frame()
        n = grob.count
        xs = _recycle(frame.loc(grob.x, "x"), n)
        ys = _recycle(frame.flip(frame.loc(grob.y, "y")), n)
        ids = _as_ids(grob.id, n)
        return np.column_stack([xs, ys]), ids

    def _resolve_lines(self, grob: LinesGrob) -> _Resolved:
        frame = self._frame()
        n = grob.count
        xs = _recycle(frame.loc(grob.x, "x"), n)
        ys = _recycle(frame.flip(frame.loc(grob.y, "y")), n)
        return _Resolved(
            NodeKind.LINES,
            {"points": np.column_stack([xs, ys])},
            lambda gp: {},
            split=False,
        )

    def _resolve_segments(self, grob: SegmentsGrob) -> _Resolved:
        frame = self._frame()
        n = grob.count
        x0 = _recycle(frame.loc(grob.x0, "x"), n)
        y0 = _recycle(frame.flip(frame.loc(grob.y0, "y")), n)
        x1 = _recycle(frame.loc(grob.x1, "x"), n)
        y1 = _recycle(frame.flip(frame.loc(grob.y1, "y")), n)
        return _Resolved(
            NodeKind.SEGMENTS,
            {"segments": np.column_stack([x0, y0, x1, y1])},
            lambda gp: arrow_node_params(grob.arrow),
        )

    def _resolve_polyline(self, grob: PolylineGrob) -> _Resolved:
        points, ids = self._path_points(grob)
        bufs = {"points": points}
        if ids is not None:
            bufs["id"] = ids
        return _Resolved(
            NodeKind.POLYLINE, bufs, lambda gp: arrow_node_params(grob.arrow), split=False
        )

    def _resolve_polygon(self, grob: PolygonGrob) -> _Resolved:
        points, ids = self._path_points(grob)
        bufs = {"points": points}
        if ids is not None:
            bufs["id"] = ids
        return _Resolved(NodeKind.POLYGON, bufs, lambda gp: {}, split=False)

    def _resolve_path(self, grob: PathGrob) -> _Resolved:
        points, ids = self._path_points(grob)
        bufs = {"points": points}
        if ids is not None:
            bufs["id"] = ids
        return _Resolved(NodeKind.PATH, bufs, lambda gp: {"rule": grob.rule}, split=False)

    def _resolve_points(self, grob: PointsGrob) -> _Resolved:
        frame = self._frame()
        n = grob.count
        points = frame.xy(grob.x, grob.y, n)
        size = _recycle(frame.dim(grob.size, "x"), n)
        if float(size.min()) < 0:
            raise GrobError("points 的 size 不能为负")
        if float(size.max()) - float(size.min()) > 1e-9:
            raise GrobError(
                "points 的 size 只能是单值：IR 的 points.size 是一个参数，逐点尺寸表达不了"
            )
        return _Resolved(
            NodeKind.POINTS,
            {"points": points},
            lambda gp: {"pch": int(grob.pch), "size": float(size[0])},
        )

    def _resolve_text(self, grob: TextGrob) -> _Resolved:
        frame = self._frame()
        n = grob.count
        points = frame.xy(grob.x, grob.y, n)
        metrics = frame.ctx.metrics
        if metrics is None:
            raise GrobError(
                "text 需要度量：给 ViewportTree(metrics=...) 传一个 ggcore.units.Metrics"
                "（M0-7 的 MetricProvider），否则 IR 的 text.width 无从得出"
            )
        labels = tuple(grob.label[index % len(grob.label)] for index in range(n))
        fontsize = float(frame.ctx.fontsize)
        cex = float(frame.ctx.cex)
        lineheight = float(frame.ctx.lineheight)
        font_key = _font_key(frame.gpar) if frame.gpar is not None else DEFAULT_FONT_KEY
        # 多行：`\n` 切行，宽取各行的最大推进，高 = 行数 × 行高（行高 =
        # fontsize × lineheight）。IR 的 text 只带一个宽度，所以写进去的就是
        # 整块的宽（max），锚点也按整块折（docs/notes/metrics-ledger.md）。
        widths = np.asarray(
            [
                metrics.strwidth(label, fontsize=fontsize, cex=cex, font=font_key)
                * BIGPOINTS_PER_INCH
                for label in labels
            ],
            dtype=np.float64,
        )
        heights = np.asarray(
            [label.count("\n") + 1 for label in labels],
            dtype=np.float64,
        )
        hjust, vjust = grob.hjust, grob.vjust
        anchor_index = _nearest(_ANCHOR_FRACTIONS, hjust)
        baseline_index = _nearest(_BASELINE_FRACTIONS, 1.0 - vjust)
        anchor = _ANCHORS[anchor_index]
        baseline = _BASELINES[baseline_index]
        pos = points.copy()
        # pos 是锚点：把任意 (hjust, vjust) 折进 pos，枚举只表达“锚点指哪一边”。
        pos[:, 0] += (_ANCHOR_FRACTIONS[anchor_index] - hjust) * widths
        block_heights = heights * fontsize * cex * lineheight
        pos[:, 1] += (_BASELINE_FRACTIONS[baseline_index] - (1.0 - vjust)) * block_heights
        # 文字角度只放**局部**旋转：视口旋转已经在 `transform` 里（SIL-634）。
        # 视口 20° + `rot = 0` 画成 20°，不是 40°——见 `docs/notes/grobs.md` §7。
        angle = float(grob.rot)

        def params(gp: ResolvedGpar, *, label_angle: float = angle) -> dict[str, Any]:
            return {
                "font": _font_key(gp),
                "size": fontsize * cex,
                "anchor": anchor.value,
                "baseline": baseline.value,
                "angle": label_angle,
                # 多行的行距要跟着 gpar 走：R 的 `textGrob` 行距 =
                # 1.2 × lineheight × fontsize，`legend.text` 的 lineheight = 0.9
                # 时是 1.08em，不是缺省的 1.44em（SIL-820）。
                "lineheight": float(gp.lineheight),
            }

        return _Resolved(NodeKind.TEXT, {"pos": pos, "width": widths}, params, texts=labels)

    def _resolve_raster(self, grob: RasterGrob) -> _Resolved:
        frame = self._frame()
        rect = self._local_rect(
            grob.x, grob.y, grob.width, grob.height, grob.hjust, grob.vjust, 1, frame
        )
        blob = Blob(grob.data, grob.mime)
        bid = ir.blob_id(blob.data, blob.mime)
        self.blobs.setdefault(bid, blob)

        def params(gp: ResolvedGpar) -> dict[str, Any]:
            return {
                "blob": bid,
                "width": grob.width_px,
                "height": grob.height_px,
                "interpolate": grob.interpolate,
            }

        return _Resolved(NodeKind.RASTER, {"rect": rect}, params)

    def _resolve_xspline(self, grob: XSplineGrob) -> _Resolved:
        points, ids = self._path_points(grob)
        bufs = {"points": points}
        if ids is not None:
            bufs["id"] = ids
        return _Resolved(
            NodeKind.XSPLINE,
            bufs,
            lambda gp: {"shape": grob.shape, "open": grob.open},
            split=False,
        )

    def _resolve_bezier(self, grob: BezierGrob) -> _Resolved:
        frame = self._frame()
        n = grob.count
        control = np.column_stack(
            [_recycle(frame.loc(grob.x, "x"), n), _recycle(frame.flip(frame.loc(grob.y, "y")), n)]
        )
        return _Resolved(NodeKind.BEZIER, {"control": control}, lambda gp: {}, split=False)

    def _resolve_curve(self, grob: CurveGrob) -> _Resolved:
        frame = self._frame()
        ends = np.column_stack(
            [
                _recycle(frame.loc(grob.x1, "x"), 1),
                _recycle(frame.flip(frame.loc(grob.y1, "y")), 1),
                _recycle(frame.loc(grob.x2, "x"), 1),
                _recycle(frame.flip(frame.loc(grob.y2, "y")), 1),
            ]
        )
        return _Resolved(
            NodeKind.CURVE,
            {"ends": ends},
            lambda gp: {
                "curvature": grob.curvature,
                "angle": grob.angle,
                "ncp": grob.ncp,
                "shape": grob.shape,
                "square": grob.square,
                "inflect": grob.inflect,
                "open": grob.open,
                **arrow_node_params(grob.arrow),
            },
            split=False,
        )

    def _resolve_null(self, grob: NullGrob) -> _Resolved:  # pragma: no cover - 走不到
        raise GrobError("nullGrob 不产出绘制指令")


_ANCHORS: tuple[ir.Anchor, ...] = (ir.Anchor.LEFT, ir.Anchor.CENTER, ir.Anchor.RIGHT)
_ANCHOR_FRACTIONS: tuple[float, ...] = (0.0, 0.5, 1.0)
_BASELINES: tuple[ir.Baseline, ...] = (ir.Baseline.TOP, ir.Baseline.MIDDLE, ir.Baseline.BOTTOM)
_BASELINE_FRACTIONS: tuple[float, ...] = (0.0, 0.5, 1.0)


def _nearest(fractions: Sequence[float], value: float) -> int:
    """最近的枚举下标（IR 的 anchor/baseline 是枚举，任意 just 靠平移 pos 折进去）。

    先把 `value` 落到 1e-6 网格再比距离：`just` 常常正好落在两个 fraction 的中点
    （theta 标签的 `vjust = 0.5 - cos(...) / 2` 就是 0.25 / 0.75），宿主 `libm` 的
    ±1 ULP 会让「到两边的距离」翻个大小，枚举随之翻转、pos 平移半个行高——IR 的
    字节就漂了（`gate:libm-noise`，SIL-844）。平局取**较小**下标，与 `hjust = 0.25`
    这类精确中点的既有口径一致（`geom_text(hjust = 0.25)` 仍折到 left 锚点）。
    """
    value = round(float(value), 6)
    return min(range(len(fractions)), key=lambda index: (abs(fractions[index] - value), index))


_RESOLVERS: Mapping[type, Callable[[_Traverser, Any], _Resolved]] = {
    RectGrob: _Traverser._resolve_rect,
    CircleGrob: _Traverser._resolve_circle,
    LinesGrob: _Traverser._resolve_lines,
    SegmentsGrob: _Traverser._resolve_segments,
    PolylineGrob: _Traverser._resolve_polyline,
    PolygonGrob: _Traverser._resolve_polygon,
    PathGrob: _Traverser._resolve_path,
    PointsGrob: _Traverser._resolve_points,
    TextGrob: _Traverser._resolve_text,
    RasterGrob: _Traverser._resolve_raster,
    XSplineGrob: _Traverser._resolve_xspline,
    BezierGrob: _Traverser._resolve_bezier,
    CurveGrob: _Traverser._resolve_curve,
}


def scene(
    grob: GrobLike | Iterable[GrobLike],
    tree: ViewportTree,
    *,
    cache: Any = None,
) -> Scene:
    """场景遍历：grob 树 → 扁平指令序列（Device 只认这个）。

    传入单个 grob / gtable，或它们的可迭代对象（按给出顺序绘制）。遍历时
    push/pop 自己造出来的视口（grob 的 `vp`、`childrenvp`、gtable 单元格），
    结束时视口树回到进来时的状态。

    `cache=` 是增量重算用的指令缓存（`ggcore.perf.SceneInstructionCache`）：
    按内容键复用叶子解析出的指令。不传就逐条重算。
    """
    traverser = _Traverser(tree, cache=cache)
    items: Iterable[GrobLike]
    if isinstance(grob, (Grob, GTable)):
        items = (grob,)
    else:
        items = tuple(grob)
    for item in items:
        if isinstance(item, NullGrob) or isinstance(item, ZeroGrob):
            continue  # 不产出绘制指令（zeroGrob 仍参与布局，见 width_details）
        traverser.visit(item)
    blobs = BlobTable(traverser.blobs) if traverser.blobs else BlobTable.empty()
    return Scene(device=tree.device, instructions=tuple(traverser.out), blobs=blobs)


# ---------------------------------------------------------------------------
# 布局：widthDetails / heightDetails
# ---------------------------------------------------------------------------


def _extent_unit(grob: GrobLike, node: VpNode, axis: str, gp: ResolvedGpar) -> Unit:
    """一种 grob 在 `node` 视口里的自然宽/高（`widthDetails` / `heightDetails`）。

    `gp` 是**进这个 grob 之前**已经生效的 gpar；本 grob 自己的 `gp` 在这里叠上去，
    再往下传给子节点（R 的 `set.gpar()` 口径，与场景遍历同一条链）。所以
    `lines` / `char` / `strwidth` 这类依赖字号的单位用的是**继承后**的 gp，不是
    视口自己的——`gTree(gp = gpar(fontsize = 20))` 里的 `unit(2, "lines")` 是
    48pt（SIL-634）。
    """
    item = _as_grob(grob)
    if isinstance(item, (NullGrob, ZeroGrob)):
        return unit(0.0, "cm")
    inherited = gp.merge(item.gp)
    frame = _Frame(node, inherited)
    if isinstance(item, (GTreeGrob, ClipPathGrob)):
        sizes = [_extent_unit(child, node, axis, inherited) for child in item.children]
        return unit_max(*sizes) if sizes else unit(0.0, "cm")
    if isinstance(item, GTableGrob):
        table = gtable_width(item.table) if axis == "x" else gtable_height(item.table)
        return _to_absolute_pt(table, frame, axis)
    if isinstance(item, RectGrob):
        return _to_absolute_pt(item.width if axis == "x" else item.height, frame, axis)
    if isinstance(item, CircleGrob):
        return _to_absolute_pt(item.r * 2.0, frame, axis)
    if isinstance(item, PointsGrob):
        return _to_absolute_pt(item.size, frame, axis)
    if isinstance(item, RasterGrob):
        return _to_absolute_pt(item.width if axis == "x" else item.height, frame, axis)
    if isinstance(item, TextGrob):
        ctx = frame.ctx
        if ctx.metrics is None:
            raise GrobError("text 的宽高需要度量（ViewportTree(metrics=...)）")
        labels = item.label
        font_key = _font_key(inherited)
        widths = [
            ctx.metrics.strwidth(label, fontsize=ctx.fontsize, cex=ctx.cex, font=font_key)
            for label in labels
        ]
        if axis == "x":
            # 度量提供者返回英寸；这一层统一折成 bigpts（与下面的高度、以及
            # `_to_absolute_pt` 同一口径），下游再用任何上下文换算都是同一个数。
            return unit(max(widths) * 72.0 if widths else 0.0, "bigpts")
        # heightDetails：行数 × 行高（行高 = fontsize × lineheight）。
        lines = max((label.count("\n") + 1 for label in labels), default=1)
        return unit(lines * ctx.fontsize * ctx.cex * ctx.lineheight, "bigpts")

    xs, ys = _bbox_points(item, frame)
    if axis == "x":
        return unit(float(xs), "bigpts")
    return unit(float(ys), "bigpts")


def _to_absolute_pt(value: Unit, frame: _Frame, axis: str) -> Unit:
    """把依赖上下文的单位按 `frame` 的 gpar 立刻折成绝对 pt（bigpts）。

    返回的仍然是单位对象（调用方照旧 `convert_width(...)`），只是已经没有
    `lines` / `char` / `npc` 这类要上下文才能解的元素——gp 继承不会被下游覆盖。
    """
    return unit(np.asarray(frame.dim(value, axis), dtype=np.float64), "bigpts")


def _bbox_points(grob: Grob, frame: _Frame) -> tuple[float, float]:
    """路径型 / 曲线型原语的外包框（局部 pt）。"""
    n = grob.count
    if isinstance(grob, SegmentsGrob):
        xs = np.concatenate(
            [_recycle(frame.loc(grob.x0, "x"), n), _recycle(frame.loc(grob.x1, "x"), n)]
        )
        ys = np.concatenate(
            [_recycle(frame.loc(grob.y0, "y"), n), _recycle(frame.loc(grob.y1, "y"), n)]
        )
    elif isinstance(grob, CurveGrob):
        xs = np.concatenate(
            [_recycle(frame.loc(grob.x1, "x"), 1), _recycle(frame.loc(grob.x2, "x"), 1)]
        )
        ys = np.concatenate(
            [_recycle(frame.loc(grob.y1, "y"), 1), _recycle(frame.loc(grob.y2, "y"), 1)]
        )
    else:
        xs = _recycle(frame.loc(grob.x, "x"), n)  # type: ignore[attr-defined]
        ys = _recycle(frame.loc(grob.y, "y"), n)  # type: ignore[attr-defined]
    return float(xs.max() - xs.min()), float(ys.max() - ys.min())


_ABSOLUTE_UNITS = frozenset(
    {"cm", "mm", "inches", "points", "bigpts", "picas", "dida", "cicero", "scaledpts"}
)


def is_absolute_size(grob: GrobLike) -> bool:
    """grob 的尺寸是不是绝对单位（cm / mm / inches / pt …）。

    `guide_custom()` 的缺省盒子是 `grobWidth()` / `grobHeight()`，而相对单位
    （`npc` / `null` / `lines`）要先有一个视口才折得开——R 在 guide 的绘制上下文
    里量，本仓在临时页视口里量，两者对 `circleGrob(r = unit(0.5, "npc"))` 会给出
    完全不同的数（`upstream-guides-old-s3-guide-circle` 就是这么红起来的）。
    调用方拿到 ``False`` 时应退回 `legend.key.size`。
    """
    item = _as_grob(grob)
    if isinstance(item, (GTreeGrob, ClipPathGrob)):
        return all(is_absolute_size(child) for child in item.children)
    if isinstance(item, (RectGrob, RasterGrob)):
        units = (item.width, item.height)
    elif isinstance(item, CircleGrob):
        units = (item.r,)
    elif isinstance(item, PointsGrob):
        units = (item.size,)
    elif isinstance(item, TextGrob):
        return True  # 文字尺寸只由字号决定，与视口无关
    elif isinstance(item, GTableGrob):
        return all(is_absolute_size(grob) for grob in item.table.grobs)
    else:
        # 路径型 grob 由坐标决定尺寸，坐标里的相对单位同样要视口。
        return False
    return all(_unit_is_absolute(value) for value in units)


def _unit_is_absolute(value: Any) -> bool:
    """单位（含 sum/min/max 复合）的每个成分都是绝对长度。"""
    unit_obj = value if isinstance(value, Unit) else unit(value)
    for element in unit_obj:
        if element.children:
            if not all(_unit_is_absolute(Unit((child,))) for child in element.children):
                return False
        elif element.kind not in _ABSOLUTE_UNITS:
            return False
    return True


def width_details(grob: GrobLike, node: VpNode) -> Unit:
    """`widthDetails()`：grob 的自然宽度（单位对象，绝对 pt）。

    `zeroGrob` / `nullGrob` 给 0——这就是「参与布局但不产出指令」的那一半：
    gtable / gTree 排版时量得到它，遍历时画不出任何东西。

    单位在这一层就用**继承后的 gp**（视口 gpar + 外层 gTree 的 gp + 本 grob 的
    gp）折成 bigpts，所以返回的单位已经没有上下文依赖；调用方照旧
    `convert_width(width_details(grob, node), "cm", ctx=node.unit_context())` 即可，
    不需要自己再叠 gpar。
    """
    return _extent_unit(grob, node, "x", node.gpar)


def height_details(grob: GrobLike, node: VpNode) -> Unit:
    """`heightDetails()`，见 :func:`width_details`。"""
    return _extent_unit(grob, node, "y", node.gpar)

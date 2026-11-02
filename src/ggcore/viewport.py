"""grid 视口栈（SIL-596 / M0-4）。

`ggcore.viewport` 是 R `grid` 视口语义的 Python 对等物：视口树 + push/pop/
up/down 导航、单位换算后的仿射变换（含旋转与 `just` 对齐）、裁剪区继承、
gpar 逐字段继承。它是 gtable（M0-5）、grob 遍历（M0-6）和 IR 写出（M0-8）
共同的坐标底座。

坐标口径
--------
所有几何计算都在 **设备英寸、y 向上、原点在左下角** 的空间里完成——这与 R
graphics engine 一致，也是 `grid` 能在变换里直接做旋转的原因（`grid/src/
viewport.c` 的 `calcViewportTransform()`）。写 IR 前的 y 翻转由
:meth:`VpNode.ir_transform` / :meth:`VpNode.ir_clip_rect` 负责，见
`docs/notes/ir.md` 的坐标约定。

一个视口的变换与 R 逐条对应（行向量 3×3，`matrix.c` 的 `trans()`）：

    transform = J · R · L · parent.transform

- `L`：把视口左下角移到父坐标系里的 `(x, y)`（单位在**父视口**里换算）；
- `R`：绕对齐点旋转 `angle` 度（逆时针，y 向上）；
- `J`：`just` 带来的平移 `(-width*hjust, -height*vjust)`，所以旋转是绕
  “对齐点”转的，不是绕固定角点；
- `parent.transform`：父视口自己到设备的变换。

单位换算是 M0-3 的 `ggcore.units`：视口的 `x`/`y`/`width`/`height` 用**父视口**
的 :class:`~ggcore.units.UnitContext` 求值，视口内部坐标用**自己**的（宽度、
`xscale`/`yscale`、gpar 的字号/cex/行高）。不另造单位系统。

与 R 的已知差异（完整账本见 `docs/notes/viewport.md`）：

- gpar 里的显式 `None` 表示“清空该字段，回到 grid 缺省值”；R 的
  `gpar(col = NULL)` 是把该字段从增量里删掉（等价于“不覆盖”），见
  :meth:`ResolvedGpar.merge`。
- 根视口的 `xscale`/`yscale` 就是 **设备原生单位**：本模块的 `Device` 以英寸
  计量，所以根级 `unit(1, "native")` = 1 英寸（R 的 pdf 设备原生单位是点，
  同一条规则、不同的设备单位；见 `docs/notes/viewport.md` §9 / §12）。
- 路径匹配按**段**精确比较；R 的 `pathMatch()` 把路径当正则、只锚定末尾
  （所以 `down("a::b")` 在 `xxa/b` 树里 R 命中、这里不命中）。
- 裁剪路径（`clip = grob`）、mask、viewport layout（`layout.pos.row/col`，
  M0-5）不在本模块范围内。
"""

from __future__ import annotations

import itertools
import math
import warnings
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

import numpy as np

from ggcore.units import (
    CM_PER_INCH,
    Metrics,
    Unit,
    UnitContext,
    UnitError,
    convert_unit,
    unit,
)

__all__ = [
    "GPAR_FIELDS",
    "IDENTITY",
    "NA",
    "Affine",
    "Clip",
    "Device",
    "Gpar",
    "ResolvedGpar",
    "RotatedClipWarning",
    "Viewport",
    "ViewportError",
    "ViewportTree",
    "VpNode",
    "VpPath",
    "device_loc",
    "gpar",
    "viewport",
    "vp_path",
]

# R 的 `.grid.pathSep`
PATH_SEP = "::"


class ViewportError(ValueError):
    """视口构造、导航或换算失败。消息尽量贴近 R 的 conditionMessage。"""


class RotatedClipWarning(UserWarning):
    """`clip="on"` 撞上不能轴对齐的旋转（R：`cannot clip to rotated viewport`）。"""


# ---------------------------------------------------------------------------
# 仿射变换（行向量 2×3，与 grid `matrix.c` 的 m[i][j] 布局一一对应）
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Affine:
    """行向量 2×3 仿射：``x' = a*x + c*y + e``、``y' = b*x + d*y + f``。

    分量顺序跟 SVG / CanvasKit 的 `matrix(a, b, c, d, e, f)` 相同，写 IR 时不用
    再重排。R 侧 3×3 的 `trans()` 就是这份布局：`m[0][0]=a`、`m[0][1]=b`、
    `m[1][0]=c`、`m[1][1]=d`、`m[2][0]=e`、`m[2][1]=f`。
    """

    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e: float = 0.0
    f: float = 0.0

    def map(self, x: float, y: float) -> tuple[float, float]:
        """单点变换（不做取整，全 double）。"""
        return (self.a * x + self.c * y + self.e, self.b * x + self.d * y + self.f)

    def map_array(self, x: np.ndarray[Any, Any], y: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
        """批量变换：返回 ``(n, 2)`` float64。"""
        out = np.empty((x.size, 2), dtype=np.float64)
        out[:, 0] = self.a * x + self.c * y + self.e
        out[:, 1] = self.b * x + self.d * y + self.f
        return out

    def then(self, other: Affine) -> Affine:
        """先把 `self` 作用在点上，再作用 `other`（= grid `multiply(self, other)`）。

        `trans` 是行向量乘以矩阵，所以 ``p · (M1·M2) = (p·M1)·M2``：等号左边先
        作用，和直觉的“矩阵乘法顺序”相反。
        """
        return Affine(
            a=self.a * other.a + self.b * other.c,
            b=self.a * other.b + self.b * other.d,
            c=self.c * other.a + self.d * other.c,
            d=self.c * other.b + self.d * other.d,
            e=self.e * other.a + self.f * other.c + other.e,
            f=self.e * other.b + self.f * other.d + other.f,
        )

    def inverse(self) -> Affine:
        """逆变换（grid `invTransform()` 的 2×3 退化版）。"""
        det = self.a * self.d - self.b * self.c
        if det == 0:
            raise ViewportError("singular transformation matrix")
        a = self.d / det
        b = -self.b / det
        c = -self.c / det
        d = self.a / det
        return Affine(
            a=a, b=b, c=c, d=d, e=-(a * self.e + c * self.f), f=-(b * self.e + d * self.f)
        )

    def as_tuple(self) -> tuple[float, float, float, float, float, float]:
        """`(a, b, c, d, e, f)`，便于断言与序列化。"""
        return (self.a, self.b, self.c, self.d, self.e, self.f)

    @staticmethod
    def translation(tx: float, ty: float) -> Affine:
        return Affine(e=float(tx), f=float(ty))

    @staticmethod
    def rotation(degrees: float) -> Affine:
        """逆时针旋转（y 向上；与 grid `rotation()` 同号）。"""
        theta = math.radians(degrees)
        cos = math.cos(theta)
        sin = math.sin(theta)
        return Affine(a=cos, b=sin, c=-sin, d=cos)


IDENTITY = Affine()


def _compose(*affines: Affine) -> Affine:
    result = IDENTITY
    for item in affines:
        result = result.then(item)
    return result


def _points_to_inches(height_in: float) -> Affine:
    """本视口坐标（pt，y 向下）→ 本视口英寸（y 向上，原点左下）。"""
    return Affine(a=1.0 / 72.0, d=-1.0 / 72.0, f=height_in)


def _inches_to_points(height_in: float) -> Affine:
    """本视口英寸（y 向上）→ 本视口坐标（pt，y 向下）。"""
    return Affine(a=72.0, d=-72.0, f=height_in * 72.0)


# ---------------------------------------------------------------------------
# gpar：增量与解析值
# ---------------------------------------------------------------------------


class _UnsetType:
    """“字段没写”的哨兵：与 `None`（显式清空）必须区分开。"""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - 只为调试可读
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET = _UnsetType()


class _NAType:
    """R 的 `NA`：颜色字段里表示“透明 / 不画”（`gpar(col = NA)`）。

    与 `None` 是两件事，见 `docs/notes/grobs.md`：

    - :data:`UNSET`：字段没写，继承父值；
    - `None`：显式清空，解析时回落到 grid 缺省值；
    - :data:`NA`：解析后仍然留在 gpar 里，写 IR 时折成“不描边 / 不填充”。

    只用 `__slots__` 的空单例，`is NA` 是唯一的判定方式；不要拿它当布尔值用。
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - 只为调试可读
        return "NA"

    def __bool__(self) -> bool:
        raise TypeError("NA has no truth value (R: NA is not TRUE/FALSE)")


NA = _NAType()
"""颜色字段的 `NA` 哨兵（R 的 `NA`），见 :class:`_NAType`。"""

#: gpar 字段顺序与 grid 缺省值（`gpar.c` 的 `initGPar()` 在 pdf 设备上
#: `get.gpar()` 的结果）。`cex` / `alpha` / `lex` 是累积的（R `set.gpar()`）。
GPAR_FIELDS: tuple[tuple[str, Any], ...] = (
    ("fill", "transparent"),
    ("col", "black"),
    ("lwd", 1.0),
    ("lty", "solid"),
    ("lineend", "round"),
    ("linejoin", "round"),
    ("linemitre", 10.0),
    ("alpha", 1.0),
    ("cex", 1.0),
    ("fontsize", 12.0),
    ("lineheight", 1.2),
    ("font", 1),
    ("fontfamily", ""),
    ("lex", 1.0),
)

GPAR_DEFAULTS: Mapping[str, Any] = dict(GPAR_FIELDS)
#: R `set.gpar()` 里相乘（不是覆盖）的字段。
CUMULATIVE_GPAR = frozenset({"cex", "alpha", "lex"})
_LINEENDS = frozenset({"round", "butt", "square"})
#: R 不做校验，两种拼法都收（"mitre" 是 grid 文档里的写法，值原样保留）。
_LINEJOINS = frozenset({"round", "miter", "mitre", "bevel"})


def _check_number(name: str, value: Any, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ViewportError(f"gpar.{name} 必须是数值，收到 {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ViewportError(f"gpar.{name} 必须是有限值，收到 {value!r}")
    if minimum is not None and number < minimum:
        raise ViewportError(f"gpar.{name} 不能小于 {minimum}，收到 {value!r}")
    return number


@dataclass(frozen=True, slots=True)
class Gpar:
    """gpar **增量**（R 的 `gpar(...)`）：没写的字段是 :data:`UNSET`。

    三类取值不能混：

    - :data:`UNSET`（默认）：不覆盖，继承父视口的解析值；
    - `None`：显式清空，解析时回到 `GPAR_DEFAULTS` 里的缺省值；
    - 具体值：覆盖（`cex` / `alpha` / `lex` 与父值相乘，与 R 一致）。

    颜色字段（`fill` / `col`）另收 :data:`NA` —— R 的“透明 / 不画”，它**不**
    清空、也不继承，解析后原样留着，由写 IR 的一方折成“不描边 / 不填充”。

    R 的 `gpar(col = NULL)` 走的是“从增量里删掉”（等价于 :data:`UNSET`），
    这里刻意分开，见 `docs/notes/viewport.md`。
    """

    fill: Any = UNSET
    col: Any = UNSET
    lwd: Any = UNSET
    lty: Any = UNSET
    lineend: Any = UNSET
    linejoin: Any = UNSET
    linemitre: Any = UNSET
    alpha: Any = UNSET
    cex: Any = UNSET
    fontsize: Any = UNSET
    lineheight: Any = UNSET
    font: Any = UNSET
    fontfamily: Any = UNSET
    lex: Any = UNSET

    def __post_init__(self) -> None:
        for name in ("fill", "col"):
            value = getattr(self, name)
            if value is UNSET or value is None or value is NA:
                continue
            if not isinstance(value, str):
                raise ViewportError(f"gpar.{name} 必须是颜色字符串、NA 或 None，收到 {value!r}")
        for name in ("lwd", "alpha", "cex", "fontsize", "lineheight", "linemitre", "lex"):
            value = getattr(self, name)
            if value is not UNSET and value is not None:
                _check_number(f"{name}", value, minimum=None)
        for name in ("lwd", "alpha", "cex", "fontsize", "lineheight", "lex"):
            value = getattr(self, name)
            if value is not UNSET and value is not None and float(value) < 0:
                raise ViewportError(f"gpar.{name} 不能为负，收到 {value!r}")
        alpha = self.alpha
        if alpha is not UNSET and alpha is not None and not 0.0 <= float(alpha) <= 1.0:
            raise ViewportError(f"gpar.alpha 必须在 [0, 1]，收到 {alpha!r}")
        linemitre = self.linemitre
        if linemitre is not UNSET and linemitre is not None and float(linemitre) < 1.0:
            raise ViewportError(f"gpar.linemitre 不能小于 1，收到 {linemitre!r}")
        for name, allowed in (("lineend", _LINEENDS), ("linejoin", _LINEJOINS)):
            value = getattr(self, name)
            if value is not UNSET and value is not None and value not in allowed:
                raise ViewportError(f"gpar.{name} 不认识：{value!r}")
        lty = self.lty
        if lty is not UNSET and lty is not None and lty is not NA:
            if isinstance(lty, bool):
                raise ViewportError(f"gpar.lty 必须是样式名、编号或段长序列，收到 {lty!r}")
            if isinstance(lty, int):
                # R 的 `lty = 0..6`（0 是 blank）；段长在写 IR 时折成 pt。
                if not 0 <= lty <= 6:
                    raise ViewportError(f"gpar.lty 必须在 0..6，收到 {lty!r}")
            elif not isinstance(lty, (str, tuple, list)):
                raise ViewportError(f"gpar.lty 必须是样式名、编号或段长序列，收到 {lty!r}")
        font = self.font
        if font is not UNSET and font is not None:
            if isinstance(font, bool) or not isinstance(font, int):
                raise ViewportError(f"gpar.font 必须是整数，收到 {font!r}")
            if not 1 <= font <= 5:
                raise ViewportError(f"gpar.font 必须在 1..5，收到 {font!r}")

    def items(self) -> Iterator[tuple[str, Any]]:
        """只产出**写在增量里**的字段（含显式清空的 `None`）。"""
        for name, _ in GPAR_FIELDS:
            value = getattr(self, name)
            if value is not UNSET:
                yield name, value

    def as_dict(self) -> dict[str, Any]:
        return dict(self.items())


def gpar(**kwargs: Any) -> Gpar:
    """`gpar(...)` 的便捷构造；未知字段名直接报错（R 的 `validGP` 也这么干）。"""
    unknown = set(kwargs) - {name for name, _ in GPAR_FIELDS}
    if unknown:
        raise ViewportError(f"不认识的 gpar 字段：{', '.join(sorted(unknown))}")
    return Gpar(**kwargs)


@dataclass(frozen=True, slots=True)
class ResolvedGpar:
    """某个视口的**解析后** gpar：每个字段都有值，没有继承这一步。

    颜色字段保留三态的结果：具体颜色字符串、`None`（清空后回落到缺省值——
    正常路径不会留下它），或 :data:`NA`（透明 / 不画）。`NA` 与缺省值 `"black"`
    是两件事，见 `docs/notes/grobs.md`。
    """

    fill: Any = "transparent"
    col: Any = "black"
    lwd: float = 1.0
    lty: Any = "solid"
    lineend: str = "round"
    linejoin: str = "round"
    linemitre: float = 10.0
    alpha: float = 1.0
    cex: float = 1.0
    fontsize: float = 12.0
    lineheight: float = 1.2
    font: int = 1
    fontfamily: str = ""
    lex: float = 1.0

    def merge(self, delta: Gpar) -> ResolvedGpar:
        """父值 + 增量 = 子值（R `set.gpar()`）：未设置不覆盖，`None` 回缺省。

        `cex` / `alpha` / `lex` 是 R 的特例——累积相乘；显式 `None` 不参与乘法，
        直接清回缺省（1.0）。:data:`NA` 原样留着，不参与乘法也不回缺省。
        """
        if not isinstance(delta, Gpar):
            raise ViewportError(f"gp 必须是 Gpar，收到 {type(delta).__name__}")
        values: dict[str, Any] = {}
        for name, _ in GPAR_FIELDS:
            value = getattr(delta, name)
            if value is UNSET:
                values[name] = getattr(self, name)
            elif value is None:
                values[name] = GPAR_DEFAULTS[name]
            elif name in CUMULATIVE_GPAR:
                values[name] = float(getattr(self, name)) * float(value)
            else:
                values[name] = value
        return ResolvedGpar(**values)

    def as_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name, _ in GPAR_FIELDS}

    @classmethod
    def defaults(cls) -> ResolvedGpar:
        return cls()


# ---------------------------------------------------------------------------
# 视口规格：just / clip / 构造
# ---------------------------------------------------------------------------


class Clip(StrEnum):
    """裁剪三态。R 4.5.3 的字符串形式 → 逻辑值：

    - `on` → `TRUE`：裁剪到本视口；
    - `off` → `NA`：裁剪到整个设备（比设备略大，避免边缘效应）；
    - `inherit` → `FALSE`：沿用父视口的裁剪区（**R 4.5 的缺省值**）。
    """

    ON = "on"
    OFF = "off"
    INHERIT = "inherit"


def _clip(value: Any) -> Clip:
    if isinstance(value, Clip):
        return value
    if isinstance(value, bool):
        raise ViewportError(
            "clip 用 'on'/'off'/'inherit'；R 的逻辑形式 TRUE/NA/FALSE 依次对应 on/off/inherit"
        )
    try:
        return Clip(str(value))
    except ValueError:
        raise ViewportError(f"invalid 'clip' value: {value!r}") from None


_JUST_NAMES = {
    "left": (0.0, None),
    "right": (1.0, None),
    "bottom": (None, 0.0),
    "top": (None, 1.0),
    "centre": (0.5, 0.5),
    "center": (0.5, 0.5),
}


def normalize_just(just: Any) -> tuple[float, float]:
    """R `valid.just()`：字符串/数值 → `(hjust, vjust)`，都在 `[0, 1]`。"""
    if just is None:
        return (0.5, 0.5)
    if isinstance(just, str):
        key = just.lower()
        if key not in _JUST_NAMES:
            raise ViewportError(f"invalid justification: {just!r}")
        horizontal, vertical = _JUST_NAMES[key]
        return (
            0.5 if horizontal is None else horizontal,
            0.5 if vertical is None else vertical,
        )
    if isinstance(just, (int, float)) and not isinstance(just, bool):
        return (float(just), 0.5)

    try:
        items = list(just)
    except TypeError:
        raise ViewportError(f"invalid justification: {just!r}") from None
    if not items:
        return (0.5, 0.5)
    if len(items) == 1:
        return normalize_just(items[0])
    horizontal, vertical = items[0], items[1]
    if isinstance(horizontal, str):
        key = horizontal.lower()
        if key not in ("left", "right", "centre", "center"):
            raise ViewportError(f"invalid horizontal justification: {horizontal!r}")
        hjust = _JUST_NAMES[key][0]
        assert hjust is not None
    else:
        hjust = float(horizontal)
    if isinstance(vertical, str):
        key = vertical.lower()
        if key not in ("bottom", "top", "centre", "center"):
            raise ViewportError(f"invalid vertical justification: {vertical!r}")
        vjust = _JUST_NAMES[key][1]
        assert vjust is not None
    else:
        vjust = float(vertical)
    return (hjust, vjust)


def _scale(name: str, value: Any) -> tuple[float, float]:
    # 任意非字符串可迭代对象都收：panel 的 `xscale`/`yscale` 大概率直接来自
    # numpy 数组（`np.ndarray` 不是 `Sequence`，只认 `Sequence` 会把最常见的
    # 写法挡在门外）。
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise ViewportError(f"invalid '{name}' in viewport")
    try:
        items = [float(item) for item in value]
    except (TypeError, ValueError):
        raise ViewportError(f"invalid '{name}' in viewport") from None
    if len(items) != 2:
        raise ViewportError(f"invalid '{name}' in viewport")
    if not all(math.isfinite(item) for item in items):
        raise ViewportError(f"invalid '{name}' in viewport")
    if items[0] == items[1]:
        raise ViewportError(f"invalid '{name}' in viewport")
    return (items[0], items[1])


_auto_name_counter = itertools.count(1)


def _auto_name() -> str:
    """R 的 `vpAutoName()`：`GRID.VP.<n>`（计数在进程内单调）。"""
    return f"GRID.VP.{next(_auto_name_counter)}"


def _as_unit(name: str, value: Any, default_units: str) -> Unit:
    if isinstance(value, Unit):
        if len(value) != 1:
            raise ViewportError(f"'{name}' must be a unit of length 1")
        return value
    if isinstance(value, bool):
        raise ViewportError(f"'{name}' must be a unit or a number")
    if isinstance(value, (int, float)):
        return unit(float(value), default_units)
    raise ViewportError(f"'{name}' must be a unit or a number, got {type(value).__name__}")


def _probe_unit(name: str, value: Any) -> Unit:
    """探针坐标：数字按 `npc` 解释，单位对象可以带向量（批量换算用）。"""
    if isinstance(value, Unit):
        if len(value) == 0:
            raise ViewportError(f"'{name}' must have length > 0")
        return value
    if isinstance(value, bool):
        raise ViewportError(f"'{name}' must be a unit or a number")
    if isinstance(value, (int, float)):
        return unit(float(value), "npc")
    raise ViewportError(f"'{name}' must be a unit or a number, got {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class Viewport:
    """视口**规格**（R 的 `viewport` 对象）。push 时复制成 :class:`VpNode`。

    规格本身不可变、可复用：同一个 `Viewport` 可以 push 多次，每次得到独立的
    树节点（R `L_setviewport()` 的 `duplicate()` 也是这个意思）。
    """

    x: Unit = field(default_factory=lambda: unit(0.5, "npc"))
    y: Unit = field(default_factory=lambda: unit(0.5, "npc"))
    width: Unit = field(default_factory=lambda: unit(1.0, "npc"))
    height: Unit = field(default_factory=lambda: unit(1.0, "npc"))
    just: tuple[float, float] = (0.5, 0.5)
    xscale: tuple[float, float] = (0.0, 1.0)
    yscale: tuple[float, float] = (0.0, 1.0)
    angle: float = 0.0
    clip: Clip = Clip.INHERIT
    gpar: Gpar = field(default_factory=Gpar)
    name: str = ""

    def __post_init__(self) -> None:
        for name in ("x", "y", "width", "height"):
            value = getattr(self, name)
            if not isinstance(value, Unit) or len(value) != 1:
                raise ViewportError(f"'{name}' must be a unit of length 1")
        for name in ("xscale", "yscale"):
            object.__setattr__(self, name, _scale(name, getattr(self, name)))
        object.__setattr__(self, "just", normalize_just(self.just))
        if isinstance(self.angle, bool) or not isinstance(self.angle, (int, float)):
            raise ViewportError(f"invalid 'angle' in viewport: {self.angle!r}")
        if not math.isfinite(float(self.angle)):
            raise ViewportError(f"invalid 'angle' in viewport: {self.angle!r}")
        object.__setattr__(self, "angle", float(self.angle))
        object.__setattr__(self, "clip", _clip(self.clip))
        if not isinstance(self.gpar, Gpar):
            raise ViewportError(f"invalid 'gp' value: {type(self.gpar).__name__}")
        if self.name is None:
            object.__setattr__(self, "name", _auto_name())
        elif not isinstance(self.name, str):
            object.__setattr__(self, "name", str(self.name))

    @property
    def hjust(self) -> float:
        return self.just[0]

    @property
    def vjust(self) -> float:
        return self.just[1]


def viewport(
    name: str | None = None,
    *,
    x: Any = 0.5,
    y: Any = 0.5,
    width: Any = 1.0,
    height: Any = 1.0,
    default_units: str = "npc",
    just: Any = "centre",
    gp: Gpar | Mapping[str, Any] | None = None,
    gpar: Gpar | Mapping[str, Any] | None = None,
    clip: Clip | str = Clip.INHERIT,
    xscale: Any = (0.0, 1.0),
    yscale: Any = (0.0, 1.0),
    angle: float = 0.0,
) -> Viewport:
    """`viewport()`：数字按 `default_units` 解释（缺省 `npc`），单位对象原样用。

    R 的签名是 `viewport(..., gp = gpar())`；这里同时接受 `gpar=`，因为
    Python 里 `gpar` 也是构造函数的常用叫法。
    """
    if gp is not None and gpar is not None:
        raise ViewportError("gp 与 gpar 只能给一个")
    raw_gp = gp if gp is not None else gpar
    if raw_gp is None:
        delta = Gpar()
    elif isinstance(raw_gp, Gpar):
        delta = raw_gp
    elif isinstance(raw_gp, Mapping):
        delta = Gpar(**raw_gp)
    else:
        raise ViewportError(f"invalid 'gp' value: {type(raw_gp).__name__}")
    return Viewport(
        x=_as_unit("x", x, default_units),
        y=_as_unit("y", y, default_units),
        width=_as_unit("width", width, default_units),
        height=_as_unit("height", height, default_units),
        just=normalize_just(just),
        xscale=_scale("xscale", xscale),
        yscale=_scale("yscale", yscale),
        angle=angle,
        clip=_clip(clip),
        gpar=delta,
        name=_auto_name() if name is None else name,
    )


# ---------------------------------------------------------------------------
# vpPath
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VpPath:
    """`vpPath()`：从祖先到后代的名称序列（`a::b::c`）。"""

    names: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.names:
            raise ViewportError("vpPath must have at least one component")
        if not all(isinstance(name, str) for name in self.names):
            raise ViewportError("vpPath components must be strings")

    def __str__(self) -> str:
        return PATH_SEP.join(self.names)

    def __len__(self) -> int:
        return len(self.names)

    @property
    def depth(self) -> int:
        return len(self.names)

    @classmethod
    def parse(cls, value: str | VpPath | Sequence[str]) -> VpPath:
        """字符串（含 `::` 则拆段）/ 序列 / `VpPath` → `VpPath`。"""
        if isinstance(value, VpPath):
            return value
        if isinstance(value, str):
            if PATH_SEP in value:
                parts = tuple(part for part in value.split(PATH_SEP) if part != "")
                if not parts:
                    raise ViewportError(f"invalid vpPath: {value!r}")
                return cls(parts)
            return cls((value,))
        if isinstance(value, Sequence):
            return cls(tuple(value))
        raise ViewportError(f"invalid vpPath: {value!r}")


def vp_path(*names: str | VpPath | Sequence[str]) -> VpPath:
    """`vpPath("a", "b")`；单个带 `::` 的字符串会被拆开（R 的行为）。"""
    if len(names) == 1:
        return VpPath.parse(names[0])
    flattened: list[str] = []
    for item in names:
        flattened.extend(VpPath.parse(item).names)
    return VpPath(tuple(flattened))


# ---------------------------------------------------------------------------
# 设备
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Device:
    """设备尺寸（英寸）。根视口铺满它，`clip="off"` 也是它的 1.5 倍外包框。"""

    width_in: float = 7.0
    height_in: float = 7.0

    def __post_init__(self) -> None:
        for name in ("width_in", "height_in"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0:
                raise ViewportError(f"device {name} must be positive, got {value!r}")

    @property
    def width_cm(self) -> float:
        return self.width_in * CM_PER_INCH

    @property
    def height_cm(self) -> float:
        return self.height_in * CM_PER_INCH


# ---------------------------------------------------------------------------
# 树节点
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Computed:
    """push 时算好、设备尺寸变化时重算的那部分状态（R 的 pushedvp 槽位）。"""

    width_cm: float
    height_cm: float
    transform: Affine
    rotation: float
    clip_rect: tuple[float, float, float, float]


@dataclass(eq=False, slots=True)
class VpNode:
    """已 push 的视口（R 的 `pushedvp`）：规格 + 父/子 + 解析后的 gpar + 变换。"""

    spec: Viewport
    parent: VpNode | None
    parent_gpar: ResolvedGpar
    gpar: ResolvedGpar
    device: Device
    metrics: Metrics | None = None
    children: dict[str, VpNode] = field(default_factory=dict)
    _computed: _Computed | None = None

    # -- 规格的直通属性 -----------------------------------------------------

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def x(self) -> Unit:
        return self.spec.x

    @property
    def y(self) -> Unit:
        return self.spec.y

    @property
    def width(self) -> Unit:
        return self.spec.width

    @property
    def height(self) -> Unit:
        return self.spec.height

    @property
    def just(self) -> tuple[float, float]:
        return self.spec.just

    @property
    def xscale(self) -> tuple[float, float]:
        return self.spec.xscale

    @property
    def yscale(self) -> tuple[float, float]:
        return self.spec.yscale

    @property
    def angle(self) -> float:
        return self.spec.angle

    @property
    def clip(self) -> Clip:
        return self.spec.clip

    # -- 计算状态 -----------------------------------------------------------

    def _require(self) -> _Computed:
        if self._computed is None:  # pragma: no cover - push 一定先算
            raise ViewportError(f"viewport {self.name!r} has no computed transform")
        return self._computed

    @property
    def width_cm(self) -> float:
        return self._require().width_cm

    @property
    def height_cm(self) -> float:
        return self._require().height_cm

    @property
    def width_in(self) -> float:
        return self.width_cm / CM_PER_INCH

    @property
    def height_in(self) -> float:
        return self.height_cm / CM_PER_INCH

    @property
    def transform(self) -> Affine:
        """本视口坐标（英寸，y 向上）→ 设备坐标（英寸，y 向上）。"""
        return self._require().transform

    @property
    def rotation(self) -> float:
        """累积旋转角（R 的 `viewportRotation()`）：父旋转 + 自己。"""
        return self._require().rotation

    @property
    def clip_rect(self) -> tuple[float, float, float, float]:
        """当前生效的裁剪框（设备英寸，y 向上，**未规范化**）。

        R 里同样是未经排序的四元组：`clip="on"` + 90° 旋转时 `x0 > x1`，
        渲染端要自己取 min/max（见 :attr:`clip_box`）。
        """
        return self._require().clip_rect

    @property
    def clip_box(self) -> tuple[float, float, float, float]:
        """规范化后的裁剪框 `(x0, y0, x1, y1)`，`x0 <= x1`、`y0 <= y1`。"""
        x0, y0, x1, y1 = self.clip_rect
        return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))

    # -- 坐标换算 -----------------------------------------------------------

    def unit_context(self) -> UnitContext:
        """在本视口内部换算单位用的上下文（自己这一级的尺寸/刻度/gpar）。"""
        return UnitContext(
            width_cm=self.width_cm,
            height_cm=self.height_cm,
            xscale=self.xscale,
            yscale=self.yscale,
            fontsize=self.gpar.fontsize,
            cex=self.gpar.cex,
            lineheight=self.gpar.lineheight,
            metrics=self.metrics,
        )

    def convert(
        self,
        target: Unit,
        to: str,
        *,
        axis: str = "x",
        measure: str = "location",
        value_only: bool = True,
    ) -> Any:
        """在本视口里换算单位（`convertX` / `convertY` / `convertWidth` / ...）。"""
        return convert_unit(
            target,
            to,
            ctx=self.unit_context(),
            axis_from=axis,
            type_from=measure,
            axis_to=axis,
            type_to=measure,
            value_only=value_only,
        )

    def local_loc(self, x: Any, y: Any) -> np.ndarray[Any, Any]:
        """视口内部坐标（任意单位，可给向量）→ 本视口原点起算的英寸 `(n, 2)`。"""
        xs = _probe_unit("x", x)
        ys = _probe_unit("y", y)
        ctx = self.unit_context()
        xi = convert_unit(xs, "inches", ctx=ctx, axis_from="x", type_from="location")
        yi = convert_unit(ys, "inches", ctx=ctx, axis_from="y", type_from="location")
        count = max(xi.size, yi.size)
        if count == 0:
            raise ViewportError("no locations to convert")
        # R 的 transformLocn 按 index %% length 循环取值（recycle）。
        xi = np.resize(xi, count)
        yi = np.resize(yi, count)
        return np.column_stack([xi, yi])

    def device_points(self, x: Any, y: Any) -> np.ndarray[Any, Any]:
        """视口内部坐标 → 设备坐标（英寸，y 向上），`(n, 2)`。"""
        local = self.local_loc(x, y)
        return self.transform.map_array(local[:, 0], local[:, 1])

    def device_loc(self, x: Any, y: Any) -> tuple[float, float]:
        """单点版本（R `deviceLoc()`）：返回设备英寸。"""
        points = self.device_points(x, y)
        return (float(points[0, 0]), float(points[0, 1]))

    # -- 写 IR --------------------------------------------------------------

    def ir_transform(self) -> Affine:
        """子坐标（pt，y 向下）→ 父视口坐标（pt，y 向下）的 2×3 仿射。

        与 `docs/notes/ir.md` 的约定一致：IR 里的 `viewport.transform` 是**相对
        父视口**的，坐标已解析成 pt、y 向下；根视口是单位阵。设备高度在两端
        翻转里互相抵消，所以不需要传页面尺寸。
        """
        own = _points_to_inches(self.height_in).then(self.transform)
        if self.parent is None:
            return own.then(_inches_to_points(self.height_in))
        to_parent = own.then(self.parent.transform.inverse())
        return to_parent.then(_inches_to_points(self.parent.height_in))

    def ir_clip_rect(self) -> tuple[float, float, float, float]:
        """裁剪框 → IR 坐标（pt、y 向下、原点左上、**页面绝对坐标**），已规范化。

        不是子坐标：IR v0.2 起 `viewport.clip_rect` 的口径就是页面坐标（见
        `docs/notes/ir.md` §4）。旋转 `inherit` 的生效裁剪框在子坐标里不是
        轴对齐矩形，4 元组表达不了；页面坐标无损，M0-8 在合成页面变换之后
        直接在页面空间里裁剪。
        """
        x0, y0, x1, y1 = self.clip_box
        height = self.device.height_in * 72.0
        return (x0 * 72.0, height - y1 * 72.0, x1 * 72.0, height - y0 * 72.0)

    # -- 树 -----------------------------------------------------------------

    @property
    def path(self) -> VpPath:
        """从根视口下方开始的路径（R 的 `current.vpPath()`；根给单段 "ROOT"）。"""
        names: list[str] = []
        node: VpNode | None = self
        while node is not None and node.parent is not None:
            names.append(node.name)
            node = node.parent
        names.reverse()
        return VpPath(tuple(names)) if names else VpPath((self.name,))

    @property
    def depth(self) -> int:
        """根是 0（R 的 `vpDepth()`）。"""
        node: VpNode | None = self
        count = 0
        while node.parent is not None:
            count += 1
            node = node.parent
        return count

    def siblings(self) -> tuple[VpNode, ...]:
        """兄弟节点（按 push 顺序；查找顺序是名称排序，见 :meth:`ViewportTree.find`）。"""
        if self.parent is None:
            return (self,)
        return tuple(self.parent.children.values())

    def descendants(self) -> Iterator[VpNode]:
        """深度优先遍历所有后代（按名称排序，和 R 的 children 环境一致）。"""
        for name in sorted(self.children):
            child = self.children[name]
            yield child
            yield from child.descendants()

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<VpNode {self.path!s} angle={self.rotation:g}>"


# ---------------------------------------------------------------------------
# 视口树 / 栈
# ---------------------------------------------------------------------------


def _root_viewport(device: Device) -> Viewport:
    """R 的 `grid.top.level.vp()`：铺满设备、左下对齐、`clip="on"`。

    `xscale` / `yscale` 定成**设备原生单位**。R 的原生单位是设备的设备坐标
    （pdf 下是点：7in × 72 = 504），本模块的 :class:`Device` 以英寸计量，所以
    这里就是 `0 .. width_in`——根级 `unit(1, "native")` 恰好是 1 英寸，与
    M0 交接点名的口径一致。子视口仍按自己的 `xscale` / `yscale` 换算
    （`tests/test_viewport.py::test_root_native_units_are_device_inches`）。
    """
    return Viewport(
        x=unit(0.0, "npc"),
        y=unit(0.0, "npc"),
        width=unit(1.0, "npc"),
        height=unit(1.0, "npc"),
        just=(0.0, 0.0),
        xscale=(0.0, device.width_in),
        yscale=(0.0, device.height_in),
        angle=0.0,
        clip=Clip.ON,
        gpar=Gpar(),
        name="ROOT",
    )


class ViewportTree:
    """一个设备上的视口树 + 当前视口栈（R 的 `GSS_VP` / `GSS_GPAR` 状态）。

    语义对照 R：

    - :meth:`push` = `pushViewport()`：新视口挂到当前视口下，`parentgpar` 记下
      推进来的 gpar，解析后的 gpar 成为当前 gpar；
    - :meth:`pop` = `popViewport()`：从树上摘掉，gpar 回到被摘掉视口的
      `parentgpar`；
    - :meth:`up` = `upViewport()`：只上移，不动树；
    - :meth:`down` = `downViewport()`：导航到已存在的名字/路径，gpar **直接换成**
      目标视口的解析值（不是累积，R 特意没用 `set.gpar()`）；
    - :meth:`seek` = `seekViewport()`：先到根再往下找。
    """

    def __init__(
        self,
        device: Device | None = None,
        *,
        metrics: Metrics | None = None,
        root: Viewport | None = None,
    ) -> None:
        self.device = device if device is not None else Device()
        self.metrics = metrics
        spec = root if root is not None else _root_viewport(self.device)
        if spec.name != "ROOT":
            raise ViewportError("根视口必须叫 'ROOT'")
        node = VpNode(
            spec=spec,
            parent=None,
            parent_gpar=ResolvedGpar.defaults(),
            gpar=ResolvedGpar.defaults().merge(spec.gpar),
            device=self.device,
            metrics=metrics,
        )
        self._root = node
        self._current = node
        self._gpar = node.gpar
        self._compute(node, is_root=True)

    # -- 状态 ---------------------------------------------------------------

    @property
    def root(self) -> VpNode:
        return self._root

    @property
    def current(self) -> VpNode:
        return self._current

    @property
    def gpar(self) -> ResolvedGpar:
        """当前生效的 gpar（R 的 `GSS_GPAR`）。"""
        return self._gpar

    @contextmanager
    def temporary_gpar(self, gp: Gpar) -> Iterator[ResolvedGpar]:
        """临时叠加 gpar（R `set.gpar()`）：退出时恢复（M0-6 的 gTree 路径）。

        `drawGTree()` / `preDraw.gTree()` 先把 gTree 的 `gp` 设进来、再
        `pushViewport(childrenvp)`，所以子视口 push 时捕获的 `parent_gpar`
        是**叠加后**的值——`lines` / `char` 这类单位的几何按它换算（见
        `_parent_context()`）。`cex` / `alpha` / `lex` 与当前值相乘，同 `set.gpar()`。

        区别于 :meth:`push`：这里不改视口树，只改当前 gpar。

        退出时它不看当前视口在哪，直接把 gpar 换回进入前的值。R 那边恢复 gpar
        时一定已经回到 gTree 层，但**两条路径不是一回事**：`postDraw.grob()` 只
        `popgrobvp(x$vp)`，弹掉的是 gTree 自己的 `vp`；`childrenvp` 是在
        `preDraw.gTree()` 里 `pushViewport()` 之后**立刻**
        `upViewport(depth(childrenvp))` 掉的——早于画子节点，更早于 `drawGTree()`
        的 `on.exit()`。所以调用方也要**先 up/pop 回 gTree 层再退出本上下文**（块内
        push 的 `childrenvp` 在块内 pop 掉），否则会留下“当前视口还是子视口、
        gpar 已经是 gTree 外那份”的不一致状态（M0-6 的 gTree 绘制循环最容易踩到）。
        """
        if not isinstance(gp, Gpar):
            raise ViewportError(f"invalid 'gp' value: {type(gp).__name__}")
        saved = self._gpar
        self._gpar = saved.merge(gp)
        try:
            yield self._gpar
        finally:
            self._gpar = saved

    @property
    def clip_rect(self) -> tuple[float, float, float, float]:
        return self._current.clip_rect

    def depth(self) -> int:
        """当前视口深度（根为 0），同 R 的 `vpDepth()`。"""
        return self._current.depth

    def vp_path(self) -> VpPath | None:
        """当前路径；在根上返回 `None`（R 的 `current.vpPath()`）。"""
        if self._current.parent is None:
            return None
        return self._current.path

    # -- push / pop / up / down --------------------------------------------

    def push(self, *viewports: Viewport) -> Any:
        """`pushViewport(...)`：依次压栈，返回最后的节点（多个时返回元组）。"""
        if not viewports:
            raise ViewportError("must specify at least one viewport")
        pushed: list[VpNode] = []
        for spec in viewports:
            if not isinstance(spec, Viewport):
                raise ViewportError(f"only valid to push viewports, got {type(spec).__name__}")
            node = VpNode(
                spec=spec,
                parent=self._current,
                parent_gpar=self._gpar,
                gpar=self._gpar.merge(spec.gpar),
                device=self.device,
                metrics=self.metrics,
            )
            self._compute(node, is_root=False)
            # R 的 children 是 environment：同名再 push 会顶掉旧的那个。
            self._current.children[spec.name] = node
            self._current = node
            self._gpar = node.gpar
            pushed.append(node)
        return pushed[0] if len(pushed) == 1 else tuple(pushed)

    def pop(self, n: int = 1) -> None:
        """`popViewport(n)`：出栈并从树上摘掉；`n=0` 表示一直回到根。"""
        if isinstance(n, bool) or not isinstance(n, int):
            raise ViewportError("n must be an integer")
        if n < 0:
            raise ViewportError("must pop at least one viewport")
        count = self.depth() if n == 0 else n
        if count == 0:
            return
        if self.depth() < count:
            raise ViewportError("cannot pop the top-level viewport")
        for _ in range(count):
            node = self._current
            assert node.parent is not None
            node.parent.children.pop(node.name, None)
            self._gpar = node.parent_gpar
            self._current = node.parent

    def up(self, n: int = 1) -> VpPath | None:
        """`upViewport(n)`：只上移，返回上移掉的那段路径。"""
        if isinstance(n, bool) or not isinstance(n, int):
            raise ViewportError("n must be an integer")
        if n < 0:
            raise ViewportError("must navigate up at least one viewport")
        count = self.depth() if n == 0 else n
        if count == 0:
            return None
        if self.depth() < count:
            raise ViewportError("cannot pop the top-level viewport")
        start = self._current
        for _ in range(count):
            self._gpar = self._current.parent_gpar
            assert self._current.parent is not None
            self._current = self._current.parent
        names: list[str] = []
        node: VpNode | None = start
        while node is not None and node is not self._current:
            names.append(node.name)
            node = node.parent
        names.reverse()
        return VpPath(tuple(names))

    def find(
        self, target: str | VpPath | Sequence[str], *, strict: bool = False
    ) -> tuple[VpNode, int] | None:
        """从当前视口往下找：返回 `(节点, 下移层数)`，找不到给 `None`。

        `strict=False`（R 缺省）对整个相对路径做**后缀**匹配，所以
        `down("b")` 会找到任意深度的 `b`；`strict=True` 要求从当前视口的
        直接子节点起逐段完全一致。同级候选按名称排序遍历（R 的 children 是
        environment，`ls()` 排过序）。
        """
        path = VpPath.parse(target)
        found = self._search(self._current, path, 1, strict, ())
        return found

    def down(self, target: str | VpPath | Sequence[str], *, strict: bool = False) -> int:
        """`downViewport(name, strict)`：返回下移的层数。"""
        found = self.find(target, strict=strict)
        if found is None:
            raise ViewportError(f"Viewport '{VpPath.parse(target)}' was not found")
        node, depth = found
        self._current = node
        # R: grid.Call.graphics(C_setGPar, pvp$gpar)，直接换成目标视口的解析值。
        self._gpar = node.gpar
        return depth

    def seek(self, target: str | VpPath | Sequence[str], *, strict: bool = False) -> int:
        """`seekViewport(name)`：先回到根，再往下找。"""
        self.up(0)
        return self.down(target, strict=strict)

    def _search(
        self,
        node: VpNode,
        path: VpPath,
        depth: int,
        strict: bool,
        accumulated: tuple[str, ...],
    ) -> tuple[VpNode, int] | None:
        for name in sorted(node.children):
            child = node.children[name]
            trail = (*accumulated, name)
            if _path_matches(path.names, trail, strict):
                return (child, depth)
            found = self._search(child, path, depth + 1, strict, trail)
            if found is not None:
                return found
        return None

    # -- 设备变化 -----------------------------------------------------------

    def resize(self, device: Device) -> None:
        """设备尺寸变了：从头重算所有变换（R 的 `deviceChanged()` 分支）。"""
        if not isinstance(device, Device):
            raise ViewportError(f"device must be a Device, got {type(device).__name__}")
        self.device = device
        self._recompute(self._root, is_root=True)

    def _recompute(self, node: VpNode, *, is_root: bool) -> None:
        node.device = self.device
        self._compute(node, is_root=is_root)
        for child in node.children.values():
            self._recompute(child, is_root=False)

    # -- 变换 / 裁剪计算（grid/src/viewport.c） ----------------------------

    def _parent_context(self, node: VpNode) -> UnitContext:
        """父视口（或设备）的换算上下文：视口几何是在父坐标系里给的。

        尺寸与 `xscale` / `yscale` 取父视口，**gpar 的字号 / `cex` / 行高取
        `node.parent_gpar`**。R 的 `calcViewportTransform()` 就是这两段拼起来
        的（`grid/src/viewport.c:270-285`）：

        - `fillViewportContextFromViewport(parent, &parentContext)`：尺寸 + scale；
        - `gcontextFromgpar(viewportParentGPar(vp), 0, &parentgc, dd)`：gpar 取
          **本视口 push 时捕获的 `parentgpar`**，不是父视口自己的 gpar。源码
          注释写得很直白：“最近一次 gpar 设置可能来自 gTree”。

        所以 gTree 在临时 `gp` 下 push 子视口时（`preDraw.gTree()` 先
        `pushvpgp()` 再 `pushViewport(childrenvp)`），子视口里 `lines` / `char`
        这类依赖字号/cex/行高的单位必须用**那次 push 时生效的** gpar；拿父视口
        的 gpar 会静默算错尺寸。
        """
        parent = node.parent
        if parent is not None:
            gp = node.parent_gpar
            return replace(
                parent.unit_context(),
                fontsize=gp.fontsize,
                cex=gp.cex,
                lineheight=gp.lineheight,
            )
        # R: calcViewportTransform() 里父为 NULL 时 parentgc.ps = 10、lh = 1.2、cex = 1。
        return UnitContext(
            width_cm=self.device.width_cm,
            height_cm=self.device.height_cm,
            xscale=(0.0, 1.0),
            yscale=(0.0, 1.0),
            fontsize=10.0,
            cex=1.0,
            lineheight=1.2,
            metrics=self.metrics,
        )

    def _compute(self, node: VpNode, *, is_root: bool) -> None:
        spec = node.spec
        ctx = self._parent_context(node)
        try:
            x_in = float(convert_unit(spec.x, "inches", ctx=ctx, axis_from="x")[0])
            y_in = float(convert_unit(spec.y, "inches", ctx=ctx, axis_from="y")[0])
            width_in = float(
                convert_unit(spec.width, "inches", ctx=ctx, axis_from="x", type_from="dimension")[0]
            )
            height_in = float(
                convert_unit(spec.height, "inches", ctx=ctx, axis_from="y", type_from="dimension")[
                    0
                ]
            )
        except UnitError as exc:
            raise ViewportError(str(exc)) from exc
        if not all(math.isfinite(value) for value in (x_in, y_in, width_in, height_in)):
            raise ViewportError("non-finite location and/or size for viewport")

        hjust, vjust = spec.just
        # R `justification()`：hadj = -width * hjust，所以旋转绕“对齐点”发生。
        justification = Affine.translation(-width_in * hjust, -height_in * vjust)
        rotation = Affine.rotation(spec.angle) if spec.angle != 0 else IDENTITY
        location = Affine.translation(x_in, y_in)
        parent_transform = node.parent.transform if node.parent is not None else IDENTITY
        transform = _compose(justification, rotation, location, parent_transform)
        total_rotation = spec.angle + (node.parent.rotation if node.parent is not None else 0.0)

        clip_rect = self._clip_rect(
            node,
            is_root=is_root,
            transform=transform,
            total_rotation=total_rotation,
            width_in=width_in,
            height_in=height_in,
        )
        node._computed = _Computed(
            width_cm=width_in * CM_PER_INCH,
            height_cm=height_in * CM_PER_INCH,
            transform=transform,
            rotation=total_rotation,
            clip_rect=clip_rect,
        )

    def _clip_rect(
        self,
        node: VpNode,
        *,
        is_root: bool,
        transform: Affine,
        total_rotation: float,
        width_in: float,
        height_in: float,
    ) -> tuple[float, float, float, float]:
        """R `doSetViewport()` 的裁剪分支。

        - `off`：整个设备略微放宽（`-0.5..1.5` 倍），避免边缘效应；
        - `inherit`：父视口的裁剪框；
        - `on`：本视口 `0..1 npc` 的设备外包框；但旋转不是 0/90/270/360 时
          R 只警告并退化成继承父裁剪框（180° 也在退化之列——角点顺序会翻转）。
        """
        device = self.device
        expanded = (
            -0.5 * device.width_in,
            -0.5 * device.height_in,
            1.5 * device.width_in,
            1.5 * device.height_in,
        )
        parent_rect = node.parent.clip_rect if node.parent is not None else expanded
        clip = node.spec.clip
        if is_root:
            if clip is Clip.OFF:
                return expanded
            if clip is Clip.INHERIT:  # pragma: no cover - 根视口由 _root_viewport 固定
                return expanded
            # R 的 top-level 特例：视口坐标取 -0.5..1.5 npc，等价于设备外包框。
            return expanded
        if clip is Clip.OFF:
            return expanded
        if clip is Clip.INHERIT:
            return parent_rect
        if total_rotation not in (0.0, 90.0, 270.0, 360.0):
            warnings.warn(
                "cannot clip to rotated viewport",
                RotatedClipWarning,
                stacklevel=2,
            )
            return parent_rect
        x0, y0 = transform.map(0.0, 0.0)
        x1, y1 = transform.map(width_in, height_in)
        return (x0, y0, x1, y1)

    # -- 遍历 ---------------------------------------------------------------

    def nodes(self) -> Iterator[VpNode]:
        """深度优先遍历整棵树（根在最前）。"""
        yield self._root
        yield from self._root.descendants()


def _path_matches(pattern: tuple[str, ...], trail: tuple[str, ...], strict: bool) -> bool:
    """相对路径匹配：严格模式要求完全相同，非严格模式是后缀匹配。

    R 的实现是把路径当正则去 `grepl()`（所以名字里的 `.` 之类会被当元字符），
    这里按**段**精确比较，见 `docs/notes/viewport.md`。
    """
    if strict:
        return trail == pattern
    if len(pattern) > len(trail):
        return False
    return trail[len(trail) - len(pattern) :] == pattern


def device_loc(
    tree: ViewportTree,
    x: Any,
    y: Any,
    *,
    viewport_node: VpNode | None = None,
) -> np.ndarray[Any, Any]:
    """便捷入口：把视口内坐标换算成设备英寸（默认在当前视口里）。"""
    node = viewport_node if viewport_node is not None else tree.current
    return node.device_points(x, y)


def _iter_units(values: Iterable[Any]) -> Iterator[Unit]:  # pragma: no cover - 预留
    yield from values

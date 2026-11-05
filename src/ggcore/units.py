"""与 R `grid::unit` 对等的单位系统（SIL-592 / M0-3）。

模型照抄 grid：一个 `Unit` 是**单位元素的有序列表**（R 的 `unit` 对象），每个
元素是 `(amount, kind, data)`：

- `kind` 是 `npc` / `native` / `mm` / `points` / `lines` / `strwidth` / `null`
  这类单位名；
- `sum` / `min` / `max` 是复合元素，`data` 里放子元素（R 的 `unit.arithmetic`）；
- `data` 为字符串的是 `strwidth` / `strheight`。

因此 `unit(1, "npc") + unit(2, "mm")` 保留两个单位，不折算成绝对值：
`sum(1npc, 2mm)`。求值一律先换算成英寸、再换算到目标单位，与 R
`src/library/grid/src/unit.c` 的 `transform()` / `transformFromINCHES()` 逐条对应。

非绝对单位（`npc` / `native` / `snpc` / `lines` / `char` / `strwidth` /
`strheight` / `null`）需要一个 :class:`UnitContext`：视口尺寸、坐标范围、字号、
行高和度量提供者。度量不硬编码字体——M0-7 的真实实现从 :class:`Metrics`
协议注入。

口径与 R 的差异（含刻意不复制的行为）记在 `docs/notes/units.md`。
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np

__all__ = [
    "BIGPOINTS_PER_INCH",
    "CM_PER_INCH",
    "POINTS_PER_INCH",
    "FixedMetrics",
    "Unit",
    "UnitContext",
    "UnitElement",
    "UnitError",
    "convert_height",
    "convert_unit",
    "convert_width",
    "convert_x",
    "convert_y",
    "is_pure_null",
    "is_simple_unit",
    "is_unit",
    "null_value",
    "simple_unit_kind",
    "str_height",
    "str_width",
    "unit",
    "unit_c",
    "unit_max",
    "unit_min",
    "unit_pmax",
    "unit_pmin",
    "unit_psum",
    "unit_sum",
    "unit_type",
]

CM_PER_INCH = 2.54
"""R：2.54 cm per inch（`unit.c` 里到处都是这个常数）。"""

POINTS_PER_INCH = 72.27
"""R 的 `points` / `pt` 是 TeX pt（1/72.27 in），不是 PostScript 的 1/72。"""

BIGPOINTS_PER_INCH = 72.0
"""R 的 `bigpts`（1/72 in）。CSS 的 px→pt 换算用的是这个口径。"""

BULK_CONVERT_THRESHOLD = 256
"""`convert_unit()` 走批量路径的最小长度（单 kind 的仿射换算）。

小于它的单位向量保持逐元素路径：数值上与 R 的标量实现逐位相同，改动只在
大批量几何上才有意义（见 `docs/notes/performance.md`）。
"""


class UnitError(ValueError):
    """单位构造或换算失败；消息尽量贴近 R 的 conditionMessage。"""


_SIMPLE_KINDS = frozenset(
    {
        "npc",
        "cm",
        "inches",
        "lines",
        "native",
        "null",
        "snpc",
        "mm",
        "points",
        "picas",
        "bigpts",
        "dida",
        "cicero",
        "scaledpts",
        "strwidth",
        "strheight",
        "char",
    }
)
_COMPOUND_KINDS = frozenset({"sum", "min", "max"})
_STRING_KINDS = frozenset({"strwidth", "strheight"})

# R 的 `unit.c` UnitTable 里的伪名（`pt` 指 points，不是 bigpts）。
_ALIASES = {
    "centimetre": "cm",
    "centimetres": "cm",
    "centimeter": "cm",
    "centimeters": "cm",
    "in": "inches",
    "inch": "inches",
    "line": "lines",
    "millimetre": "mm",
    "millimetres": "mm",
    "millimeter": "mm",
    "millimeters": "mm",
    "point": "points",
    "pt": "points",
}


def _canonical_kind(kind: str) -> str:
    name = _ALIASES.get(kind, kind)
    if name not in _SIMPLE_KINDS:
        raise UnitError(f"Invalid unit: {kind!r}")
    return name


@dataclass(frozen=True, slots=True)
class UnitElement:
    """一个单位元素：R 的 `(amount, data, unit_id)` 三元组。"""

    amount: float
    kind: str
    data: str | tuple[UnitElement, ...] | None = None

    @property
    def children(self) -> tuple[UnitElement, ...]:
        """复合元素（sum/min/max）的子元素；简单元素返回空元组。"""
        if isinstance(self.data, tuple):
            return self.data
        return ()

    def to_structure(self) -> dict[str, object]:
        node: dict[str, object] = {"kind": self.kind, "amount": self.amount}
        if self.kind in _COMPOUND_KINDS:
            node["children"] = [child.to_structure() for child in self.children]
        elif isinstance(self.data, str):
            node["text"] = self.data
        return node

    def __str__(self) -> str:
        if self.kind in _COMPOUND_KINDS:
            inner = ", ".join(str(child) for child in self.children)
            prefix = "" if self.amount == 1 else f"{_format_number(self.amount)}*"
            return f"{prefix}{self.kind}({inner})"
        return f"{_format_number(self.amount)}{self.kind}"


def _format_number(value: float) -> str:
    if value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.15g}"


@dataclass(frozen=True, slots=True)
class Unit:
    """单位向量（R 的 `unit` 对象）：元素有序，长度即 R 的 `length()`。"""

    elements: tuple[UnitElement, ...] = ()

    def __len__(self) -> int:
        return len(self.elements)

    def __iter__(self) -> Iterator[UnitElement]:
        return iter(self.elements)

    def __getitem__(self, index: int | slice) -> Unit | UnitElement:
        if isinstance(index, slice):
            return Unit(self.elements[index])
        return self.elements[index]

    def __add__(self, other: Unit) -> Unit:
        return _add_units(self, _expect_unit(other, "+"))

    def __sub__(self, other: Unit) -> Unit:
        return _add_units(self, -_expect_unit(other, "-"))

    def __mul__(self, scalar: float | Sequence[float]) -> Unit:
        return _scale_units(self, scalar)

    def __rmul__(self, scalar: float | Sequence[float]) -> Unit:
        return _scale_units(self, scalar)

    def __truediv__(self, scalar: float | Sequence[float]) -> Unit:
        # R 的 Ops.unit：先取 1/x 再乘（浮点结果与直接除不完全相同）。
        return _scale_units(self, 1.0 / np.asarray(scalar, dtype=float))

    def __neg__(self) -> Unit:
        return _scale_units(self, -1.0)

    def to_structure(self) -> list[dict[str, object]]:
        """结构快照（供与 R 侧逐元素对拍）。"""
        return [element.to_structure() for element in self.elements]

    def __str__(self) -> str:
        if not self.elements:
            return "<empty unit>"
        return " ".join(str(element) for element in self.elements)

    __repr__ = __str__


def _expect_unit(value: object, operator: str) -> Unit:
    if not isinstance(value, Unit):
        raise UnitError(f"object is not coercible to a unit (operator {operator})")
    return value


# ---------------------------------------------------------------------------
# 构造
# ---------------------------------------------------------------------------


def unit(
    amount: float | Sequence[float],
    kind: str | Sequence[str],
    data: object = None,
) -> Unit:
    """`unit(x, units, data)`：把标量/向量摊成元素列表（R 的 `unit()`）。

    长度按 R `constructUnits()` 的规则**按模回收**到
    `max(len(amount), len(kind))`，两个方向都成立：
    `unit(1, ["cm", "mm"])` 是 `1cm 1mm`，`unit([1, 2, 3], ["cm", "mm"])` 是
    `1cm 2mm 3cm`。

    `data` 是 `strwidth` / `strheight` 的文本：长度 1 时复用，更长时取前 N 个
    （R `validData()` 只拒绝比单位向量短的）。一次调用里混合字符串单位与普通
    单位不在支持范围内（见 `docs/notes/units.md`）。
    """
    amounts = np.asarray(amount, dtype=float)
    if amounts.ndim == 0:
        amounts = amounts.reshape(1)
    if amounts.ndim != 1 or amounts.size == 0:
        raise UnitError("'x' and 'units' must have length > 0")

    declared = (
        [_canonical_kind(kind)]
        if isinstance(kind, str)
        else [_canonical_kind(item) for item in kind]
    )
    if not declared:
        raise UnitError("'x' and 'units' must have length > 0")
    count = max(amounts.size, len(declared))

    # 单 kind + 单长度（几何层最常见的形状：`unit(x, "native")` 一次 10 万个点）
    # 走摊平路径：`amounts.tolist()` 一次换完，省掉逐元素 `amounts[i % n]` 的
    # numpy 标量索引。回收语义与下面那条一样，只是没有第二个 kind 要循环。
    if len(declared) == 1 and amounts.size == count:
        name = declared[0]
        if name in _STRING_KINDS:
            if data is None:
                raise UnitError("no string supplied for 'strwidth/height' unit")
            texts = [data] if isinstance(data, str) else list(data)  # type: ignore[arg-type]
            if not texts or (len(texts) != 1 and len(texts) < count):
                raise UnitError(
                    "data must be either NULL, have length 1, "
                    "or match the length of the final unit vector"
                )
            if not all(isinstance(text, str) for text in texts):
                raise UnitError("no string supplied for 'strwidth/height' unit")
            values = amounts.tolist()
            return Unit(
                tuple(
                    UnitElement(value, name, texts[index % len(texts)])
                    for index, value in enumerate(values)
                )
            )
        if data is not None:
            raise UnitError(f"unit {name!r} does not take data")
        return Unit(tuple(UnitElement(value, name) for value in amounts.tolist()))

    names = [declared[index % len(declared)] for index in range(count)]
    values = [float(amounts[index % amounts.size]) for index in range(count)]

    string_kinds = [name in _STRING_KINDS for name in names]
    if any(string_kinds):
        if not all(string_kinds):
            raise UnitError("mixed string/plain units in one unit() call are unsupported")
        if data is None:
            raise UnitError("no string supplied for 'strwidth/height' unit")
        texts = [data] if isinstance(data, str) else list(data)  # type: ignore[arg-type]
        if not texts or (len(texts) != 1 and len(texts) < count):
            raise UnitError(
                "data must be either NULL, have length 1, "
                "or match the length of the final unit vector"
            )
        if not all(isinstance(text, str) for text in texts):
            raise UnitError("no string supplied for 'strwidth/height' unit")
        return Unit(
            tuple(
                UnitElement(value, name, texts[index % len(texts)])
                for index, (value, name) in enumerate(zip(values, names, strict=True))
            )
        )

    if data is not None:
        raise UnitError(f"unit {names[0]!r} does not take data")
    return Unit(tuple(UnitElement(value, name) for value, name in zip(values, names, strict=True)))


def unit_c(*units: Unit) -> Unit:
    """`unit.c(...)`：拼接并摊平元素列表（不折算单位）。

    R 4.5.3 里 `unit.c()` 无参数会报错；gg4py 允许空列表（gtable 的空格子），
    见 `docs/notes/units.md`。
    """
    elements: list[UnitElement] = []
    for item in units:
        if not isinstance(item, Unit):
            raise UnitError("object is not coercible to a unit")
        elements.extend(item.elements)
    return Unit(tuple(elements))


def str_width(text: str | Sequence[str]) -> Unit:
    """`stringWidth(text)`：宽度单位（求值需要 `UnitContext.metrics`）。"""
    texts = [text] if isinstance(text, str) else list(text)
    return unit([1.0] * len(texts), "strwidth", data=texts)


def str_height(text: str | Sequence[str]) -> Unit:
    """`stringHeight(text)`。"""
    texts = [text] if isinstance(text, str) else list(text)
    return unit([1.0] * len(texts), "strheight", data=texts)


# ---------------------------------------------------------------------------
# 算术
# ---------------------------------------------------------------------------


def _add_elements(left: UnitElement, right: UnitElement) -> UnitElement:
    if left.kind == right.kind and left.data == right.data:
        return UnitElement(left.amount + right.amount, left.kind, left.data)
    children: list[UnitElement] = []
    for element in (left, right):
        if element.kind == "sum":
            children.extend(_scaled_children(element))
        else:
            children.append(element)
    return UnitElement(1.0, "sum", tuple(children))


def _scaled_children(element: UnitElement) -> list[UnitElement]:
    """把 sum 的子元素按外层 amount 展开（R `addUnit` 的 flatten 分支）。"""
    return [
        UnitElement(child.amount * element.amount, child.kind, child.data)
        for child in element.children
    ]


def _add_units(left: Unit, right: Unit) -> Unit:
    # R 无法构造空单位；gg4py 允许，空列表在加法里按单位元处理。
    if len(left) == 0:
        return right
    if len(right) == 0:
        return left
    count = max(len(left), len(right))
    return Unit(
        tuple(
            _add_elements(
                left.elements[index % len(left)],
                right.elements[index % len(right)],
            )
            for index in range(count)
        )
    )


def _scale_units(target: Unit, scalar: float | Sequence[float] | np.ndarray) -> Unit:
    if isinstance(scalar, Unit):
        raise UnitError("only one operand may be a unit")
    if len(target) == 0:
        return Unit()
    values = np.asarray(scalar, dtype=float)
    if values.ndim == 0:
        values = values.reshape(1)
    if values.ndim != 1 or values.size == 0:
        raise UnitError("non-unit operand must be numeric")
    count = max(len(target), values.size)
    return Unit(
        tuple(
            UnitElement(
                target.elements[index % len(target)].amount * float(values[index % values.size]),
                target.elements[index % len(target)].kind,
                target.elements[index % len(target)].data,
            )
            for index in range(count)
        )
    )


def _identical_simple(units: Sequence[Unit]) -> str | None:
    """R `identicalUnits()`：全部是简单单位且同一单位名时返回该名字。

    R 的 simpleUnit 是「没有 data 的数值向量」：带字符串的 `strwidth` /
    `strheight` 不算，与 `identicalUnits()` 返回 NULL 的行为一致。
    """
    if not units or any(len(item) == 0 for item in units):
        return None
    first = units[0].elements[0]
    if first.kind in _COMPOUND_KINDS:
        return None
    for item in units:
        for element in item.elements:
            if element.data is not None:
                return None
            if element.kind != first.kind:
                return None
    return first.kind


def _p_summary(units: Sequence[Unit], op: str) -> Unit:
    """`unit.pmax` / `unit.pmin` / `unit.psum`：逐元素（R `summaryUnits`）。"""
    kept = [item for item in units if len(item) > 0]
    if not kept:
        return Unit()
    count = max(len(item) for item in kept)
    elements: list[UnitElement] = []
    for index in range(count):
        group = [item.elements[index % len(item)] for item in kept]
        elements.append(_combine_group(group, op))
    return Unit(tuple(elements))


def _combine_group(group: Sequence[UnitElement], op: str) -> UnitElement:
    first = group[0]
    if all(element.kind == first.kind and element.data == first.data for element in group):
        amounts = [element.amount for element in group]
        reduced = {"sum": sum, "min": min, "max": max}[op](amounts)
        return UnitElement(float(reduced), first.kind, first.data)
    children: list[UnitElement] = []
    for element in group:
        if element.kind == op:
            children.extend(_scaled_children(element))
        else:
            children.append(element)
    return UnitElement(1.0, op, tuple(children))


def unit_pmax(*units: Unit) -> Unit:
    """`unit.pmax(...)`：逐元素取最大，混合单位保留为 `max(...)` 复合元素。"""
    return _p_summary([_expect_unit(item, "pmax") for item in units], "max")


def unit_pmin(*units: Unit) -> Unit:
    """`unit.pmin(...)`。"""
    return _p_summary([_expect_unit(item, "pmin") for item in units], "min")


def unit_psum(*units: Unit) -> Unit:
    """`unit.psum(...)`：逐元素求和，混合单位保留为 `sum(...)`。"""
    return _p_summary([_expect_unit(item, "psum") for item in units], "sum")


def _summary(units: Sequence[Unit], op: str) -> Unit:
    """R 的 `sum(unit, ...)` / `min(...)` / `max(...)`：塌成**一个**元素。"""
    kept = list(units)
    if not kept:
        raise UnitError(f"{op}() needs at least one unit")
    kind = _identical_simple(kept)
    if kind is not None:
        amounts = [element.amount for item in kept for element in item.elements]
        reduced = {"sum": sum, "min": min, "max": max}[op](amounts)
        return Unit((UnitElement(float(reduced), kind),))

    # R `Summary.unit` 在 nMatches != 0 时写成 c(x[-matchUnits], matchData)：
    # 非匹配单位按原序在前，被摊平的子项在后。普通量级下两种顺序等价，但大数
    # 相消时求和顺序决定结果（见 docs/notes/units.md 的浮点一节），所以照抄。
    flat = [element for item in kept for element in item.elements]
    children = [element for element in flat if element.kind != op]
    children.extend(
        child for element in flat if element.kind == op for child in _scaled_children(element)
    )
    return Unit((UnitElement(1.0, op, tuple(children)),))


def unit_sum(*units: Unit) -> Unit:
    """`sum(...)` 的单位版本（结果长度 1）。"""
    return _summary([_expect_unit(item, "sum") for item in units], "sum")


def unit_min(*units: Unit) -> Unit:
    """`min(...)` 的单位版本（结果长度 1）。"""
    return _summary([_expect_unit(item, "min") for item in units], "min")


def unit_max(*units: Unit) -> Unit:
    """`max(...)` 的单位版本（结果长度 1）。"""
    return _summary([_expect_unit(item, "max") for item in units], "max")


# ---------------------------------------------------------------------------
# 结构判定
# ---------------------------------------------------------------------------


def is_unit(value: object) -> bool:
    """`is.unit()`。"""
    return isinstance(value, Unit)


def simple_unit_kind(target: Unit) -> str | None:
    """老版 grid `simpleUnit()`：简单单位返回单位名，否则 None。

    带 data 的单位（`strwidth` / `strheight`）不是 R 的 simpleUnit，这里也不
    算简单单位。
    """
    if not isinstance(target, Unit) or len(target) == 0:
        return None
    first = target.elements[0]
    if first.kind in _COMPOUND_KINDS:
        return None
    for element in target:
        if element.data is not None or element.kind != first.kind:
            return None
    return first.kind


def is_simple_unit(target: Unit) -> bool:
    """R 4.5 的 `grid:::is.simpleUnit()`。"""
    return simple_unit_kind(target) is not None


def unit_type(target: Unit) -> list[str]:
    """`unitType()`：顶层单位名（复合元素给 `sum`/`min`/`max`）。"""
    if not isinstance(target, Unit):
        raise UnitError("object is not coercible to a unit")
    return [element.kind for element in target.elements]


def is_pure_null(target: Unit, index: int) -> bool:
    """R `pureNullUnit(unit, index)`：第 `index` 个元素是不是纯 `null`。

    `null` 与其他单位混在一个元素里（`unit(1, "null") + unit(2, "cm")` 的
    `sum(1null, 2cm)`）**不是**纯 null：R 的 layout 对该列/行判 0 权重。
    """
    return _is_pure_null_element(_element_at(target, index))


def _is_pure_null_element(element: UnitElement) -> bool:
    if element.kind in _COMPOUND_KINDS:
        return all(_is_pure_null_element(child) for child in element.children)
    return element.kind == "null"


def null_value(target: Unit, index: int) -> float:
    """R `pureNullUnitValue(unit, index)`：布局阶段第 `index` 个元素的 null 权重。

    gtable 逐列/逐行取权重分配剩余空间：`[null_value(widths, i) for i in
    range(len(widths))]`。只有纯 null 元素（:func:`is_pure_null`）才有权重，
    与 `null` 混合的复合元素返回 0——这正是 R layout 先做 `pureNullUnit` 门、
    再过 `pureNullUnitValue` 的效果。`null` 还是 0 的元素（`unit(0, "null")`）
    权重也是 0，但 `is_pure_null` 仍为真，两者不是同一个判断。
    """
    element = _element_at(target, index)
    if not _is_pure_null_element(element):
        return 0.0
    return _null_weight(element)


def _null_weight(element: UnitElement) -> float:
    """R `pureNullUnitValue()` 的递归体；只在纯 null 元素上调用。"""
    if element.kind == "sum":
        return element.amount * sum(_null_weight(child) for child in element.children)
    if element.kind == "min":
        # R 用 DBL_MAX 起步；这里与 _to_inches() 一致用 +inf（空的 min 元素）。
        return element.amount * min(
            (_null_weight(child) for child in element.children), default=math.inf
        )
    if element.kind == "max":
        return element.amount * max(
            (_null_weight(child) for child in element.children), default=-math.inf
        )
    return element.amount


def _element_at(target: Unit, index: int) -> UnitElement:
    if not isinstance(target, Unit):
        raise UnitError("object is not coercible to a unit")
    return target.elements[index]


# ---------------------------------------------------------------------------
# 求值上下文
# ---------------------------------------------------------------------------


@runtime_checkable
class Metrics(Protocol):
    """字符串度量注入点（M0-7 的真实实现在包外）。返回英寸。

    `font` 是 IR 的字体 key（`族` 或 `族:bold-italic`）：字重/斜体会改变推进，
    宽度必须按实际字面量（`docs/notes/metrics-ledger.md`）。实现不需要区分字面时
    可以忽略它。
    """

    def strwidth(self, text: str, *, fontsize: float, cex: float, font: str = "sans") -> float: ...

    def strheight(self, text: str, *, fontsize: float, cex: float, font: str = "sans") -> float: ...


@dataclass(frozen=True, slots=True)
class FixedMetrics:
    """固定度量表：宽度/高度按英寸给，原样返回（用于对拍与占位）。"""

    widths: dict[str, float]
    heights: dict[str, float]

    def strwidth(self, text: str, *, fontsize: float, cex: float, font: str = "sans") -> float:
        return float(self.widths[text])

    def strheight(self, text: str, *, fontsize: float, cex: float, font: str = "sans") -> float:
        return float(self.heights[text])


@dataclass(frozen=True, slots=True)
class UnitContext:
    """R 的 viewport + gpar + 设备状态里换算需要的那部分。

    `width_cm` / `height_cm` 是当前视口的尺寸；`xscale` / `yscale` 是 native
    坐标范围；`fontsize` / `cex` / `lineheight` 对应 `gc->ps` / `cex` /
    `lineheight`。布局阶段的 null 权重用 :func:`null_value`（逐元素），不走换算。
    """

    width_cm: float = 1.0
    height_cm: float = 1.0
    xscale: tuple[float, float] = (0.0, 1.0)
    yscale: tuple[float, float] = (0.0, 1.0)
    fontsize: float = 12.0
    cex: float = 1.0
    lineheight: float = 1.2
    metrics: Metrics | None = None

    def __post_init__(self) -> None:
        for name, (low, high) in (("xscale", self.xscale), ("yscale", self.yscale)):
            if low == high:
                raise UnitError(f"{name} limits must differ (grid forbids equal limits)")


_AXIS_CODES = {
    ("x", "location"): 0,
    ("y", "location"): 1,
    ("x", "dimension"): 2,
    ("y", "dimension"): 3,
}


def _axis_code(axis: str, measure: str) -> int:
    try:
        return _AXIS_CODES[(axis, measure)]
    except KeyError:
        raise UnitError(f"invalid axis/type: {axis}/{measure}") from None


def _axis_codes(code: int) -> tuple[str, str]:
    for (axis, measure), value in _AXIS_CODES.items():
        if value == code:
            return axis, measure
    raise UnitError(f"invalid axis code: {code}")


def _this_other(ctx: UnitContext, axis: str) -> tuple[float, float]:
    if axis == "x":
        return ctx.width_cm, ctx.height_cm
    return ctx.height_cm, ctx.width_cm


def _scales(ctx: UnitContext, axis: str) -> tuple[float, float]:
    return ctx.xscale if axis == "x" else ctx.yscale


def _metric_value(element: UnitElement, ctx: UnitContext, *, width: bool) -> float:
    if ctx.metrics is None:
        raise UnitError(f"{element.kind} needs a metric provider in UnitContext")
    text = element.data if isinstance(element.data, str) else ""
    measure = ctx.metrics.strwidth if width else ctx.metrics.strheight
    return measure(text, fontsize=ctx.fontsize, cex=ctx.cex)


def _to_inches(
    element: UnitElement,
    *,
    axis: str,
    measure: str,
    ctx: UnitContext,
    mode: str = "plain",
) -> float:
    """对应 R `transform()` / `transformLocation()` / `transformDimension()`。"""
    amount = element.amount
    kind = element.kind
    this_cm, other_cm = _this_other(ctx, axis)
    scale_min, scale_max = _scales(ctx, axis)

    if kind == "sum":
        total = 0.0
        for child in element.children:
            total += _to_inches(child, axis=axis, measure=measure, ctx=ctx, mode="sum")
        return amount * total
    if kind == "min":
        # 空复合元素给 +inf（R 用 DBL_MAX 起步）；非空时结果与 R 一致。
        result = math.inf
        for child in element.children:
            result = min(result, _to_inches(child, axis=axis, measure=measure, ctx=ctx, mode="min"))
        return amount * result
    if kind == "max":
        # 空复合元素给 -inf（R 用 DBL_MIN 起步）；非空时结果与 R 一致。
        result = -math.inf
        for child in element.children:
            result = max(result, _to_inches(child, axis=axis, measure=measure, ctx=ctx, mode="max"))
        return amount * result

    if kind == "npc":
        return amount * this_cm / CM_PER_INCH
    if kind == "cm":
        return amount / CM_PER_INCH
    if kind == "inches":
        return amount
    if kind == "char":
        return amount * ctx.fontsize * ctx.cex / BIGPOINTS_PER_INCH
    if kind == "lines":
        return amount * ctx.fontsize * ctx.cex * ctx.lineheight / BIGPOINTS_PER_INCH
    if kind == "snpc":
        return amount * min(this_cm, other_cm) / CM_PER_INCH
    if kind == "mm":
        return amount / 10 / CM_PER_INCH
    if kind == "points":
        return amount / POINTS_PER_INCH
    if kind == "picas":
        return amount * 12 / POINTS_PER_INCH
    if kind == "bigpts":
        return amount / BIGPOINTS_PER_INCH
    if kind == "dida":
        return amount / 1157 * 1238 / POINTS_PER_INCH
    if kind == "cicero":
        return amount * 12 / 1157 * 1238 / POINTS_PER_INCH
    if kind == "scaledpts":
        return amount / 65536 / POINTS_PER_INCH
    if kind == "strwidth":
        return amount * _metric_value(element, ctx, width=True)
    if kind == "strheight":
        return amount * _metric_value(element, ctx, width=False)
    if kind == "native":
        if measure == "location":
            return ((amount - scale_min) / (scale_max - scale_min)) * this_cm / CM_PER_INCH
        return (amount / (scale_max - scale_min)) * this_cm / CM_PER_INCH
    if kind == "null":
        # R 的 evaluateNullUnit()：取 min 时 null 视作整个视口宽/高（永远不赢）。
        return this_cm if mode == "min" else 0.0
    raise UnitError(f"invalid unit or unit not yet implemented: {kind}")


def _from_inches(value: float, kind: str, *, axis: str, measure: str, ctx: UnitContext) -> float:
    """对应 R `transformFromINCHES()` / `transformXYFromINCHES()`。"""
    this_cm, _ = _this_other(ctx, axis)
    scale_min, scale_max = _scales(ctx, axis)
    zero_dim = this_cm < 1e-6

    if kind == "npc":
        if zero_dim:
            if value != 0:
                raise UnitError("Viewport has zero dimension(s)")
            return value
        return value / (this_cm / CM_PER_INCH)
    if kind == "cm":
        return value * CM_PER_INCH
    if kind == "inches":
        return value
    if kind == "char":
        return (value * BIGPOINTS_PER_INCH) / (ctx.fontsize * ctx.cex)
    if kind == "lines":
        return (value * BIGPOINTS_PER_INCH) / (ctx.fontsize * ctx.cex * ctx.lineheight)
    if kind == "mm":
        return value * CM_PER_INCH * 10
    if kind == "points":
        return value * POINTS_PER_INCH
    if kind == "picas":
        return value / 12 * POINTS_PER_INCH
    if kind == "bigpts":
        return value * BIGPOINTS_PER_INCH
    if kind == "dida":
        return value / 1238 * 1157 * POINTS_PER_INCH
    if kind == "cicero":
        return value / 1238 * 1157 * POINTS_PER_INCH / 12
    if kind == "scaledpts":
        return value * 65536 * POINTS_PER_INCH
    if kind == "native":
        if zero_dim:
            if value != 0:
                raise UnitError("Viewport has zero dimension(s)")
            return value
        if measure == "location":
            return scale_min + (value / (this_cm / CM_PER_INCH)) * (scale_max - scale_min)
        return (value / (this_cm / CM_PER_INCH)) * (scale_max - scale_min)
    raise UnitError(f"invalid unit or unit not yet implemented: cannot convert to {kind}")


_RELATIVE_KINDS = frozenset({"npc", "native"})
# R L_convert() 的 relConvert：同一轴，或同轴的 location<->dimension
_REL_CODES = frozenset({(0, 0), (1, 1), (2, 2), (3, 3), (0, 2), (2, 0), (1, 3), (3, 1)})


def _rel_npc(value: float, kind: str, measure: str, scale_min: float, scale_max: float) -> float:
    if kind == "npc":
        return value
    if measure == "location":
        return (value - scale_min) / (scale_max - scale_min)
    return value / (scale_max - scale_min)


def _rel_from_npc(
    value: float, kind: str, measure: str, scale_min: float, scale_max: float
) -> float:
    if kind == "npc":
        return value
    if measure == "location":
        return scale_min + value * (scale_max - scale_min)
    return value * (scale_max - scale_min)


def _convert_element(
    element: UnitElement, from_code: int, to_code: int, to_kind: str, ctx: UnitContext
) -> float:
    axis_from, measure_from = _axis_codes(from_code)
    axis_to, measure_to = _axis_codes(to_code)

    this_cm, _ = _this_other(ctx, axis_from)
    relative = (
        element.kind in _RELATIVE_KINDS
        and to_kind in _RELATIVE_KINDS
        and (from_code, to_code) in _REL_CODES
    )
    if relative and this_cm < 1e-6:
        scale_from = _scales(ctx, axis_from)
        intermediate = _rel_npc(element.amount, element.kind, measure_from, *scale_from)
        scale_to = _scales(ctx, axis_to)
        return _rel_from_npc(intermediate, to_kind, measure_to, *scale_to)

    inches = _to_inches(element, axis=axis_from, measure=measure_from, ctx=ctx)
    return _from_inches(inches, to_kind, axis=axis_to, measure=measure_to, ctx=ctx)


def _convert_bulk(
    target: Unit,
    from_code: int,
    to_code: int,
    to_kind: str,
    ctx: UnitContext,
    *,
    axis_from: str,
) -> np.ndarray | None:
    """单 kind 的大数组批量换算；不是这种形状就返回 `None`（调用方走逐元素）。

    换算对 `amount` 是**仿射**的（`npc` / `native` / `cm` / `bigpts` / `lines` /
    `char` … 都是「乘一个系数再加/减一个常数」），所以截距与斜率各量一次就够，
    剩下的交给 numpy。`sum` / `min` / `max` 复合单位与 `strwidth` / `strheight`
    （逐元素文本不同）不是仿射形状，留在标量路径上。

    阈值刻意设得比「大数组」低一档：10 万点的 `geom_point` 每次要换算 20 万
    个元素，逐元素 Python 调用是这里最大的单项成本（`docs/notes/performance.md`）。
    """
    elements = target.elements
    if len(elements) < BULK_CONVERT_THRESHOLD:
        return None
    kind = elements[0].kind
    if kind in _COMPOUND_KINDS or kind in _STRING_KINDS:
        return None
    for element in elements:
        if element.kind != kind:
            return None
    this_cm, _ = _this_other(ctx, axis_from)
    relative = (
        kind in _RELATIVE_KINDS
        and to_kind in _RELATIVE_KINDS
        and (from_code, to_code) in _REL_CODES
    )
    if relative and this_cm < 1e-6:
        return None
    try:
        base = _convert_element(UnitElement(0.0, kind), from_code, to_code, to_kind, ctx)
        step = _convert_element(UnitElement(1.0, kind), from_code, to_code, to_kind, ctx) - base
    except UnitError:
        return None
    amounts = np.fromiter(
        (element.amount for element in elements), dtype=np.float64, count=len(elements)
    )
    return base + step * amounts


def convert_unit(
    target: Unit,
    to: str | Sequence[str],
    *,
    ctx: UnitContext,
    axis_from: str = "x",
    type_from: str = "location",
    axis_to: str | None = None,
    type_to: str | None = None,
    value_only: bool = True,
) -> np.ndarray | Unit:
    """`convertUnit()`：把单位换算到 `to`（逐元素，`to` 可循环）。

    返回 float64 数组（`value_only=True`）或同长度的 `Unit`。
    """
    if not isinstance(target, Unit):
        raise UnitError("object is not coercible to a unit")
    axis_to = axis_from if axis_to is None else axis_to
    type_to = type_from if type_to is None else type_to
    from_code = _axis_code(axis_from, type_from)
    to_code = _axis_code(axis_to, type_to)

    names = [_canonical_kind(to)] if isinstance(to, str) else [_canonical_kind(item) for item in to]
    if not names:
        raise UnitError("'units' must be of length > 0")
    if not target.elements:
        return np.empty(0, dtype=np.float64) if value_only else Unit()

    values: np.ndarray | None = None
    if len(names) == 1:
        values = _convert_bulk(
            target,
            from_code,
            to_code,
            names[0],
            ctx,
            axis_from=axis_from,
        )
    if values is None:
        values = np.empty(len(target), dtype=np.float64)
        for index, element in enumerate(target.elements):
            to_kind = names[index % len(names)]
            values[index] = _convert_element(element, from_code, to_code, to_kind, ctx)
    if not value_only:
        out_names: str | list[str] = names[0]
        if len(names) > 1:
            out_names = [names[index % len(names)] for index in range(len(values))]
        return unit(values, out_names)
    return values


def convert_x(target: Unit, to: str, *, ctx: UnitContext, value_only: bool = True):
    """`convertX()`。"""
    return convert_unit(
        target,
        to,
        ctx=ctx,
        axis_from="x",
        type_from="location",
        axis_to="x",
        type_to="location",
        value_only=value_only,
    )


def convert_y(target: Unit, to: str, *, ctx: UnitContext, value_only: bool = True):
    """`convertY()`。"""
    return convert_unit(
        target,
        to,
        ctx=ctx,
        axis_from="y",
        type_from="location",
        axis_to="y",
        type_to="location",
        value_only=value_only,
    )


def convert_width(target: Unit, to: str, *, ctx: UnitContext, value_only: bool = True):
    """`convertWidth()`。"""
    return convert_unit(
        target,
        to,
        ctx=ctx,
        axis_from="x",
        type_from="dimension",
        axis_to="x",
        type_to="dimension",
        value_only=value_only,
    )


def convert_height(target: Unit, to: str, *, ctx: UnitContext, value_only: bool = True):
    """`convertHeight()`。"""
    return convert_unit(
        target,
        to,
        ctx=ctx,
        axis_from="y",
        type_from="dimension",
        axis_to="y",
        type_to="dimension",
        value_only=value_only,
    )

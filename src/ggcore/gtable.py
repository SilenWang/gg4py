"""gtable —— 表格布局核心（gtable 0.3.6 的对等实现）。

一张表由三部分组成，与 R gtable 的对象结构一一对应：

- `widths`：列宽单位向量（长度 = 列数）；
- `heights`：行高单位向量（长度 = 行数）；
- `layout`：每个 grob 占的单元格范围 `(t, l, b, r)`、`z`、`clip`、`name`。

R 里 gtable 本身是个 grob；这里 grob 可以是任意对象，子 :class:`GTable` 也能
当 grob 放进来——嵌套表在自己的单元格视口里解析，于是沿该轴继承单元格尺寸
（`resolve(box.width_cm, box.height_cm)`）。

尺寸解析（:meth:`Layout.resolve`）照抄 grid `src/layout.c` 的
`calcViewportLayout()`：固定部分先换算成 cm，剩余空间按纯 null 权重分配
（`allocateKnownWidths` → `allocateRespected` → `allocateRemainingWidth`）。
与 R 的差异（R 会算成 NaN 或报错的地方）记在 `docs/notes/gtable.md`。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from ggcore.units import (
    Unit,
    UnitContext,
    convert_height,
    convert_width,
    is_pure_null,
    null_value,
    unit_c,
    unit_sum,
)

__all__ = [
    "CellBox",
    "GTable",
    "Layout",
    "LayoutSizes",
    "Placement",
    "gtable",
    "gtable_add_cols",
    "gtable_add_grob",
    "gtable_add_padding",
    "gtable_add_rows",
    "gtable_height",
    "gtable_layout",
    "gtable_width",
    "is_gtable",
]

HJUST = 0.5
"""grid 的 `grid.layout(just = "centre")`：gtable 用的水平对齐。"""

VJUST = 0.5
"""同上，垂直方向（grid 的 `just` 是 `(hjust, vjust)`）。"""

# gtable 0.3.6 的 `gtable_add_grob()` 文档列的就是这三个值（R 不校验）。
# `"inherit"` 只存值：「继承父视口 clip」要等 M0-6 的视口栈，
# 见 docs/notes/gtable.md 的 `vp` 决策点。
_CLIP = frozenset({"on", "off", "inherit"})


@dataclass(frozen=True, slots=True)
class LayoutSizes:
    """解析结果：每列宽 / 每行高（cm）。"""

    widths_cm: tuple[float, ...] = ()
    heights_cm: tuple[float, ...] = ()

    @property
    def total_width_cm(self) -> float:
        return sum(self.widths_cm)

    @property
    def total_height_cm(self) -> float:
        return sum(self.heights_cm)


@dataclass(frozen=True, slots=True)
class CellBox:
    """一个单元格（或 span 区域）在布局视口里的位置与尺寸（cm）。"""

    t: int
    l: int
    b: int
    r: int
    x_cm: float
    y_cm: float
    width_cm: float
    height_cm: float


@dataclass(frozen=True, slots=True)
class Placement:
    """`layout` 表的一行：R 的 `data.frame(t, l, b, r, z, clip, name)`。"""

    t: int
    l: int
    b: int
    r: int
    z: float = math.inf
    clip: str = "on"
    name: str = "layout"

    def __post_init__(self) -> None:
        if self.clip not in _CLIP:
            raise ValueError(f"clip must be 'on', 'off' or 'inherit', got {self.clip!r}")


def _has_room(initial: float, remaining: float) -> bool:
    """对应 layout.c `allocationRemaining()`。"""
    if initial == 0:
        return True
    if initial > 0:
        return remaining > 0
    return remaining < 0


def _share(weight: float, denom: float, mult: float) -> float:
    """`weight / denom * mult`（C 的运算顺序：先除后乘）。

    `denom == 0` 在 R 里是 0/0 = NaN（grid 随后报
    `non-finite location and/or size for viewport`）；这里的 0 权重本来就该拿 0，
    所以直接给 0，见台账。
    """
    if denom == 0:
        return 0.0
    return weight / denom * mult


def _weights(units: Unit, count: int) -> tuple[list[bool], list[float]]:
    """逐列/逐行的 `is_pure_null` 与 `null_value`（M0-3 提供）。"""
    relative = [is_pure_null(units, index) for index in range(count)]
    weights = [null_value(units, index) for index in range(count)]
    return relative, weights


def _allocate(
    widths: Unit,
    heights: Unit,
    parent_width_cm: float,
    parent_height_cm: float,
    ctx: UnitContext,
    respect: bool,
) -> LayoutSizes:
    """`calcViewportLayout()`：把两轴的单位向量解析成 cm。

    两个轴通过 `respect` 耦合，所以不能拆成两次独立的单轴分配。
    """
    ncol, nrow = len(widths), len(heights)
    relative_w, weight_w = _weights(widths, ncol)
    relative_h, weight_h = _weights(heights, nrow)
    # transformWidth() / transformHeight()：非纯 null 的元素立刻换算成 cm。
    fixed_w = [float(value) for value in convert_width(widths, "cm", ctx=ctx)]
    fixed_h = [float(value) for value in convert_height(heights, "cm", ctx=ctx)]

    col_widths = [0.0] * ncol
    row_heights = [0.0] * nrow
    width_left, height_left = parent_width_cm, parent_height_cm

    # allocateKnownWidths() / allocateKnownHeights()
    for index in range(ncol):
        if not relative_w[index]:
            col_widths[index] = fixed_w[index]
            width_left -= col_widths[index]
    for index in range(nrow):
        if not relative_h[index]:
            row_heights[index] = fixed_h[index]
            height_left -= row_heights[index]

    # totalWidth() / totalHeight()：所有参与分配的 null 权重。
    sum_width = 0.0
    for index in range(ncol):
        if relative_w[index]:
            sum_width += weight_w[index]
    sum_height = 0.0
    for index in range(nrow):
        if relative_h[index]:
            sum_height += weight_h[index]

    # allocateRespected()：gtable 的 respect 是逻辑值，故「每个」null 行/列都
    # 受 respect 约束（grid 里 respect 为矩阵时才按格判定，gtable 不产生矩阵）。
    if _has_room(parent_width_cm, width_left) or _has_room(parent_height_cm, height_left):
        if respect:
            temp_width, temp_height = width_left, height_left
            if temp_height * sum_width > sum_height * temp_width:
                denom, mult = sum_width, temp_width
            else:
                denom, mult = sum_height, temp_height
            for index in range(ncol):
                if relative_w[index]:
                    if sum_height == 0:
                        denom, mult = sum_width, temp_width
                    col_widths[index] = _share(weight_w[index], denom, mult)
                    width_left -= col_widths[index]
            for index in range(nrow):
                if relative_h[index]:
                    if sum_width == 0:
                        denom, mult = sum_height, temp_height
                    row_heights[index] = _share(weight_h[index], denom, mult)
                    height_left -= row_heights[index]
    elif respect:
        # setRespectedZero()：两轴都没余量时，受 respect 约束的 null 行列归 0。
        for index in range(ncol):
            if relative_w[index]:
                col_widths[index] = 0.0
        for index in range(nrow):
            if relative_h[index]:
                row_heights[index] = 0.0

    # allocateRemainingWidth() / allocateRemainingHeight()：只看「不受 respect
    # 约束」的 null 权重，分母为 0 时整组归 0（`unit(0, "null")` 的权重就是 0）。
    if _has_room(parent_width_cm, width_left):
        unrespected = 0.0
        for index in range(ncol):
            if relative_w[index] and not respect:
                unrespected += weight_w[index]
        for index in range(ncol):
            if relative_w[index] and not respect:
                col_widths[index] = (
                    width_left * weight_w[index] / unrespected if unrespected > 0 else 0.0
                )
    else:
        for index in range(ncol):
            if relative_w[index] and not respect:
                col_widths[index] = 0.0

    if _has_room(parent_height_cm, height_left):
        unrespected = 0.0
        for index in range(nrow):
            if relative_h[index] and not respect:
                unrespected += weight_h[index]
        for index in range(nrow):
            if relative_h[index] and not respect:
                row_heights[index] = (
                    height_left * weight_h[index] / unrespected if unrespected > 0 else 0.0
                )
    else:
        for index in range(nrow):
            if relative_h[index] and not respect:
                row_heights[index] = 0.0

    return LayoutSizes(tuple(col_widths), tuple(row_heights))


def _layout_context(ctx: UnitContext, width_cm: float, height_cm: float) -> UnitContext:
    """布局视口自己的尺寸由调用方给；其余（xscale / 字号 / 度量）沿用 `ctx`。"""
    return replace(ctx, width_cm=width_cm, height_cm=height_cm)


@dataclass(frozen=True, slots=True)
class Layout:
    """`gtable_layout()` 的结果，等价于 grid 的 `grid.layout()` 对象。"""

    widths: Unit = field(default_factory=Unit)
    heights: Unit = field(default_factory=Unit)
    respect: bool = False

    @property
    def ncol(self) -> int:
        return len(self.widths)

    @property
    def nrow(self) -> int:
        return len(self.heights)

    def resolve(
        self, width_cm: float, height_cm: float, *, ctx: UnitContext | None = None
    ) -> LayoutSizes:
        """在 `width_cm` × `height_cm` 的视口里解析行列尺寸（cm）。"""
        if width_cm < 0 or height_cm < 0:
            raise ValueError("viewport size must not be negative")
        context = _layout_context(ctx or UnitContext(), float(width_cm), float(height_cm))
        return _allocate(
            self.widths, self.heights, float(width_cm), float(height_cm), context, self.respect
        )

    def region_box(
        self,
        t: int,
        l: int,
        b: int | None = None,
        r: int | None = None,
        *,
        width_cm: float,
        height_cm: float,
        sizes: LayoutSizes | None = None,
        ctx: UnitContext | None = None,
        hjust: float = HJUST,
        vjust: float = VJUST,
    ) -> CellBox:
        """单元格（或跨行列区域）的位置与尺寸，对应 layout.c `subRegion()`。"""
        b = t if b is None else b
        r = l if r is None else r
        if not 1 <= t <= b <= self.nrow:
            raise ValueError(f"row range {t}:{b} outside 1:{self.nrow}")
        if not 1 <= l <= r <= self.ncol:
            raise ValueError(f"column range {l}:{r} outside 1:{self.ncol}")
        resolved = sizes if sizes is not None else self.resolve(width_cm, height_cm, ctx=ctx)
        total_w = sum(resolved.widths_cm)
        total_h = sum(resolved.heights_cm)
        x = width_cm * hjust - total_w * hjust + sum(resolved.widths_cm[: l - 1])
        y = height_cm * vjust + (1 - vjust) * total_h - sum(resolved.heights_cm[:b])
        return CellBox(
            t=t,
            l=l,
            b=b,
            r=r,
            x_cm=x,
            y_cm=y,
            width_cm=sum(resolved.widths_cm[l - 1 : r]),
            height_cm=sum(resolved.heights_cm[t - 1 : b]),
        )


def _as_unit(value: Unit | Sequence[Unit] | None, what: str) -> Unit:
    """单位向量参数：`Unit`、`Unit` 列表（`unit_c` 拼接）或 None（空）。"""
    if value is None:
        return Unit()
    if isinstance(value, Unit):
        return value
    if isinstance(value, (list, tuple)):
        items = list(value)
        for item in items:
            if not isinstance(item, Unit):
                raise TypeError(f"{what} must be a unit or a sequence of units")
        return unit_c(*items)
    raise TypeError(f"{what} must be a unit or a sequence of units")


@dataclass(frozen=True, slots=True)
class GTable:
    """gtable：列宽 / 行高 / layout 表 / grobs（R `gtable` 对象）。"""

    widths: Unit = field(default_factory=Unit)
    heights: Unit = field(default_factory=Unit)
    respect: bool = False
    name: str = "layout"
    rownames: tuple[str, ...] | None = None
    colnames: tuple[str, ...] | None = None
    grobs: tuple[Any, ...] = ()
    layout: tuple[Placement, ...] = ()

    def __post_init__(self) -> None:
        if len(self.grobs) != len(self.layout):
            raise ValueError(f"{len(self.grobs)} grobs but {len(self.layout)} layout rows")
        if self.rownames is not None and len(self.rownames) != len(self.heights):
            raise ValueError("rownames must be NULL or have the same length as heights")
        if self.colnames is not None and len(self.colnames) != len(self.widths):
            raise ValueError("colnames must be NULL or have the same length as widths")

    @property
    def nrow(self) -> int:
        return len(self.heights)

    @property
    def ncol(self) -> int:
        return len(self.widths)

    def layout_spec(self) -> Layout:
        """`gtable_layout()`：grid 的 `grid.layout()` 对象。"""
        return Layout(self.widths, self.heights, self.respect)

    def resolve(
        self, width_cm: float, height_cm: float, *, ctx: UnitContext | None = None
    ) -> LayoutSizes:
        return self.layout_spec().resolve(width_cm, height_cm, ctx=ctx)

    def region_box(
        self,
        t: int,
        l: int,
        b: int | None = None,
        r: int | None = None,
        *,
        width_cm: float,
        height_cm: float,
        sizes: LayoutSizes | None = None,
        ctx: UnitContext | None = None,
        hjust: float = HJUST,
        vjust: float = VJUST,
    ) -> CellBox:
        return self.layout_spec().region_box(
            t,
            l,
            b,
            r,
            width_cm=width_cm,
            height_cm=height_cm,
            sizes=sizes,
            ctx=ctx,
            hjust=hjust,
            vjust=vjust,
        )

    def boxes(
        self,
        width_cm: float,
        height_cm: float,
        *,
        ctx: UnitContext | None = None,
        hjust: float = HJUST,
        vjust: float = VJUST,
    ) -> tuple[CellBox, ...]:
        """每条 layout 记录的区域框（span 的宽高即跨行列之和）。"""
        spec = self.layout_spec()
        sizes = spec.resolve(width_cm, height_cm, ctx=ctx)
        return tuple(
            spec.region_box(
                row.t,
                row.l,
                row.b,
                row.r,
                width_cm=width_cm,
                height_cm=height_cm,
                sizes=sizes,
                hjust=hjust,
                vjust=vjust,
            )
            for row in self.layout
        )

    def placements(self, name: str | None = None) -> tuple[Placement, ...]:
        """按 name 查 layout 记录（不传则全部）。"""
        if name is None:
            return self.layout
        return tuple(row for row in self.layout if row.name == name)

    def grob(self, name: str) -> Any:
        """按 name 取第一个 grob。"""
        for row, grob in zip(self.layout, self.grobs, strict=True):
            if row.name == name:
                return grob
        raise KeyError(f"no grob named {name!r}")

    def drawing_order(self) -> tuple[int, ...]:
        """按 z 排序的 grob 下标（R `makeContent.gtable` 的 `order(z)`）。"""
        return tuple(sorted(range(len(self.layout)), key=lambda index: self.layout[index].z))

    def __str__(self) -> str:
        head = f'TableGrob ({self.nrow} x {self.ncol}) "{self.name}": {len(self.grobs)} grobs'
        if not self.layout:
            return head
        lines = [head]
        for index in self.drawing_order():
            row = self.layout[index]
            lines.append(
                f"  ({row.t}-{row.b},{row.l}-{row.r}) z={row.z:g} clip={row.clip} name={row.name}"
            )
        return "\n".join(lines)

    __repr__ = __str__


def is_gtable(value: object) -> bool:
    """`is.gtable()`。"""
    return isinstance(value, GTable)


def gtable(
    widths: Unit | Sequence[Unit] | None = None,
    heights: Unit | Sequence[Unit] | None = None,
    *,
    respect: bool = False,
    name: str = "layout",
    rownames: Sequence[str] | None = None,
    colnames: Sequence[str] | None = None,
    rows: Unit | Sequence[Unit] | None = None,
    cols: Unit | Sequence[Unit] | None = None,
) -> GTable:
    """`gtable(widths, heights, respect, name, rownames, colnames)`。

    行列由两个单位向量定义（R 的签名就是 `widths` / `heights`）：列数 =
    `len(widths)`，行数 = `len(heights)`。`rows` / `cols` 是同一对参数的
    gg4py 别名（`rows` → `heights`，`cols` → `widths`），写起来读起来更顺，
    不能与 `widths` / `heights` 同时给。
    """
    if rows is not None:
        if heights is not None:
            raise TypeError("give either heights or rows, not both")
        heights = rows
    if cols is not None:
        if widths is not None:
            raise TypeError("give either widths or cols, not both")
        widths = cols
    return GTable(
        widths=_as_unit(widths, "widths"),
        heights=_as_unit(heights, "heights"),
        respect=bool(respect),
        name=name,
        rownames=None if rownames is None else tuple(rownames),
        colnames=None if colnames is None else tuple(colnames),
    )


def gtable_layout(x: GTable) -> Layout:
    """`gtable_layout()`：这张表的 grid 布局（行高列宽 + respect）。"""
    if not is_gtable(x):
        raise TypeError("x is not a gtable")
    return x.layout_spec()


def gtable_width(x: GTable) -> Unit:
    """`gtable_width()`：`sum(widths)`，仍是单位（未解析）。"""
    return unit_sum(_expect_gtable(x).widths)


def gtable_height(x: GTable) -> Unit:
    """`gtable_height()`：`sum(heights)`。"""
    return unit_sum(_expect_gtable(x).heights)


def _expect_gtable(x: object) -> GTable:
    if not isinstance(x, GTable):
        raise TypeError("x is not a gtable")
    return x


def _match(value: Any, count: int, what: str) -> list[Any]:
    """R 的 `len_same_or_1()`：长度 1 或与 grobs 等长，否则报错。"""
    items = list(value) if isinstance(value, (list, tuple)) else [value]
    if len(items) == count:
        return items
    if len(items) == 1:
        return items * count
    raise ValueError(f"{what} must have length 1 or length {count} (same as grobs)")


def _neg_to_pos(value: int, maximum: int) -> int:
    """R `neg_to_pos()`：负数从末尾数（-1 是最后一个）。"""
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"index must be an integer, got {value!r}")
    return value if value >= 0 else maximum + 1 + value


def _clip_value(value: Any) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    if value in _CLIP:
        return str(value)
    raise ValueError(f"clip must be a logical or 'on'/'off'/'inherit', got {value!r}")


def gtable_add_grob(
    x: GTable,
    grobs: Any,
    t: int | Sequence[int],
    l: int | Sequence[int],
    b: int | Sequence[int] | None = None,
    r: int | Sequence[int] | None = None,
    z: float | Sequence[float] = math.inf,
    clip: Any = "on",
    name: str | Sequence[str] | None = None,
) -> GTable:
    """`gtable_add_grob()`：把 grob（含子 gtable）钉到 t:b / l:r 区域。

    `t` / `l` / `b` / `r` 都是 1 起、支持负数从末尾数；`z` 默认 `Inf`（排在最
    上层），显式 `-Inf` 排到最下层。`name` 默认沿用表名，与 R 一致。
    """
    table = _expect_gtable(x)
    items = list(grobs) if isinstance(grobs, (list, tuple)) else [grobs]
    count = len(items)
    if count == 0:
        return table

    if name is None:
        name = table.name
    tops = [_neg_to_pos(value, table.nrow) for value in _match(t, count, "t")]
    lefts = [_neg_to_pos(value, table.ncol) for value in _match(l, count, "l")]
    bottoms = [
        _neg_to_pos(value, table.nrow) for value in _match(t if b is None else b, count, "b")
    ]
    rights = [_neg_to_pos(value, table.ncol) for value in _match(l if r is None else r, count, "r")]
    zs = [float(value) for value in _match(z, count, "z")]
    clips = [_clip_value(value) for value in _match(clip, count, "clip")]
    names = [str(value) for value in _match(name, count, "name")]

    for top, bottom in zip(tops, bottoms, strict=True):
        if not 1 <= top <= bottom <= table.nrow:
            raise ValueError(f"invalid row range {top}:{bottom} for {table.nrow} rows")
    for left, right in zip(lefts, rights, strict=True):
        if not 1 <= left <= right <= table.ncol:
            raise ValueError(f"invalid column range {left}:{right} for {table.ncol} columns")

    # z 的无穷值按 R 的规则落到现有 z 之外：-Inf 从下往上排，+Inf 从上往上排。
    pool = [row.z for row in table.layout] + [value for value in zs if not math.isinf(value)]
    zmin, zmax = (1.0, 0.0) if not pool else (min(pool), max(pool))
    below = [index for index, value in enumerate(zs) if value == -math.inf]
    above = [index for index, value in enumerate(zs) if value == math.inf]
    for offset, index in enumerate(below):
        zs[index] = zmin - (len(below) - offset)
    for offset, index in enumerate(above):
        zs[index] = zmax + offset + 1

    placements = tuple(
        Placement(t=top, l=left, b=bottom, r=right, z=value_z, clip=value_clip, name=value_name)
        for top, left, bottom, right, value_z, value_clip, value_name in zip(
            tops, lefts, bottoms, rights, zs, clips, names, strict=True
        )
    )
    return replace(table, grobs=table.grobs + tuple(items), layout=table.layout + placements)


def _insert_unit(target: Unit, values: Unit, after: int) -> Unit:
    """R `insert.unit(x, values, after)`。"""
    length = len(target)
    if length == 0:
        return values
    if len(values) == 0:
        return target
    if after <= 0:
        return unit_c(values, target)
    if after >= length:
        return unit_c(target, values)
    return unit_c(target[:after], values, target[after:])


def gtable_add_rows(x: GTable, heights: Unit | Sequence[Unit], pos: int = -1) -> GTable:
    """`gtable_add_rows()`：在 `pos` 之后插行（0 = 最前，-1 = 最后）。"""
    table = _expect_gtable(x)
    values = _as_unit(heights, "heights")
    count = len(values)
    if count == 0:
        return table
    after = _neg_to_pos(pos, len(table.heights))
    layout = tuple(
        replace(
            row,
            t=row.t + count if row.t > after else row.t,
            b=row.b + count if row.b > after else row.b,
        )
        for row in table.layout
    )
    return replace(table, heights=_insert_unit(table.heights, values, after), layout=layout)


def gtable_add_cols(x: GTable, widths: Unit | Sequence[Unit], pos: int = -1) -> GTable:
    """`gtable_add_cols()`：在 `pos` 之后插列（0 = 最前，-1 = 最后）。"""
    table = _expect_gtable(x)
    values = _as_unit(widths, "widths")
    count = len(values)
    if count == 0:
        return table
    after = _neg_to_pos(pos, len(table.widths))
    layout = tuple(
        replace(
            row,
            l=row.l + count if row.l > after else row.l,
            r=row.r + count if row.r > after else row.r,
        )
        for row in table.layout
    )
    return replace(table, widths=_insert_unit(table.widths, values, after), layout=layout)


def gtable_add_padding(x: GTable, padding: Unit | Sequence[Unit]) -> GTable:
    """`gtable_add_padding()`：四边各加一行/一列。

    `padding` 按 grid 的顺序 `(top, right, bottom, left)`；长度不足 4 时按模回收。
    单位可以是 `pt` / `mm` / `null` 等任何单位——`null` 边距与表内的 null 行列
    一起参与剩余空间分配。
    """
    table = _expect_gtable(x)
    pads = _as_unit(padding, "padding")
    if len(pads) == 0:
        raise ValueError("padding must not be empty")
    sides = [Unit((pads.elements[index % len(pads)],)) for index in range(4)]
    top, right, bottom, left = sides
    table = gtable_add_rows(table, top, pos=0)
    table = gtable_add_cols(table, right, pos=-1)
    table = gtable_add_rows(table, bottom, pos=-1)
    table = gtable_add_cols(table, left, pos=0)
    return table

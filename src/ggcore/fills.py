"""渐变 / pattern 填充的**写方** API（SIL-751）。

grid 的 `linearGradient()` / `radialGradient()` / `pattern()` 在 gg4py 的对等物。
IR 里没有单位（`docs/notes/ir.md` §1），所以这些对象只是**待解析的规格**：坐标
按 `units` 解释，写 IR 的那一刻（`Instruction.to_node()`）才用被填充节点的包围盒
折成最终几何，折出来的就是 `ggcore.ir` 的 `LinearGradient` / `RadialGradient` /
`TilePattern`。

单位口径（对标 grid）：

| `units` | 渐变端点 / 图案 tile 的尺寸与位置 | 径向半径 |
| --- | --- | --- |
| `"npc"`（缺省） | 被填充对象包围盒的比例（0..1） | `r × min(宽, 高)` |
| `"pt"` | 节点局部坐标的 pt（与几何同一坐标系） | pt |

图案的 tile 以 `(x, y)` 为**中心**对齐（R `pattern()` 的 `just = "centre"`），
窗口是 `[origin, origin + size)`。`x` / `y` 的锚点单位由 `anchor_units` 单独给
（缺省 `"npc"`）——R 的 `width` / `height` 可以是 `unit(1, "cm")` 这种绝对单位，
而 `x` / `y` 仍留在缺省的 npc 上，两者不必同单位。

图案**内容**的坐标系与 tile 无关（SIL-833）：R 的 `pattern()` 内容按**被填充 grob
的 bbox** 折 npc，再按 tile 窗口裁剪，所以 `draw(bbox)` 收到的是整层 grob 的
包围盒（本地坐标），内容照它摆一次，所有 tile 共用这份几何——这才是 R 的相位。
IR 仍是 `patternContentUnits="userSpaceOnUse"` 的绝对几何，两个渲染器都能直接吃。
`pattern_npc_rect()` 就是「按 bbox 的 npc 摆一块矩形」的便捷写法。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from ggcore import ir
from ggcore.ir import Node

__all__ = [
    "Box",
    "FillSpec",
    "LinearGradientSpec",
    "RadialGradientSpec",
    "TilePatternSpec",
    "linear_gradient",
    "node_bbox",
    "pattern_circle",
    "pattern_npc_rect",
    "pattern_rect",
    "radial_gradient",
    "tile_pattern",
]

Box = tuple[float, float, float, float]


def _colour(value: Any) -> tuple[int, int, int, int]:
    # 延迟导入：`ggcore.grobs` 依赖本模块，模块级互相 import 会成环。
    from ggcore.grobs import parse_colour

    return parse_colour(value)


def _colours(colours: Sequence[Any], stops: Sequence[float] | None) -> tuple[ir.Stop, ...]:
    parsed = [_colour(colour) for colour in colours]
    if len(parsed) < 2:
        raise ValueError(f"渐变至少要两个颜色，收到 {len(parsed)} 个")
    if stops is None:
        offsets = [index / (len(parsed) - 1) for index in range(len(parsed))]
    else:
        offsets = [float(offset) for offset in stops]
        if len(offsets) != len(parsed):
            raise ValueError(f"stops（{len(offsets)} 个）必须和 colours（{len(parsed)} 个）等长")
    return tuple(ir.Stop(offset, colour) for offset, colour in zip(offsets, parsed, strict=True))


def _extend(value: str) -> ir.Extend:
    try:
        return ir.Extend(value)
    except ValueError as exc:
        raise ValueError(f"extend 不认识 {value!r}；可选 pad / repeat / reflect") from exc


def _position(value: float | int, lo: float, hi: float, units: str) -> float:
    if units == "npc":
        return lo + float(value) * (hi - lo)
    if units == "pt":
        return float(value)
    raise ValueError(f"units 只能是 'npc' 或 'pt'，收到 {units!r}")


def _position_y(value: float | int, lo: float, hi: float, units: str) -> float:
    """y 轴的 npc 位置：R / grid 的 npc 是 **y 向上**（0 = 底边），IR 的局部坐标
    y 向下，所以这里要翻一次。`pt` 口径是节点局部坐标直通，不翻。
    """
    if units == "npc":
        return hi - float(value) * (hi - lo)
    return _position(value, lo, hi, units)


def _span(value: float | int, length: float, units: str) -> float:
    if units == "npc":
        return float(value) * length
    if units == "pt":
        return float(value)
    raise ValueError(f"units 只能是 'npc' 或 'pt'，收到 {units!r}")


class FillSpec:
    """待解析的填充规格：`resolve(bbox)` → `ggcore.ir` 的 fill 对象。"""

    def resolve(self, bbox: Box) -> ir.Fill:
        raise NotImplementedError


@dataclass(frozen=True)
class LinearGradientSpec(FillSpec):
    stops: tuple[ir.Stop, ...]
    x1: float
    y1: float
    x2: float
    y2: float
    units: str = "npc"
    extend: ir.Extend = ir.Extend.PAD

    def resolve(self, bbox: Box) -> ir.LinearGradient:
        x0, y0, x1, y1 = bbox
        return ir.LinearGradient(
            stops=self.stops,
            start=(
                _position(self.x1, x0, x1, self.units),
                _position_y(self.y1, y0, y1, self.units),
            ),
            end=(_position(self.x2, x0, x1, self.units), _position_y(self.y2, y0, y1, self.units)),
            extend=self.extend,
        )


@dataclass(frozen=True)
class RadialGradientSpec(FillSpec):
    stops: tuple[ir.Stop, ...]
    cx: float
    cy: float
    r: float
    fx: float | None = None
    fy: float | None = None
    fr: float = 0.0
    units: str = "npc"
    extend: ir.Extend = ir.Extend.PAD

    def resolve(self, bbox: Box) -> ir.RadialGradient:
        x0, y0, x1, y1 = bbox
        radius = _span(self.r, min(x1 - x0, y1 - y0), self.units)
        focal = None
        if self.fx is not None or self.fy is not None:
            focal = (
                _position(self.cx if self.fx is None else self.fx, x0, x1, self.units),
                _position_y(self.cy if self.fy is None else self.fy, y0, y1, self.units),
                _span(self.fr, min(x1 - x0, y1 - y0), self.units),
            )
        return ir.RadialGradient(
            stops=self.stops,
            center=(
                _position(self.cx, x0, x1, self.units),
                _position_y(self.cy, y0, y1, self.units),
            ),
            radius=radius,
            focal=focal,
            extend=self.extend,
        )


@dataclass(frozen=True)
class TilePatternSpec(FillSpec):
    draw: Callable[[Box], Sequence[Node]]
    width: float = 1.0
    height: float = 1.0
    x: float = 0.5
    y: float = 0.5
    units: str = "npc"
    anchor_units: str = "npc"
    extend: ir.Extend = ir.Extend.REPEAT

    def resolve(self, bbox: Box) -> ir.TilePattern:
        x0, y0, x1, y1 = bbox
        width = _span(self.width, x1 - x0, self.units)
        height = _span(self.height, y1 - y0, self.units)
        if width <= 0 or height <= 0:
            raise ValueError(f"pattern 的 tile 尺寸必须为正，收到 {width!r} × {height!r}")
        # tile 以 (x, y) 为中心：origin = 中心 - 半个 tile（y 向下，与几何一致）。
        left = _position(self.x, x0, x1, self.anchor_units) - width / 2
        top = _position_y(self.y, y0, y1, self.anchor_units) - height / 2
        return ir.TilePattern(
            # 内容是**被填充 grob 的 bbox** 里的几何（R 的 npc 口径），不是 tile
            # 局部坐标：同一层的每块 tile 共用这一份，相位才与 R 一致（SIL-833）。
            content=tuple(self.draw(bbox)),
            size=(width, height),
            origin=(left, top),
            extend=self.extend,
        )


# ---------------------------------------------------------------------------
# 公共构造器（对标 grid::linearGradient / radialGradient / pattern）
# ---------------------------------------------------------------------------


def linear_gradient(
    colours: Sequence[Any],
    stops: Sequence[float] | None = None,
    *,
    x1: float = 0.0,
    y1: float = 0.0,
    x2: float = 1.0,
    y2: float = 1.0,
    units: str = "npc",
    extend: str = "pad",
) -> LinearGradientSpec:
    """线性渐变；缺省从左下到右上（grid 的缺省 npc 口径，y 向下即左上到右下）。"""
    return LinearGradientSpec(
        stops=_colours(colours, stops),
        x1=float(x1),
        y1=float(y1),
        x2=float(x2),
        y2=float(y2),
        units=units,
        extend=_extend(extend),
    )


def radial_gradient(
    colours: Sequence[Any],
    stops: Sequence[float] | None = None,
    *,
    cx: float = 0.5,
    cy: float = 0.5,
    r: float = 0.5,
    fx: float | None = None,
    fy: float | None = None,
    fr: float = 0.0,
    units: str = "npc",
    extend: str = "pad",
) -> RadialGradientSpec:
    """径向渐变；缺省圆心在被填充对象正中、半径是短边的一半（grid 的缺省）。"""
    return RadialGradientSpec(
        stops=_colours(colours, stops),
        cx=float(cx),
        cy=float(cy),
        r=float(r),
        fx=None if fx is None else float(fx),
        fy=None if fy is None else float(fy),
        fr=float(fr),
        units=units,
        extend=_extend(extend),
    )


def tile_pattern(
    draw: Callable[[Box], Sequence[Node]],
    *,
    width: float = 1.0,
    height: float = 1.0,
    x: float = 0.5,
    y: float = 0.5,
    units: str = "npc",
    anchor_units: str = "npc",
    extend: str = "repeat",
) -> TilePatternSpec:
    """平铺图案：`draw(bbox)` 收到**被填充 grob 的包围盒**（节点局部坐标）。

    内容按包围盒摆一次、所有 tile 共用（R `pattern()` 的内容坐标系，SIL-833）：
    内容不是 tile 局部坐标，也不是逐 tile 各画一份——tile 只决定**裁剪窗口与
    重复周期**，相位由内容与 bbox 的相对位置决定。`draw` 里通常用
    :func:`pattern_npc_rect` 按 bbox 的 npc 摆矩形（R 里写 `rectGrob(x = …)` 的
    那个口径），或用 :func:`pattern_rect` / :func:`pattern_circle` 直接给局部坐标。

    `x` / `y` 是 tile 的锚点（tile 的中心），单位由 `anchor_units` 单独给；
    `width` / `height` 用 `units`（R 的 `pattern(width = unit(1, "cm"))` 就是
    `units="pt"` + 绝对 pt 尺寸）。
    """
    return TilePatternSpec(
        draw=draw,
        width=float(width),
        height=float(height),
        x=float(x),
        y=float(y),
        units=units,
        anchor_units=anchor_units,
        extend=_extend(extend),
    )


# ---------------------------------------------------------------------------
# pattern 内容的便捷构造（gpar.fill 只能是纯色）
# ---------------------------------------------------------------------------


def _pattern_gpar(fill: Any, colour: Any, lwd: float) -> ir.Gpar:
    return ir.Gpar(
        fill=None if fill is None else _colour(fill),
        col=None if colour is None else _colour(colour),
        lwd=lwd,
    )


def pattern_rect(
    rect: Sequence[float],
    fill: Any = None,
    *,
    colour: Any = None,
    lwd: float = 1.0,
) -> Node:
    """tile 里的一块矩形：`rect` 是 `(x0, y0, x1, y1)`（节点局部坐标）。"""
    return Node(
        ir.NodeKind.RECT,
        gpar=_pattern_gpar(fill, colour, lwd),
        bufs={"rect": ir.f32([list(rect)])},
    )


def pattern_npc_rect(
    bbox: Box,
    x: float,
    y: float,
    width: float,
    height: float,
    fill: Any = None,
    *,
    colour: Any = None,
    lwd: float = 1.0,
) -> Node:
    """按**包围盒的 npc** 摆一块矩形（R `rectGrob(x, y, width, height)` 的口径）。

    `(x, y)` 是矩形中心、`width` / `height` 是 bbox 的比例，**y 向上**（npc 0 =
    底边，与 grid / R 一致）；IR 的局部坐标 y 向下，这里翻一次。R 的
    `pattern(rectGrob(c(0.25, 0.75), c(0.25, 0.75), width = 0.5, height = 0.5))`
    就是两次 `pattern_npc_rect(bbox, 0.25, 0.25, 0.5, 0.5, …)`。
    """
    x0, y0, x1, y1 = bbox
    span_x = x1 - x0
    span_y = y1 - y0
    left = x0 + (float(x) - float(width) / 2) * span_x
    right = left + float(width) * span_x
    centre_y = y1 - float(y) * span_y
    top = centre_y - float(height) * span_y / 2
    bottom = centre_y + float(height) * span_y / 2
    return pattern_rect((left, top, right, bottom), fill, colour=colour, lwd=lwd)


def pattern_circle(
    center: Sequence[float],
    radius: float,
    fill: Any = None,
    *,
    colour: Any = None,
    lwd: float = 1.0,
) -> Node:
    """tile 里的一个圆：`center` 是 `(cx, cy)`（节点局部坐标）。"""
    return Node(
        ir.NodeKind.CIRCLE,
        gpar=_pattern_gpar(fill, colour, lwd),
        bufs={"circle": ir.f32([[float(center[0]), float(center[1]), float(radius)]])},
    )


# ---------------------------------------------------------------------------
# 包围盒：npc 口径的分母
# ---------------------------------------------------------------------------


def node_bbox(kind: Any, bufs: Any, params: Any) -> Box | None:
    """节点几何的局部包围盒 `(x0, y0, x1, y1)`；没有几何可量的返回 None。

    `points` 按「点坐标 ± size/2」估：pch 的真实外形设备才知道（25 种符号各有
    自己的半径系数），npc 渐变挂在点上本来就不是常见用法，这里只保证不崩。
    """
    kind = ir.NodeKind(kind)
    if kind is ir.NodeKind.RECT and "rect" in bufs:
        rows = bufs["rect"]
    elif kind is ir.NodeKind.SEGMENTS and "segments" in bufs:
        rows = bufs["segments"]
    elif kind is ir.NodeKind.CIRCLE and "circle" in bufs:
        circles = bufs["circle"]
        xs = [float(row[0]) - float(row[2]) for row in circles]
        ys = [float(row[1]) - float(row[2]) for row in circles]
        x1 = [float(row[0]) + float(row[2]) for row in circles]
        y1 = [float(row[1]) + float(row[2]) for row in circles]
        if not len(xs):
            return None
        return (min(xs), min(ys), max(x1), max(y1))
    elif kind is ir.NodeKind.POINTS and "points" in bufs:
        points = bufs["points"]
        half = float(params.get("size", 1.0)) / 2
        xs = [float(row[0]) - half for row in points]
        ys = [float(row[1]) - half for row in points]
        x1 = [float(row[0]) + half for row in points]
        y1 = [float(row[1]) + half for row in points]
        if not len(xs):
            return None
        return (min(xs), min(ys), max(x1), max(y1))
    elif "points" in bufs:
        rows = bufs["points"]
    elif "control" in bufs:
        rows = bufs["control"]
    elif "ends" in bufs:
        ends = bufs["ends"]
        xs = [float(row[0]) for row in ends] + [float(row[2]) for row in ends]
        ys = [float(row[1]) for row in ends] + [float(row[3]) for row in ends]
        if not xs:
            return None
        return (min(xs), min(ys), max(xs), max(ys))
    else:
        return None
    xs = [float(row[0]) for row in rows]
    ys = [float(row[1]) for row in rows]
    if not xs:
        return None
    if len(rows[0]) >= 4:
        xs += [float(row[2]) for row in rows]
        ys += [float(row[3]) for row in rows]
    return (min(xs), min(ys), max(xs), max(ys))

"""`grid::arrow()` 的对等物（M2-S2）。

IR 只带**标记属性**（`arrow` / `arrow_length` / `arrow_angle` / `arrow_type`，
见 `ggcore.ir.nodes._ARROW_PARAMS`），箭翼的几何由设备按端点切向求值：

- 线段 / 折线：切向 = 最后两个顶点连线的方向（`first` 端用前两个顶点）；
- 曲线：切向由设备采样后的曲线端点求（曲线公式只在设备侧，`ggskia.curves` /
  `web/viewer/src/curves.ts`）。

口径照 `grid::arrow()`：`length` 是每条箭翼的长度，`angle` 是箭翼与轴线之间的
夹角；`open` 画两条边，`closed` 画一个填色三角（填充色用 gpar 的 `fill`，
geom 侧默认折成线条色，R 的 `arrow.fill` 同理）。

```python
from ggcore import arrow, geom_segment
p + geom_segment(arrow=arrow(type="closed", length=unit(0.15, "inches")))
```
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ggcore.units import Unit

__all__ = [
    "ARROW_ENDS",
    "ARROW_TYPES",
    "Arrow",
    "arrow",
    "arrow_node_params",
    "as_arrow",
    "head_geometry",
]

#: `grid::arrow(ends =)` 的三个取值。
ARROW_ENDS = ("first", "last", "both")
#: `grid::arrow(type =)` 的两个取值。
ARROW_TYPES = ("open", "closed")
#: `grid::arrow()` 的缺省 length：`unit(0.25, "inches")` → 18 pt。
DEFAULT_LENGTH_PT = 0.25 * 72.0

#: 简单单位 → pt 的换算（grid 的 `convertUnit(..., "bigpts")` 只覆盖这几个）。
_TO_PT = {
    "pt": 1.0,
    "points": 1.0,
    "bigpts": 1.0,
    "in": 72.0,
    "inch": 72.0,
    "inches": 72.0,
    "cm": 72.0 / 2.54,
    "mm": 72.0 / 25.4,
    "lines": 12.0,  # 上游的 lines → pt 依赖字体；这里给一个固定口径（0.25in 的 2/3）
}


@dataclass(frozen=True, slots=True)
class Arrow:
    """一个已解析的箭头规格（`grid::arrow()` 的四个字段）。"""

    angle: float = 30.0
    length_pt: float = DEFAULT_LENGTH_PT
    ends: str = "last"
    type: str = "open"

    @property
    def draws_first(self) -> bool:
        return self.ends in ("first", "both")

    @property
    def draws_last(self) -> bool:
        return self.ends in ("last", "both")


def _length_pt(value: Any) -> float:
    """`length` → pt。接受数值（按 pt 解释）或简单单位对象。"""
    if isinstance(value, Unit):
        elements = value.elements
        if len(elements) != 1 or elements[0].data is not None:
            raise ValueError(f"arrow(length=...) 只接受简单单位，收到 {value!r}")
        kind = elements[0].kind
        if kind not in _TO_PT:
            raise ValueError(f"arrow(length=...) 不认识单位 {kind!r}；可用：{sorted(_TO_PT)}")
        return float(elements[0].amount) * _TO_PT[kind]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"arrow(length=...) 必须是数值（pt）或单位，收到 {type(value).__name__}")
    return float(value)


def arrow(
    angle: float = 30.0,
    length: Any = None,
    ends: str = "last",
    type: str = "open",
) -> Arrow:
    """`grid::arrow(angle = 30, length = unit(0.25, "inches"), ends = "last", type = "open")`。"""
    if length is None:
        length = DEFAULT_LENGTH_PT
    if ends not in ARROW_ENDS:
        raise ValueError(f"arrow(ends=...) 只能是 {list(ARROW_ENDS)}，收到 {ends!r}")
    if type not in ARROW_TYPES:
        raise ValueError(f"arrow(type=...) 只能是 {list(ARROW_TYPES)}，收到 {type!r}")
    value = _length_pt(length)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"arrow(length=...) 必须是非负有限数，收到 {length!r}")
    if not math.isfinite(float(angle)) or not 0.0 <= float(angle) <= 90.0:
        raise ValueError(f"arrow(angle=...) 必须在 0..90 度，收到 {angle!r}")
    return Arrow(angle=float(angle), length_pt=value, ends=ends, type=type)


def as_arrow(value: Any) -> Arrow | None:
    """`arrow` 参数归一：`None` / `Arrow` / 映射 / `grid::arrow` 式列表。"""
    if value is None:
        return None
    if isinstance(value, Arrow):
        return value
    if isinstance(value, Mapping):
        unknown = set(value) - {"angle", "length", "ends", "type", "length_pt"}
        if unknown:
            raise ValueError(f"arrow 映射里有不认识的键：{sorted(unknown)}")
        for name in ("ends", "type"):
            if (
                name in value
                and isinstance(value[name], (int, float))
                and not isinstance(value[name], bool)
            ):
                raise ValueError(f"arrow 的 {name} 不能是数字（grid 的整数编号由本模块换算）")
        return arrow(
            angle=value.get("angle", 30.0),
            length=value.get("length_pt", value.get("length")),
            ends=value.get("ends", "last"),
            type=value.get("type", "open"),
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return as_arrow(dict(zip(("angle", "length", "ends", "type"), value, strict=False)))
    raise TypeError(f"arrow=... 必须是 arrow() 的返回值或映射，收到 {type(value).__name__}")


def arrow_node_params(value: Any) -> dict[str, Any]:
    """`Arrow | None` → IR 节点参数（缺省值不写，保持无箭头节点的字节不变）。"""
    spec = as_arrow(value)
    if spec is None or spec.length_pt <= 0:
        return {}
    params: dict[str, Any] = {
        "arrow": spec.ends,
        "arrow_length": spec.length_pt,
        "arrow_angle": spec.angle,
    }
    if spec.type != "open":
        params["arrow_type"] = spec.type
    return params


def head_geometry(
    tip_x: float,
    tip_y: float,
    back_x: float,
    back_y: float,
    *,
    length_pt: float,
    angle: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """箭头的两个底点：从 `tip` 沿 `back → tip` 方向的两侧张开 `angle` 度。

    `back` 是切向上「箭尾一侧」的相邻点；返回 `(b1, b2)`。方向退化（两点重合）
    时返回两个与 tip 重合的点——R 的 `grid` 在这种情况下也不画。
    """
    dx = float(tip_x) - float(back_x)
    dy = float(tip_y) - float(back_y)
    norm = math.hypot(dx, dy)
    if not math.isfinite(norm) or norm == 0.0:
        return (float(tip_x), float(tip_y)), (float(tip_x), float(tip_y))
    ux, uy = dx / norm, dy / norm
    radians = math.radians(float(angle))
    cos_a, sin_a = math.cos(radians), math.sin(radians)
    # 沿 -u 方向走 length，再在两侧各转 ±angle。
    bx1 = float(tip_x) - length_pt * (ux * cos_a - uy * sin_a)
    by1 = float(tip_y) - length_pt * (ux * sin_a + uy * cos_a)
    bx2 = float(tip_x) - length_pt * (ux * cos_a + uy * sin_a)
    by2 = float(tip_y) - length_pt * (-ux * sin_a + uy * cos_a)
    return (bx1, by1), (bx2, by2)

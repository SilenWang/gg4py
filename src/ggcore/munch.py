"""非线性坐标下的逐边细分段数（`coord_munch()` 的唯一一份口径）。

`coord_munch()`（上游 `R/coord-munch.R`）把折线 / 多边形按 `segment_length` 细分，
再交给坐标变换，让极坐标里的边变成弧。三个地方都要算同一个段数：

* `ggcore.coord.coord_munch()`：坐标层（`coord_polar` / `coord_radial` / `coord_trans`）；
* `ggcore.geom.base.munch()`：几何层（`geom_col` 之类的矩形边）；
* `ggcore.geom.line.munch()`：`geom_path` / `geom_line`。

段数是**离散**判定：`ceil(distance / segment_length)`。商恰好贴在整数上时，宿主
libm 的 `hypot` / `sqrt` 差 1 ULP 就能让它多一段或少一段——同一张图在另一台机器
上因此多出两个顶点，IR 的 sha256 跟着变（SIL-824 返工：`coord_polar` 的扇形弧在
CI runner 上漂移，本机却全绿）。

所以先把商舍到固定十进制网格再取整：1 ULP 的边界抖动被吃掉，而 1e-6 段 ≈
`segment_length` 的百万分之一，视觉上不存在。舍入用 `round()`（正确舍入的十进制
转换，不经过 libm），因此这段判定在 CPython / Pyodide / 任何 CPU 上逐位相同。
"""

from __future__ import annotations

import math

__all__ = ["SEGMENT_DECIMALS", "munch_steps"]

#: 细分比量化到这一位十进制。
SEGMENT_DECIMALS = 6


def munch_steps(distance: float, segment_length: float) -> int:
    """`coord_munch()` 的段数：`ceil(distance / segment_length)`，输入先量化。"""
    ratio = round(float(distance) / float(segment_length), SEGMENT_DECIMALS)
    return max(1, math.ceil(ratio))

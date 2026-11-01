"""`pch` 符号表（M0-8）：R `src/main/engine.c::GESymbol()` 的几何。

IR 的 `points` 节点只带 `pch` 与 `size`（pt），符号画多大、怎么画都在设备侧
（`docs/notes/grobs.md` §11 把这张表留给了 M0-8）。这里逐条照 R 的常量与
坐标：

| pch | 形状 | 画法 |
| --- | --- | --- |
| 0 | 空心方 | 描边 |
| 1 | 空心圆 | 描边 |
| 2 | 上三角 | 描边 |
| 3 / 4 | 加号 / 叉号 | 描边 |
| 5 | 空心菱形 | 描边 |
| 6 | 下三角 | 描边 |
| 7 / 8 / 9 / 10 / 11 / 12 / 13 / 14 | 组合符号 | 描边 |
| 15..18 | 实心方 / 圆 / 上三角 / 菱形 | `col` 填充 |
| 19 / 20 | 实心圆 / 小实心圆 | `col` 填充 + `col` 描边 |
| 21..25 | 圆 / 方 / 菱形 / 上三角 / 下三角 | `fill` 填充 + `col` 描边 |
| 32..127、负数 | 字符（负数取码点 `-pch`） | 文字，见 `ggskia.text` |

尺寸口径：R 的 `GESymbol(x, y, pch, size, …)` 里符号半径是 `RADIUS * size`
（`RADIUS = 0.375`），即**直径是 size 的 3/4**。旧临时设备用 `size / 2` 当半径
（直径 = size），大了 1/3；M0-8 按 R 的常量，`docs/cases/grob-points/baseline`
因此重录（`docs/notes/device.md` §5）。

y 轴：R 的引擎是 y 向上，IR 是 y 向下；这里所有纵向偏移都按 R 算完再取反，
所以「上三角」在页面上仍然朝上。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import skia

__all__ = ["SYMBOLS", "Symbol", "character_pch", "symbol"]

# R engine.c 的常量（原样抄，别改成 0.5）。
SMALL = 0.25
RADIUS = 0.375
M_SQRT_2 = math.sqrt(2.0)
SQRC = 0.88622692545275801364
DMDC = 1.25331413731550025119
TRC0 = 1.55512030155621416073
TRC1 = 1.34677368708859836060
TRC2 = 0.77756015077810708036

#: 有几何定义的编号（其余按字符处理或什么也不画）。
SYMBOLS = frozenset(range(26))


@dataclass(frozen=True)
class Symbol:
    """一个符号的画法：一条路径 + 三种上色方式。"""

    path: skia.Path
    stroke: bool = True
    fill_col: bool = False
    fill_gpar: bool = False


def character_pch(pch: int) -> str | None:
    """字符型 pch：`32..127` 是字符本身，负数取其码点（R 的同一规则）。"""
    if pch < 0:
        try:
            return chr(-pch)
        except ValueError:
            return None
    if 32 <= pch <= 127:
        return chr(pch)
    return None


def _polygon(points: list[tuple[float, float]]) -> skia.Path:
    path = skia.Path()
    path.moveTo(*points[0])
    for point in points[1:]:
        path.lineTo(*point)
    path.close()
    return path


def _lines(pairs: list[tuple[tuple[float, float], tuple[float, float]]]) -> skia.Path:
    path = skia.Path()
    for start, end in pairs:
        path.moveTo(*start)
        path.lineTo(*end)
    return path


def symbol(pch: int, size: float) -> Symbol | None:
    """`pch`（0..25）→ 以原点为中心、边长按 `size` 缩放的符号。

    原点即锚点，纵向已翻成 y 向下（`_up` 取反）。
    """
    half = RADIUS * size
    up_triangle = _triangle(size, down=False)
    down_triangle = _triangle(size, down=True)

    if pch == 0:  # 空心方
        return Symbol(_polygon([(-half, -half), (half, -half), (half, half), (-half, half)]))
    if pch == 1:  # 空心圆
        path = skia.Path()
        path.addCircle(0.0, 0.0, half)
        return Symbol(path)
    if pch == 2:  # 上三角
        return Symbol(up_triangle)
    if pch == 3:  # 加号
        cross = M_SQRT_2 * RADIUS * size
        return Symbol(_lines([((-cross, 0.0), (cross, 0.0)), ((0.0, -cross), (0.0, cross))]))
    if pch == 4:  # 叉号
        return Symbol(_lines([((-half, -half), (half, half)), ((-half, half), (half, -half))]))
    if pch == 5:  # 空心菱形
        d = M_SQRT_2 * RADIUS * size
        return Symbol(_polygon([(-d, 0.0), (0.0, -d), (d, 0.0), (0.0, d)]))
    if pch == 6:  # 下三角
        return Symbol(down_triangle)
    if pch == 7:  # 方 + 叉
        path = _polygon([(-half, -half), (half, -half), (half, half), (-half, half)])
        path.addPath(_lines([((-half, -half), (half, half)), ((-half, half), (half, -half))]))
        return Symbol(path)
    if pch == 8:  # 叉 + 加
        cross = M_SQRT_2 * RADIUS * size
        return Symbol(
            _lines(
                [
                    ((-half, -half), (half, half)),
                    ((-half, half), (half, -half)),
                    ((-cross, 0.0), (cross, 0.0)),
                    ((0.0, -cross), (0.0, cross)),
                ]
            )
        )
    if pch == 9:  # 菱形 + 加
        d = M_SQRT_2 * RADIUS * size
        path = _lines([((-d, 0.0), (d, 0.0)), ((0.0, -d), (0.0, d))])
        path.addPath(_polygon([(-d, 0.0), (0.0, -d), (d, 0.0), (0.0, d)]))
        return Symbol(path)
    if pch == 10:  # 圆 + 加
        path = skia.Path()
        path.addCircle(0.0, 0.0, half)
        path.addPath(_lines([((-half, 0.0), (half, 0.0)), ((0.0, -half), (0.0, half))]))
        return Symbol(path)
    if pch == 11:  # 上下三角
        r = TRC0 * half
        yc = 0.5 * (TRC2 * half + r)
        xc = TRC1 * half
        path = _polygon([(0.0, r), (xc, -yc), (-xc, -yc)])  # 下三角
        path.addPath(_polygon([(0.0, -r), (xc, yc), (-xc, yc)]))  # 上三角
        return Symbol(path)
    if pch == 12:  # 方 + 加
        path = _lines([((-half, 0.0), (half, 0.0)), ((0.0, -half), (0.0, half))])
        path.addPath(_polygon([(-half, -half), (half, -half), (half, half), (-half, half)]))
        return Symbol(path)
    if pch == 13:  # 圆 + 叉
        path = skia.Path()
        path.addCircle(0.0, 0.0, half)
        path.addPath(_lines([((-half, -half), (half, half)), ((-half, half), (half, -half))]))
        return Symbol(path)
    if pch == 14:  # 上三角 + 方
        path = _polygon([(0.0, -half), (half, half), (-half, half)])
        path.addPath(_polygon([(-half, -half), (half, -half), (half, half), (-half, half)]))
        return Symbol(path)
    if pch == 15:  # 实心方
        square = _polygon([(-half, -half), (half, -half), (half, half), (-half, half)])
        return Symbol(square, stroke=False, fill_col=True)
    if pch == 16:  # 实心圆
        path = skia.Path()
        path.addCircle(0.0, 0.0, half)
        return Symbol(path, stroke=False, fill_col=True)
    if pch == 17:  # 实心上三角
        return Symbol(up_triangle, stroke=False, fill_col=True)
    if pch == 18:  # 实心菱形（比 5 小：RADIUS 而不是 M_SQRT2*RADIUS）
        return Symbol(
            _polygon([(-half, 0.0), (0.0, -half), (half, 0.0), (0.0, half)]),
            stroke=False,
            fill_col=True,
        )
    if pch == 19:  # 实心圆（填充 + 描边同色）
        path = skia.Path()
        path.addCircle(0.0, 0.0, half)
        return Symbol(path, stroke=True, fill_col=True)
    if pch == 20:  # 小实心圆
        path = skia.Path()
        path.addCircle(0.0, 0.0, SMALL * size)
        return Symbol(path, stroke=True, fill_col=True)
    if pch == 21:  # 圆：fill 填充 + col 描边
        path = skia.Path()
        path.addCircle(0.0, 0.0, half)
        return Symbol(path, stroke=True, fill_gpar=True)
    if pch == 22:  # 方（边长比 0 小，SQRC）
        d = RADIUS * SQRC * size
        return Symbol(_polygon([(-d, -d), (d, -d), (d, d), (-d, d)]), fill_gpar=True)
    if pch == 23:  # 菱形（DMDC）
        d = RADIUS * DMDC * size
        return Symbol(_polygon([(0.0, -d), (d, 0.0), (0.0, d), (-d, 0.0)]), fill_gpar=True)
    if pch == 24:  # 上三角
        return Symbol(up_triangle, fill_gpar=True)
    if pch == 25:  # 下三角
        return Symbol(down_triangle, fill_gpar=True)
    return None


def _triangle(size: float, *, down: bool) -> skia.Path:
    """R 的三角形：`TRC0/TRC1/TRC2` 三个常量把等边三角形摆正。"""
    radius = RADIUS * size
    r = TRC0 * radius
    yc = TRC2 * radius
    xc = TRC1 * radius
    if down:
        return _polygon([(0.0, r), (xc, -yc), (-xc, -yc)])
    return _polygon([(0.0, -r), (xc, yc), (-xc, yc)])

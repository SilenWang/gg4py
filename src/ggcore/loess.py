"""`ggcore.loess` —— R `stats::loess` 的两个拟合面（纯 numpy 移植）。

`stat_smooth` 的两种口径都来自这里：

- :func:`loess_fit`：**direct** 面（R `loess(..., control =
  loess.control(surface = "direct"))`）。逐点做局域多项式加权回归，等价于
  `loessf.f` 的 `lowesf()` / `ehg136()`；在 `newx` 上直接求值，可外推。
- :func:`loess_interpolate`：**interpolate** 面，R 的默认口径
  （`surface = "interpolate"`、`statistics = "approximate"`、
  `trace.hat = "exact"`）。照 `cloess` 的流程：

  1. 建一维 k-d 树（`ehg126` / `ehg124` / `ehg106` / `ehg125`），数据点被切进
     不超过 `floor(n · span · cell)` 个点的叶单元，每个内部节点贡献一个顶点；
  2. 在每个顶点上做一次局域多项式拟合，留下**值**与**一阶导**（`ehg139` /
     `ehg127`，即 `vval(0:1, ·)`）；
  3. 预测点落在哪个叶单元，就用该单元两个端点的 (值, 导) 做三次 Hermite
     插值（`ehg128`）——这就是 R 的 `lowese()`；
  4. 标准误：把每个顶点的「局域拟合行」（`lf` / `lq`）同样做 Hermite 插值，
     `se = s · sqrt(Σ L²/w)`（R 的 `loess_ise()` / `lowesl()` + `lowesl` 的
     `ehg191`）；
  5. 尺度 `s` 与自由度 `df`：`trL = tr(L)`（数据点上的插值矩阵），
     `delta1/delta2` 用 R 的经验公式（`ehg141` + 内嵌测试面 `ehg176`，
     `statistics = "approximate"`），`s = sqrt(Σ w r² / delta1)`、
     `df = delta1²/delta2`（`predict.loess(se = TRUE)$df`）。

口径细节（与 R 逐值对拍见 `tests/test_stat_r_parity.py`）：

- 数据范围外的预测点是 **NA**（R `predLoess()` 的 `inside` 判定），direct 面
  则可以外推；
- `cell` 缺省 0.2，R 传给 C 的是 `span * cell`（`loess.control(cell=)`）；
- 本模块只实现一维预测变量（`y ~ x`），与 `stat_smooth` 的上游约束一致。

边界：只 import 标准库 + numpy。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

__all__ = ["INTERPOLATE_CELL", "loess_fit", "loess_interpolate"]

#: R `loess.control()$cell` 的缺省值；真正传给 C 的是 `span * cell`。
INTERPOLATE_CELL = 0.2

#: `ehg141` 的经验系数表（`loessf.f` 的 data c，48 个值）。
_DELTA_COEFFICIENTS: tuple[float, ...] = (
    0.2971620,
    0.3802660,
    0.5886043,
    0.4263766,
    0.3346498,
    0.6271053,
    0.5241198,
    0.3484836,
    0.6687687,
    0.6338795,
    0.4076457,
    0.7207693,
    0.1611761,
    0.3091323,
    0.4401023,
    0.2939609,
    0.3580278,
    0.5555741,
    0.3972390,
    0.4171278,
    0.6293196,
    0.4675173,
    0.4699070,
    0.6674802,
    0.2848308,
    0.2254512,
    0.2914126,
    0.5393624,
    0.2517230,
    0.3898970,
    0.7603231,
    0.2969113,
    0.4740130,
    0.9664956,
    0.3629838,
    0.5348889,
    0.2075670,
    0.2822574,
    0.2369957,
    0.3911566,
    0.2981154,
    0.3623232,
    0.5508869,
    0.3501989,
    0.4371032,
    0.7002667,
    0.4291632,
    0.4930370,
)


def _tricube(u: np.ndarray) -> np.ndarray:
    """Cleveland 的 tricube 权 `(1 - |u|³)³`（|u| > 1 截断成 0）。"""
    u = np.minimum(np.abs(u), 1.0)
    return (1.0 - u**3) ** 3


def _design(dx: np.ndarray, degree: int) -> np.ndarray:
    """局域多项式的设计矩阵 `[1, dx, dx²]`（不缩放，与 R 的 C 实现一致）。"""
    return np.vstack([dx**power for power in range(degree + 1)]).T


def _local_fit(
    x: np.ndarray,
    weights: np.ndarray,
    point: float,
    *,
    span: float,
    degree: int,
) -> np.ndarray:
    """在 `point` 处的局域多项式拟合，返回系数行（长度 degree+1）。

    返回的 `rows[j]` 是第 j 个系数对**观测**的权重向量：`coef_j = rows[j] @ y`，
    也就是 R 的等效核（`lowesf()` / `lowsef()` 的 `L` 行）。邻域取最近
    `floor(n · span)` 个观测，带宽 = 第 q 近的距离，权重 = tricube。
    """
    n = x.size
    q = min(max(math.floor(span * n), 1), n)
    distance = np.abs(x - point)
    order = np.argsort(distance, kind="stable")
    bandwidth = float(distance[order[q - 1]])
    if bandwidth <= 0:
        positive = distance[distance > 0]
        bandwidth = float(positive.min()) if positive.size else 1.0
    local = weights * _tricube(distance / bandwidth)
    design = _design(x - point, degree)
    weighted = design * local[:, None]
    normal = design.T @ weighted
    try:
        solver = np.linalg.solve(normal, weighted.T)
    except np.linalg.LinAlgError:
        # 邻域里全同的 x（重复值）会让法方程奇异；R 的 QR/SVD 会丢掉这些方向，
        # 这里用伪逆复现「丢方向」的效果。
        solver = np.linalg.pinv(normal) @ weighted.T
    return solver


def loess_fit(
    x: np.ndarray,
    y: np.ndarray,
    weights: np.ndarray,
    *,
    span: float,
    degree: int,
    newx: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """局域多项式回归（Cleveland 的 loess，"direct" 口径）。

    返回 `(在 newx 上的拟合值, L)`，`L[j, i]` 是第 j 个预测点对第 i 个观测的
    等效权重（`fit_j = Σ_i L[j,i] · y_i`）。锚点落在数据范围外也可以外推
    （与 R `surface = "direct"` 一致）。
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    newx = np.asarray(newx, dtype=np.float64)
    n = x.size
    fits = np.empty(newx.size, dtype=np.float64)
    kernel = np.empty((newx.size, n), dtype=np.float64)
    for j, point in enumerate(newx.tolist()):
        solver = _local_fit(x, weights, point, span=span, degree=degree)
        kernel[j] = solver[0]
        fits[j] = float(solver[0] @ y)
    return fits, kernel


# ---------------------------------------------------------------------------
# k-d 树（一维）：ehg126 / ehg124 / ehg106 / ehg125
# ---------------------------------------------------------------------------


def _partition(x: np.ndarray, pi: list[int], il: int, ir: int, k: int) -> None:
    """`ehg106()`：Floyd–Rivest（CACM Algorithm 489）部分排序。

    原地重排 `pi[il..ir]`，使 `x[pi[k]]` 是这一段里的第 k 小值。
    """
    left, right = il, ir
    while left < right:
        pivot = x[pi[k]]
        i, j = left, right
        pi[left], pi[k] = pi[k], pi[left]
        if pivot < x[pi[right]]:
            pi[left], pi[right] = pi[right], pi[left]
        while i < j:
            pi[i], pi[j] = pi[j], pi[i]
            i += 1
            j -= 1
            while x[pi[i]] < pivot:
                i += 1
            while pivot < x[pi[j]]:
                j -= 1
        if x[pi[left]] == pivot:
            pi[left], pi[j] = pi[j], pi[left]
        else:
            j += 1
            pi[right], pi[j] = pi[j], pi[right]
        if j <= k:
            left = j + 1
        if k <= j:
            right = j - 1


class _Tree:
    """一维 k-d 树：顶点坐标、切分维/值、子结点指针、每个单元的包围顶点。

    `c[j] = (lower, upper)` 是第 j 个单元两个端点的顶点下标；`a[j] != 0` 的单元
    是内部结点（`lo[j]` / `hi[j]` 是子结点），否则是叶单元。
    """

    __slots__ = ("cells", "hi", "lo", "split", "vertices", "xi")

    def __init__(self, x: np.ndarray, *, span: float, cell: float) -> None:
        self.vertices: list[float] = []
        self.split: list[int] = []
        self.xi: list[float] = []
        self.lo: list[int] = []
        self.hi: list[int] = []
        self.cells: list[tuple[int, int]] = []
        self._build(np.asarray(x, dtype=np.float64), span=span, cell=cell)

    def _build(self, x: np.ndarray, *, span: float, cell: float) -> None:
        n = x.size
        alpha = float(np.min(x))
        beta = float(np.max(x))
        # `ehg126()`：包围盒向外扩 0.5%，避免顶点正好落在数据上。
        margin = 0.005 * max(beta - alpha, 1e-10 * max(abs(alpha), abs(beta)) + 1e-30)
        self.vertices = [alpha - margin, beta + margin]
        # 叶单元的阈值：`ntol = floor(n · span · cell)`（R 传给 C 的是 span*cell）。
        tolerance = math.floor(n * span * cell)
        permutation = list(range(n))
        self.lo, self.hi, self.cells = [0], [n - 1], [(0, 1)]
        p = 0
        while p < len(self.lo):
            start, stop = self.lo[p], self.hi[p]
            if (stop - start + 1) <= tolerance:
                self._leaf()
            else:
                median = (start + stop) // 2
                _partition(x, permutation, start, stop, median)
                # `ehg124()` 的平局修正：切分点与相邻值相同时左右挪一格。
                offset = 0
                while start <= median + offset < stop:
                    if offset < 0:
                        low = start
                        high = median + offset
                        check = high
                    else:
                        low = median + offset + 1
                        check = low
                        high = stop
                    _partition(x, permutation, low, high, check)
                    if x[permutation[median + offset]] == x[permutation[median + offset + 1]]:
                        offset = -offset
                        if offset >= 0:
                            offset += 1
                    else:
                        median += offset
                        break
                value = float(x[permutation[median]])
                lower_vertex, upper_vertex = self.cells[p]
                if self.vertices[lower_vertex] == value or self.vertices[upper_vertex] == value:
                    self._leaf()
                else:
                    self.split.append(1)
                    self.xi.append(value)
                    vertex = len(self.vertices)
                    self.vertices.append(value)
                    # `ehg125()`（d = 1）：新顶点复制下界顶点，只把坐标换成切分值。
                    self.cells[p] = (lower_vertex, vertex)
                    left = len(self.lo)
                    self.lo.append(start)
                    self.hi.append(median)
                    right = len(self.lo)
                    self.lo.append(median + 1)
                    self.hi.append(stop)
                    self.lo[p], self.hi[p] = left, right
                    self.cells.append((lower_vertex, vertex))
                    self.cells.append((vertex, upper_vertex))
            p += 1

    def _leaf(self) -> None:
        self.split.append(0)
        self.xi.append(0.0)

    def descend(self, point: float) -> int:
        """`ehg128()` 的第一段：从根走到包含 `point` 的叶单元。"""
        j = 0
        while self.split[j] != 0:
            j = self.lo[j] if point <= self.xi[j] else self.hi[j]
        return j


def _hermite_weights(tree: _Tree, point: float) -> tuple[int, int, float, np.ndarray]:
    """一个预测点的 Hermite 基：`(lower, upper, 区间宽度, [φ0, φ1, ψ0, ψ1])`。"""
    cell = tree.cells[tree.descend(point)]
    lower, upper = cell
    width = tree.vertices[upper] - tree.vertices[lower]
    h = (point - tree.vertices[lower]) / width
    basis = np.array(
        [
            (1 - h) ** 2 * (1 + 2 * h),
            h**2 * (3 - 2 * h),
            h * (1 - h) ** 2,
            h**2 * (h - 1),
        ],
        dtype=np.float64,
    )
    return lower, upper, width, basis


def _hermite(tree: _Tree, point: float, values: np.ndarray, slopes: np.ndarray) -> float:
    """三次 Hermite 插值（`ehg128()` 在 d = 1 时的展开）。"""
    lower, upper, width, basis = _hermite_weights(tree, point)
    return float(
        basis[0] * values[lower]
        + basis[1] * values[upper]
        + width * (basis[2] * slopes[lower] + basis[3] * slopes[upper])
    )


def _hermite_rows(tree: _Tree, point: float, rows0: np.ndarray, rows1: np.ndarray) -> np.ndarray:
    """把顶点的「拟合行」按同一个 Hermite 基插值成一行（`ehg191()` 的等价物）。"""
    lower, upper, width, basis = _hermite_weights(tree, point)
    return (
        basis[0] * rows0[lower]
        + basis[1] * rows0[upper]
        + width * (basis[2] * rows1[lower] + basis[3] * rows1[upper])
    )


# ---------------------------------------------------------------------------
# statistics = "approximate" 的 delta（ehg141 / lowesa / ehg176）
# ---------------------------------------------------------------------------


def _ehg176(z: float) -> float:
    """`ehg176()`：R 内嵌的固定测试面，`ehg141` 的经验修正因子要用它。

    这一小段是 `loessf.f` 里写死的一维 k-d 树（10 个顶点、17 个单元）与它的
    顶点系数；算法与 :func:`_hermite` 相同。
    """
    split = (1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0)
    hi = (2, 4, 6, 8, 10, 12, 14, 0, 0, 0, 0, 0, 0, 0, 16, 0, 0)
    lo = (1, 3, 5, 7, 9, 11, 13, 0, 0, 0, 0, 0, 0, 0, 15, 0, 0)
    xi = (
        0.3705,
        0.2017,
        0.5591,
        0.1204,
        0.2815,
        0.4536,
        0.7132,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.8751,
        0.0,
        0.0,
    )
    lower = (0, 0, 2, 0, 3, 2, 4, 0, 5, 3, 6, 2, 7, 4, 8, 8, 9)
    upper = (1, 2, 1, 3, 2, 4, 1, 5, 3, 6, 2, 7, 4, 8, 1, 9, 1)
    vertices = (-5e-3, 1.005, 0.3705, 0.2017, 0.5591, 0.1204, 0.2815, 0.4536, 0.7132, 0.8751)
    values = (
        -0.090572,
        -0.010856,
        -0.053718,
        0.026152,
        -0.058387,
        0.095807,
        -0.031926,
        -0.064170,
        -0.020636,
        0.040172,
    )
    slopes = (
        4.4844,
        -0.7736,
        -0.3495,
        -0.7286,
        0.1611,
        -0.7978,
        -0.4457,
        0.032813,
        0.3350,
        -0.041032,
    )
    j = 0
    while split[j] != 0:
        j = lo[j] if z <= xi[j] else hi[j]
    width = vertices[upper[j]] - vertices[lower[j]]
    h = (z - vertices[lower[j]]) / width
    return float(
        (1 - h) ** 2 * (1 + 2 * h) * values[lower[j]]
        + h**2 * (3 - 2 * h) * values[upper[j]]
        + width * (h * (1 - h) ** 2 * slopes[lower[j]] + h**2 * (h - 1) * slopes[upper[j]])
    )


def _ehg141(trace: float, n: int, degree: int, tau: int) -> tuple[float, float]:
    """`ehg141()`：`statistics = "approximate"` 的 delta1 / delta2。"""
    dk = degree + 1 if degree == 1 else (1 if degree == 0 else 3)
    correlation = math.sqrt(tau / n)
    denominator = 1 - correlation
    if trace <= 0 or denominator == 0:
        return float("nan"), float("nan")
    z = (math.sqrt(tau / trace) - correlation) / denominator
    z = min(1.0, max(0.0, z))
    correction = math.exp(_ehg176(z))
    index = 1 + 3 * (4 * (degree - 1))  # d = 1 → min(d, 4) - 1 = 0
    c1, c2, c3 = _DELTA_COEFFICIENTS[index - 1 : index + 2]
    delta1 = n - trace * math.exp(c1 * z**c2 * (1 - z) ** c3 * correction)
    c1, c2, c3 = _DELTA_COEFFICIENTS[index + 23 : index + 26]
    delta2 = n - trace * math.exp(c1 * z**c2 * (1 - z) ** c3 * correction)
    del dk
    return delta1, delta2


def _lowesa(trace: float, n: int, degree: int) -> tuple[float, float]:
    """`lowesa()`：在 degree = 1 / 2 两个经验公式之间按 `tau` 线性插值。"""
    tau = 3 if degree == 2 else 2
    d1_low, d2_low = _ehg141(trace, n, 1, tau)
    d1_high, d2_high = _ehg141(trace, n, 2, tau)
    alpha = (tau - 2) / (3 - 2)
    return (
        (1 - alpha) * d1_low + alpha * d1_high,
        (1 - alpha) * d2_low + alpha * d2_high,
    )


# ---------------------------------------------------------------------------
# interpolate 面
# ---------------------------------------------------------------------------


def loess_interpolate(
    x: np.ndarray,
    y: np.ndarray,
    weights: np.ndarray,
    *,
    span: float,
    degree: int,
    newx: np.ndarray,
    cell: float = INTERPOLATE_CELL,
    se: bool = True,
) -> dict[str, Any]:
    """R 默认口径（`surface = "interpolate"`）的 loess 拟合与标准误。

    返回 `{"fit", "se", "df", "s", "trace", "vertices", "cells"}`：
    `fit` / `se` 在 `newx` 上；数据范围外的位置是 NaN（R `predLoess()` 的
    `inside` 判定）。`se=False` 时 `se` 为 None。
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    newx = np.asarray(newx, dtype=np.float64)
    n = x.size
    tree = _Tree(x, span=span, cell=cell)
    # 每个顶点一次局域拟合：值 / 一阶导 / 两条等效核行（`ehg139()`）。
    vertex_values = np.empty(len(tree.vertices), dtype=np.float64)
    vertex_slopes = np.empty(len(tree.vertices), dtype=np.float64)
    rows0 = np.empty((len(tree.vertices), n), dtype=np.float64)
    rows1 = np.empty((len(tree.vertices), n), dtype=np.float64)
    for j, point in enumerate(tree.vertices):
        solver = _local_fit(x, weights, point, span=span, degree=degree)
        rows0[j] = solver[0]
        rows1[j] = solver[1] if degree >= 1 else 0.0
        vertex_values[j] = float(rows0[j] @ y)
        vertex_slopes[j] = float(rows1[j] @ y)

    # 数据点上的拟合值（`lowese()`）→ 残差 → 尺度 `s`。
    fitted = np.array([_hermite(tree, float(point), vertex_values, vertex_slopes) for point in x])
    residual = y - fitted
    sum_squares = float(np.sum(weights * residual**2))
    # trL = tr(L)：数据点上的插值矩阵对角（R 的 `diagl` / `lowesl` 口径）。
    trace = 0.0
    for index, point in enumerate(x.tolist()):
        lower, upper, width, basis = _hermite_weights(tree, point)
        trace += float(
            basis[0] * rows0[lower, index]
            + basis[1] * rows0[upper, index]
            + width * (basis[2] * rows1[lower, index] + basis[3] * rows1[upper, index])
        )
    delta1, delta2 = _lowesa(trace, n, degree)
    # R 在 delta 为负时只警告（"computed delta was negative"）并给出 NaN 标准误；
    # 这里同样降级成 NaN，不打断整张图的构建。
    scale = math.sqrt(sum_squares / delta1) if delta1 > 0 else float("nan")
    df = delta1 * delta1 / delta2 if delta2 > 0 else float("nan")

    inside = (newx >= float(np.min(x))) & (newx <= float(np.max(x)))
    fit = np.full(newx.size, np.nan, dtype=np.float64)
    fit[inside] = [
        _hermite(tree, float(point), vertex_values, vertex_slopes) for point in newx[inside]
    ]
    ses = None
    if se:
        ses = np.full(newx.size, np.nan, dtype=np.float64)
        for position in np.flatnonzero(inside):
            row = _hermite_rows(tree, float(newx[position]), rows0, rows1)
            with np.errstate(divide="ignore", invalid="ignore"):
                ses[position] = scale * math.sqrt(float(np.sum(row**2 / weights)))
    return {
        "fit": fit,
        "se": ses,
        "df": df,
        "s": scale,
        "trace": trace,
        "vertices": np.asarray(tree.vertices, dtype=np.float64),
        "cells": tuple(tree.cells),
    }

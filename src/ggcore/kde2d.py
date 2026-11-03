"""`MASS::kde2d()` 的 numpy 复刻（`stat_density_2d` 用）。

上游口径（MASS 7.3-x）：

```r
kde2d <- function(x, y, h, n = 25, lims = c(range(x), range(y))) {
  gx <- seq.int(lims[1], lims[2], length.out = n)
  gy <- seq.int(lims[3], lims[4], length.out = n)
  h <- h / 4
  ax <- outer(gx, x, "-") / h[1]
  ay <- outer(gy, y, "-") / h[2]
  z <- tcrossprod(matrix(dnorm(ax), , nx), matrix(dnorm(ay), , nx)) /
       (nx * h[1] * h[2])
  list(x = gx, y = gy, z = z)
}
```

带宽估计照 `precompute_2d_bw()`（ggplot2 4.0.3）：

- 缺省 `h <- c(MASS::bandwidth.nrd(x), MASS::bandwidth.nrd(y))`；
- 某一维的 nrd 为 0（IQR = 0）且观测数 > 1 时换成 `stats::bw.nrd0(x) * 4`；
- `adjust`（长度 2 或标量）乘在带宽上。

`bandwidth.nrd` 与 `bw.nrd0` 都是 R 统计口径：四分位用 type 7（线性插值），
方差用 `n - 1` 分母。不引 scipy。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from ggcore.build import BuildError

__all__ = ["bandwidth_nrd", "bw_nrd0", "kde2d", "precompute_2d_bw"]

_SQRT_2PI = float(np.sqrt(2.0 * np.pi))


def _dnorm(values: np.ndarray) -> np.ndarray:
    """标准正态密度 `dnorm()`。"""
    return np.exp(-0.5 * np.asarray(values, dtype=np.float64) ** 2) / _SQRT_2PI


def bandwidth_nrd(x: np.ndarray) -> float:
    """`MASS::bandwidth.nrd()`：`4 * 1.06 * min(sd, IQR/1.34) * n^(-1/5)`。"""
    values = np.asarray(x, dtype=np.float64)
    values = values[~np.isnan(values)]
    if values.size == 0:
        return float("nan")
    quantiles = np.quantile(values, [0.25, 0.75], method="linear")
    spread = float(quantiles[1] - quantiles[0]) / 1.34
    if values.size < 2:
        return float("nan")
    sd = float(np.sqrt(np.var(values, ddof=1)))
    return 4.0 * 1.06 * min(sd, spread) * values.size ** (-0.2)


def bw_nrd0(x: np.ndarray) -> float:
    """`stats::bw.nrd0()`：`0.9 * min(sd, IQR/1.34) * n^(-1/5)`（含退化分支）。"""
    values = np.asarray(x, dtype=np.float64)
    values = values[~np.isnan(values)]
    if values.size < 2:
        raise BuildError("bw.nrd0 至少需要 2 个观测")
    hi = float(np.sqrt(np.var(values, ddof=1)))
    quantiles = np.quantile(values, [0.25, 0.75], method="linear")
    lo = min(hi, float(quantiles[1] - quantiles[0]) / 1.34)
    if lo == 0.0:
        lo = hi
        if lo == 0.0:
            lo = abs(float(values[0]))
            if lo == 0.0:
                lo = 1.0
    return 0.9 * lo * values.size ** (-0.2)


def precompute_2d_bw(
    x: np.ndarray,
    y: np.ndarray,
    *,
    h: Any = None,
    adjust: Any = 1.0,
) -> np.ndarray:
    """`precompute_2d_bw()`：解析 / 校验 2D 带宽（`h` 长度 2、必须为正）。"""
    if h is None:
        first = bandwidth_nrd(x)
        second = bandwidth_nrd(y)
        heights = [first, second]
        if heights[0] == 0 and np.asarray(x).size > 1:
            heights[0] = bw_nrd0(x) * 4
        if heights[1] == 0 and np.asarray(y).size > 1:
            heights[1] = bw_nrd0(y) * 4
        adjustments = np.asarray(_dual(adjust, "adjust"), dtype=np.float64)
        if adjustments.size == 1:
            adjustments = np.repeat(adjustments, 2)
        heights = np.asarray(heights, dtype=np.float64) * adjustments
    else:
        heights = np.asarray(_dual(h, "h"), dtype=np.float64)
        if heights.size != 2:
            raise BuildError(f"stat_density_2d 的 h 必须是长度 2 的数值，收到 {h!r}")
    if not np.all(np.isfinite(heights)) or np.any(heights <= 0):
        raise BuildError(
            f"stat_density_2d 的带宽 h 必须是正数，收到 {h!r}；请显式给 h = c(…) 或调整数据"
        )
    return heights


def _dual(value: Any, name: str) -> Sequence[float]:
    """R 的 `dual_param()` 的数值版：标量 / 长度 2 的序列 → 长度 1 或 2。"""
    if isinstance(value, (int, float, np.integer, np.floating)):
        return [float(value)]
    values = list(np.asarray(value, dtype=np.float64).ravel())
    if len(values) not in (1, 2):
        raise BuildError(f"stat_density_2d 的 {name} 必须是标量或长度 2 的数值，收到 {value!r}")
    return values


def kde2d(
    x: np.ndarray,
    y: np.ndarray,
    h: Any,
    n: int = 25,
    lims: Sequence[float] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """`MASS::kde2d()`：返回 `(gx, gy, z)`，`z[i, j]` 对应 `(gx[i], gy[j])`。"""
    x_values = np.asarray(x, dtype=np.float64)
    y_values = np.asarray(y, dtype=np.float64)
    if x_values.size != y_values.size:
        raise BuildError("kde2d 的 x / y 长度必须一致")
    if x_values.size == 0:
        raise BuildError("kde2d 需要至少一个观测")
    if lims is None:
        limits = [
            float(np.min(x_values)),
            float(np.max(x_values)),
            float(np.min(y_values)),
            float(np.max(y_values)),
        ]
    else:
        limits = [float(value) for value in lims]
        if len(limits) != 4:
            raise BuildError("kde2d 的 lims 必须是长度 4 的数值")
    bandwidth = np.asarray(h, dtype=np.float64)
    if bandwidth.size != 2 or np.any(bandwidth <= 0) or not np.all(np.isfinite(bandwidth)):
        raise BuildError(f"kde2d 的 h 必须是两个正有限数，收到 {h!r}")
    count = int(n)
    if count < 1:
        raise BuildError(f"kde2d 的 n 至少是 1，收到 {n!r}")
    gx = np.linspace(limits[0], limits[1], count)
    gy = np.linspace(limits[2], limits[3], count)
    # 上游在 kde2d() 里把 h 再除以 4（`h <- h / 4`），不要在外层重复。
    hx = float(bandwidth[0]) / 4.0
    hy = float(bandwidth[1]) / 4.0
    ax = (gx[:, None] - x_values[None, :]) / hx
    ay = (gy[:, None] - y_values[None, :]) / hy
    z = (_dnorm(ax) @ _dnorm(ay).T) / (x_values.size * hx * hy)
    return gx, gy, z

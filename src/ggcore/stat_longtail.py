"""`ggcore.stat_longtail` —— stat 长尾 B（M2-6）：分布 / 汇总 / 回归 14 个导出。

`stat.py` 只放 M1-8 的 `bin` / `count` / `boxplot` / `smooth` / `align`；
本模块补齐 4.0.3 NAMESPACE 里剩下的这一组，派发仍从
:func:`ggcore.stat.compute_stat` 进来（名字在 :data:`LONGTAIL_STATS` 里就转到这里）。

```
compute_longtail(name, table, params, scales=…, raw=…)
```

口径逐条照上游（pin `cc1444c1`，v4.0.3）：

| stat | 上游文件 | 要点 |
| --- | --- | --- |
| `qq` / `qq_line` | `stat-qq.R` | `ppoints()`、`distribution` + `dparams`、`line.p` |
| `ecdf` | `stat-ecdf.R` | `wecdf()` 的阶梯 + `pad` 的 ±Inf；`weight` 支持 |
| `ellipse` | `stat-ellipse.R` | `cov.wt` / `MASS::cov.trob`（`type="t"`）/ `euclid` |
| `quantile` | `stat-quantilemethods.R` | 线性分位回归（`quantreg::rq` 的 `y ~ x`） |
| `summary` / `summary_bin` | `stat-summary*.R` | `fun` / `fun.min` / `fun.max` / `fun.data` |
| `sum` | `stat-sum.R` | 按 `x`/`y`/`group`（及映射的其余美学）加权计数 |
| `unique` | `stat-unique.R` | 去重行 |
| `density` | `stat-density.R` | `stats::density()` 的 bin + FFT 算法，逐值对齐 |
| `function` | `stat-function.R` | `fun` / `xlim` / `n` / `args`，标度反变换 |
| `connect` | `stat-connect.R` | `connection` 矩阵的折线插值 |
| `manual` | `stat-manual.R` | 用户函数逐组改数据 |
| `spoke` | `geom-spoke.R` | 4.0.3 里已是 `deprecate_stop()` → 报错指向 `geom_spoke()` |
| `ydensity` | `stat-ydensity.R` | 小提琴密度 + `violinwidth` + 分位线 |

几条贯穿全模块的口径：

- **参数校验在前**：不认识的取值一律 :class:`BuildError` 并点名上游选项，
  不静默退化（与 M1-8 的 `stat_smooth` 同一风格）。
- **`fun` 系列**（`stat_summary`）：既收 Python 可调用，也收字符串别名
  （`mean` / `median` / `sd` / `min` / `max` / `sum` / `length` / `first` / `last`）；
  `fun.data` 另收 `mean_se` / `mean_cl_normal` / `mean_sdl` / `median_hilow`。
- **`distribution`**（`stat_qq`）：字符串别名 `norm` / `t` / `unif` / `exp` /
  `logis` / `cauchy`，或任意 `p → quantile` 的可调用；分布参数走 `dparams`。
- **浮点**：R 的 `stats::density()` 走的是「bin + FFT + 线性插值」，
  逐值差 ~1e-4；这里照 `massdist.c` 的 `BinDist` 与 `density.default()` 的
  同一套参数（`ext = 4`、`n = max(n, 512)`）重写，才能保持 1e-9 的对拍口径。

边界：只 import 标准库 + numpy + ggcore；不碰 IR / 标度映射 / 坐标 / 位置。
"""

from __future__ import annotations

import math
import warnings as _warnings
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np

from ggcore.build import BuildError, BuildWarning
from ggcore.data import Column, ColumnTable
from ggcore.stat import (
    _betai,
    _bool_column,
    _column_values,
    _compute_bins,
    _compute_panel,
    _dimension,
    _flip_table,
    _float_column,
    _has_flipped_aes,
    _items,
    _numeric,
    _slice,
    _str_column,
    t_quantile,
)

__all__ = [
    "DEFAULT_AES",
    "DROPPED_AES",
    "LONGTAIL_STATS",
    "NON_MISSING",
    "REQUIRED",
    "compute_longtail",
    "flipped_for",
]

#: 本模块实现的 stat（名字 = 注册表里的 `Stat.name`）。
LONGTAIL_STATS: tuple[str, ...] = (
    "qq",
    "qq_line",
    "ecdf",
    "ellipse",
    "quantile",
    "summary",
    "summary_bin",
    "sum",
    "unique",
    "density",
    "function",
    "connect",
    "manual",
    "spoke",
    "ydensity",
)

#: 上游 `Stat$compute_layer()` 的 `required_aes`（同一元组里的名字 = 二选一）。
REQUIRED: Mapping[str, tuple[str, ...]] = {
    "qq": ("sample",),
    "qq_line": ("sample",),
    "ecdf": ("x", "y"),
    "ellipse": ("x", "y"),
    "quantile": ("x", "y"),
    "summary": ("x", "y"),
    "summary_bin": ("x", "y"),
    "sum": ("x", "y"),
    "unique": (),
    "density": ("x", "y"),
    "function": (),
    "connect": ("x", "y"),
    "manual": (),
    "spoke": (),
    "ydensity": ("x", "y"),
}

#: `Stat*$non_missing_aes`（`remove_missing()` 也看这些列）。
NON_MISSING: Mapping[str, tuple[str, ...]] = {
    "ellipse": ("weight",),
    "ydensity": ("weight",),
}

#: `Stat*$dropped_aes`：组内变化时丢弃但不告警的列。
DROPPED_AES: Mapping[str, frozenset[str]] = {
    "qq_line": frozenset({"sample"}),
    "ecdf": frozenset({"weight"}),
    "ellipse": frozenset({"weight"}),
    "quantile": frozenset({"weight"}),
    "sum": frozenset({"weight"}),
    "density": frozenset({"weight"}),
    "ydensity": frozenset({"weight"}),
}

#: `Stat*$default_aes` 里「stat 输出列 → 美学」的部分（常量项在 build.py 里不建列）。
#: 键序 = 上游 `aes()` 的顺序；`build._STAT_DEFAULT_AES` 直接合并这份表。
DEFAULT_AES: Mapping[str, tuple[tuple[str, str], ...]] = {
    "qq": (("x", "theoretical"), ("y", "sample")),
    "ecdf": (("x", "ecdf"), ("y", "ecdf")),
    "density": (("x", "density"), ("y", "density")),
    "sum": (("size", "n"),),
}

_EMPTY = ColumnTable()


# ---------------------------------------------------------------------------
# 派发
# ---------------------------------------------------------------------------


def flipped_for(name: str, table: ColumnTable, params: Mapping[str, Any], raw: Any) -> bool:
    """各 stat 的 `setup_params()` 里 `has_flipped_aes()` 的开关。"""
    if name == "ecdf" or name == "density":
        return _has_flipped_aes(
            table, params, raw, main_is_orthogonal=False, main_is_continuous=True
        )
    if name == "ydensity":
        return _has_flipped_aes(table, params, raw, main_is_orthogonal=True, group_has_equal=True)
    if name in ("summary", "summary_bin"):
        return _has_flipped_aes(table, params, raw)
    if name == "connect":
        return _has_flipped_aes(table, params, raw, ambiguous=True)
    return False


def compute_longtail(
    name: str,
    table: ColumnTable,
    params: Mapping[str, Any],
    *,
    scales: Any = None,
    raw: ColumnTable | None = None,
) -> ColumnTable:
    """按名字算一个长尾 stat；`table` 已经过 `remove_missing()`。"""
    flipped = flipped_for(name, table, params, raw)
    if name == "qq":
        return _stat_qq(table, params)
    if name == "qq_line":
        return _stat_qq_line(table, params, scales=scales)
    if name == "ecdf":
        return _stat_ecdf(table, params, flipped=flipped)
    if name == "ellipse":
        return _stat_ellipse(table, params)
    if name == "quantile":
        return _stat_quantile(table, params)
    if name == "summary":
        return _stat_summary(table, params, flipped=flipped)
    if name == "summary_bin":
        return _stat_summary_bin(table, params, scales=scales, flipped=flipped)
    if name == "sum":
        return _stat_sum(table, params)
    if name == "unique":
        return _stat_unique(table)
    if name == "density":
        return _stat_density(table, params, scales=scales, flipped=flipped)
    if name == "function":
        return _stat_function(table, params, scales=scales)
    if name == "connect":
        return _stat_connect(table, params, flipped=flipped)
    if name == "manual":
        return _stat_manual(table, params)
    if name == "spoke":
        raise BuildError(
            "stat_spoke() 在 ggplot2 4.0.3 里已弃用（lifecycle::deprecate_stop），"
            "请改用 geom_spoke()（M2-7 的另一组；角度/半径是 geom 的参数）"
        )
    if name == "ydensity":
        return _stat_ydensity(table, params, scales=scales, flipped=flipped)
    raise AssertionError(name)  # pragma: no cover - LONGTAIL_STATS 已经拦住了


# ---------------------------------------------------------------------------
# 通用小工具
# ---------------------------------------------------------------------------


def _param(params: Mapping[str, Any], dotted: str, *aliases: str) -> Any:
    """读一个 R 风格的点号参数（Python 里也可以写成下划线）。

    `stat_summary(fun.data = ..., fun.args = ...)` 在 R 里是点号；Python 的关键字
    写不了点，所以 `fun_data` / `fun_args` 是同一份参数的别名。
    """
    if dotted in params:
        return params[dotted]
    for name in (dotted.replace(".", "_"), *aliases):
        if name in params:
            return params[name]
    return None


def _weight_values(table: ColumnTable) -> np.ndarray | None:
    if "weight" not in table:
        return None
    values = np.asarray(_column_values(table.column("weight")), dtype=np.float64)
    return values


def _r_quantile(values: np.ndarray, probs: Sequence[float]) -> np.ndarray:
    """R 的 `quantile(type = 7)`（`stats::quantile` 的缺省）。"""
    return np.quantile(np.asarray(values, dtype=np.float64), list(probs), method="linear")


def _ppoints(n: int) -> np.ndarray:
    """R 的 `stats::ppoints(n)`：`a = 3/8`（n ≤ 10）或 `1/2`。"""
    a = 3.0 / 8.0 if n <= 10 else 0.5
    return (np.arange(1, n + 1, dtype=np.float64) - a) / (n + 1.0 - 2.0 * a)


def _r_seq_length(start: float, stop: float, length: int) -> np.ndarray:
    """R 的 `seq(from, to, length.out = n)`（`length = 1` 时返回 `from`）。"""
    if length <= 0:
        raise BuildError("seq 的 length.out 必须是正整数")
    if length == 1:
        return np.array([float(start)])
    step = (float(stop) - float(start)) / (length - 1)
    out = float(start) + np.arange(length, dtype=np.float64) * step
    out[-1] = float(stop)
    return out


def _median(values: np.ndarray) -> float:
    return float(np.median(values))


def _variance(values: np.ndarray) -> float:
    if values.size < 2:
        return math.nan
    return float(np.var(values, ddof=1))


# ---------------------------------------------------------------------------
# 分布：`p → 分位数`（stat_qq 的 `distribution` 参数）
# ---------------------------------------------------------------------------


def _norm_ppf(p: np.ndarray) -> np.ndarray:
    """标准正态分位数（Acklam 近似 + 一步 Newton，相对误差 ~1e-15）。"""
    p = np.asarray(p, dtype=np.float64)
    out = np.empty_like(p)
    a = (
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    )
    plow = 0.02425
    phigh = 1.0 - plow
    lower = p < plow
    upper = p > phigh
    middle = ~lower & ~upper
    if lower.any():
        q = np.sqrt(-2.0 * np.log(p[lower]))
        out[lower] = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    if upper.any():
        q = np.sqrt(-2.0 * np.log1p(-p[upper]))
        out[upper] = -(
            (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
        )
    if middle.any():
        q = p[middle] - 0.5
        r = q * q
        out[middle] = (
            (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q
        ) / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    # 一步 Halley 修正（`erfc` 是标准库的，精度到机器精度）。
    finite = np.isfinite(out)
    if finite.any():
        x = out[finite]
        target = p[finite]
        cdf = 0.5 * np.array([math.erfc(-float(value) / math.sqrt(2.0)) for value in x])
        pdf = np.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)
        with np.errstate(divide="ignore", invalid="ignore"):
            delta = (cdf - target) / pdf
        out[finite] = x - delta
    out[p <= 0.0] = -math.inf
    out[p >= 1.0] = math.inf
    return out


def _t_ppf(p: float, df: float) -> float:
    """`qt(p, df)`：`ggcore.stat.t_quantile()` 只给上尾（`qt(0.975, df)` 用），
    这里按对称性补下尾（`qt(p) = -qt(1-p)`）。"""
    if p == 0.5:
        return 0.0
    if p < 0.5:
        return -t_quantile(1.0 - p, df)
    return t_quantile(p, df)


def _qbeta(p: float, a: float, b: float) -> float:
    """`stats::qbeta()` 的二分反解（`qf()` / 椭圆半径用；p 在 (0,1)）。"""
    low, high = 0.0, 1.0
    for _ in range(200):
        mid = (low + high) / 2.0
        if _betai(a, b, mid) < p:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def _qf(p: float, d1: float, d2: float) -> float:
    """F 分布分位：`x = qbeta(p, d1/2, d2/2)`，`qf = (d2/d1) * x/(1-x)`。"""
    x = _qbeta(p, d1 / 2.0, d2 / 2.0)
    return (d2 / d1) * x / (1.0 - x)


_DISTRIBUTION_ALIASES = {
    "norm": "norm",
    "qnorm": "norm",
    "t": "t",
    "qt": "t",
    "unif": "unif",
    "qunif": "unif",
    "exp": "exp",
    "qexp": "exp",
    "logis": "logis",
    "qlogis": "logis",
    "cauchy": "cauchy",
    "qcauchy": "cauchy",
}


def _distribution_quantile(
    distribution: Any, probs: np.ndarray, dparams: Mapping[str, Any]
) -> np.ndarray:
    """`distribution(p = probs, !!!dparams)`：别名或可调用。"""
    if callable(distribution):
        values = distribution(probs, **dict(dparams))
        return np.asarray(values, dtype=np.float64)
    if not isinstance(distribution, str):
        raise BuildError(
            f"stat_qq 的 distribution 必须是字符串别名或可调用，收到 {type(distribution).__name__}"
        )
    name = _DISTRIBUTION_ALIASES.get(distribution.lower())
    if name is None:
        raise BuildError(
            f"stat_qq 的 distribution 不认识：{distribution!r}；"
            f"可用别名：{', '.join(sorted(set(_DISTRIBUTION_ALIASES)))}，或传可调用"
        )
    params = dict(dparams)

    def check(allowed: set[str]) -> None:
        unknown = sorted(set(params) - allowed)
        if unknown:
            raise BuildError(
                f"stat_qq 的 distribution = {distribution!r} 不认识 dparams："
                f"{', '.join(unknown)}（可用：{', '.join(sorted(allowed))}）"
            )

    if name == "norm":
        check({"mean", "sd"})
        out = _norm_ppf(probs)
        mean = float(params.get("mean", 0.0))
        sd = float(params.get("sd", 1.0))
        return mean + sd * out
    if name == "t":
        check({"df"})
        df = float(params.get("df", 1.0))
        return np.array([_t_ppf(float(value), df) for value in probs])
    if name == "unif":
        check({"min", "max"})
        low = float(params.get("min", 0.0))
        high = float(params.get("max", 1.0))
        return low + (high - low) * probs
    if name == "exp":
        check({"rate"})
        rate = float(params.get("rate", 1.0))
        return -np.log1p(-probs) / rate
    if name == "logis":
        check({"location", "scale"})
        location = float(params.get("location", 0.0))
        scale = float(params.get("scale", 1.0))
        return location + scale * np.log(probs / (1.0 - probs))
    check({"location", "scale"})
    location = float(params.get("location", 0.0))
    scale = float(params.get("scale", 1.0))
    return location + scale * np.tan(math.pi * (probs - 0.5))


def _sorted_sample(table: ColumnTable, stat: str) -> np.ndarray:
    if "sample" not in table:
        raise BuildError(f"stat_{stat} 需要 sample 美学（`aes(sample = …)`）")
    values = _numeric(table.column("sample"))
    return np.sort(values)


def _quantile_probs(params: Mapping[str, Any], n: int, stat: str) -> np.ndarray:
    quantiles = params.get("quantiles")
    if quantiles is None:
        return _ppoints(n)
    values = np.asarray(quantiles, dtype=np.float64)
    if values.ndim != 1:
        raise BuildError(f"stat_{stat} 的 quantiles 必须是一维序列")
    if values.size != n:
        raise BuildError(f"stat_{stat} 的 quantiles 长度（{values.size}）必须与数据行数（{n}）一致")
    return values


# ---------------------------------------------------------------------------
# stat_qq / stat_qq_line
# ---------------------------------------------------------------------------


def _stat_qq(table: ColumnTable, params: Mapping[str, Any]) -> ColumnTable:
    """`StatQq$compute_group()`：`sample` 排序 + 理论分位数。"""
    distribution = params.get("distribution", "norm")
    dparams = params.get("dparams") or {}

    def group_fn(sub: ColumnTable, rows: np.ndarray) -> list[tuple[str, Column]] | None:
        del rows
        sample = _sorted_sample(sub, "qq")
        probs = _quantile_probs(params, sample.size, "qq")
        theoretical = _distribution_quantile(distribution, probs, dparams)
        return [
            ("sample", _float_column(sample)),
            ("theoretical", _float_column(theoretical)),
        ]

    return _compute_panel(table, group_fn, stat="qq")


def _stat_qq_line(table: ColumnTable, params: Mapping[str, Any], *, scales: Any) -> ColumnTable:
    """`StatQqLine$compute_group()`：过 `line.p` 两点的那条线。"""
    distribution = params.get("distribution", "norm")
    dparams = params.get("dparams") or {}
    line_p = _param(params, "line.p")
    line_p = (0.25, 0.75) if line_p is None else line_p
    fullrange = bool(params.get("fullrange", False))
    line_p = np.asarray(line_p, dtype=np.float64)
    if line_p.ndim != 1 or line_p.size != 2:
        raise BuildError(f"stat_qq_line 的 line.p 必须长度 2，收到 {line_p!r}")

    def group_fn(sub: ColumnTable, rows: np.ndarray) -> list[tuple[str, Column]] | None:
        del rows
        sample = _sorted_sample(sub, "qq_line")
        probs = _quantile_probs(params, sample.size, "qq_line")
        theoretical = _distribution_quantile(distribution, probs, dparams)
        x_coords = _distribution_quantile(distribution, line_p, dparams)
        y_coords = _r_quantile(sample, line_p)
        slope = float((y_coords[1] - y_coords[0]) / (x_coords[1] - x_coords[0]))
        intercept = float(y_coords[0] - slope * x_coords[0])
        if fullrange:
            x = _dimension(scales, "x", theoretical)
        else:
            x = np.array([float(np.min(theoretical)), float(np.max(theoretical))])
        return [
            ("x", _float_column(x)),
            ("y", _float_column(slope * x + intercept)),
            ("slope", _float_column([slope, slope])),
            ("intercept", _float_column([intercept, intercept])),
        ]

    return _compute_panel(table, group_fn, stat="qq_line")


# ---------------------------------------------------------------------------
# stat_ecdf
# ---------------------------------------------------------------------------


def _wecdf(x: np.ndarray, weights: np.ndarray | None, grid: np.ndarray, *, stat: str) -> np.ndarray:
    """上游 `wecdf()`：按唯一值聚合权重后的阶梯函数（`approxfun(constant, f=0)`）。"""
    n = x.size
    if weights is None:
        weights = np.ones(n, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    if weights.size != n:
        raise BuildError(f"stat_{stat} 的 weight 长度（{weights.size}）与行数（{n}）不一致")
    order = np.argsort(x, kind="stable")
    x = x[order]
    weights = weights[order]
    bad = ~np.isfinite(weights)
    if bad.any():
        _warnings.warn(
            "stat_ecdf 的 weight 美学不支持非有限值 / NA；这些权重按 0 处理。",
            BuildWarning,
            stacklevel=4,
        )
        weights = np.where(bad, 0.0, weights)
    total = float(weights.sum())
    if abs(total) < 1000.0 * np.finfo(np.float64).eps:
        raise BuildError("stat_ecdf：weight 之和为 0，无法计算 eCDF")
    values, index = np.unique(x, return_inverse=True)
    agg = np.zeros(values.size, dtype=np.float64)
    np.add.at(agg, index, weights)
    cumulative = np.cumsum(agg) / total
    # `approxfun(vals, F, method = "constant", f = 0, yleft = 0, yright = 1)`
    position = np.searchsorted(values, grid, side="right") - 1
    out = np.where(position >= 0, cumulative[np.clip(position, 0, values.size - 1)], 0.0)
    out = np.where(grid > values[-1], 1.0, out)
    return out


def _stat_ecdf(table: ColumnTable, params: Mapping[str, Any], *, flipped: bool) -> ColumnTable:
    """`StatEcdf$compute_group()`：阶梯 eCDF，`pad = TRUE` 时两端补 ±Inf。"""
    n = params.get("n")
    pad = bool(params.get("pad", True))
    if n is not None:
        n = int(n)
        if n < 1:
            raise BuildError(f"stat_ecdf 的 n 必须是正整数，收到 {n!r}")
    work = _flip_table(table) if flipped else table

    def group_fn(sub: ColumnTable, rows: np.ndarray) -> list[tuple[str, Column]] | None:
        del rows
        values = _numeric(sub.column("x"))
        if n is None:
            grid = np.unique(values)
        else:
            grid = _r_seq_length(float(np.min(values)), float(np.max(values)), n)
        if pad:
            grid = np.concatenate(([-math.inf], grid, [math.inf]))
        ecdf = _wecdf(values, _weight_values(sub), grid, stat="ecdf")
        return [
            ("x", _float_column(grid)),
            ("y", _float_column(ecdf)),
            ("ecdf", _float_column(ecdf)),
            ("flipped_aes", _bool_column([flipped] * grid.size)),
        ]

    result = _compute_panel(work, group_fn, stat="ecdf")
    if result.nrows == 0:
        return _EMPTY
    return _flip_table(result) if flipped else result


# ---------------------------------------------------------------------------
# stat_ellipse
# ---------------------------------------------------------------------------


def _cov_wt(x: np.ndarray, wt: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """`stats::cov.wt(x, wt)` 的 `method = "unbiased"` 分支。"""
    normalized = wt / wt.sum()
    center = (normalized[:, None] * x).sum(axis=0)
    centered = (x - center) * np.sqrt(normalized)[:, None]
    cov = centered.T @ centered / (1.0 - float((normalized**2).sum()))
    return cov, center


def _cov_trob(
    x: np.ndarray, wt: np.ndarray, *, nu: float = 5.0, maxit: int = 25, tol: float = 0.01
) -> tuple[np.ndarray, np.ndarray]:
    """`MASS::cov.trob()` 的逐行移植（`center = TRUE`、`scale` 无关）。

    R 的循环里 `X` 用的是**上一轮**的 `loc`（`loc` 在循环末尾才更新），
    最后 `cov` 也用这份滞后的 `X`；这里保持同样的顺序，否则收敛方向会差一档。
    """
    _, p = x.shape
    keep = wt > 0
    x = x[keep]
    wt = wt[keep]
    loc = (wt[:, None] * x).sum(axis=0) / wt.sum()
    w = wt * (1.0 + p / nu)
    x_centered = x - loc
    for _ in range(maxit):
        w0 = w
        x_centered = x - loc
        scaled = np.sqrt(w / w.sum())[:, None] * x_centered
        _, singular, vt = np.linalg.svd(scaled, full_matrices=False)
        w_x = x_centered @ vt.T @ np.diag(1.0 / singular)
        q = np.sum(w_x**2, axis=1)
        w = wt * (nu + p) / (nu + q)
        loc = (w[:, None] * x).sum(axis=0) / w.sum()
        if np.all(np.abs(w - w0) < tol):
            break
    weighted = np.sqrt(w)[:, None] * x_centered
    cov = (weighted.T @ weighted) / wt.sum()
    return cov, loc


def _stat_ellipse(table: ColumnTable, params: Mapping[str, Any]) -> ColumnTable:
    """`StatEllipse`：`type` / `level` / `segments`，输出 `segments + 1` 个点。"""
    ellipse_type = params.get("type") or "t"
    level = float(params.get("level", 0.95))
    segments = int(params.get("segments", 51))
    if ellipse_type not in ("t", "norm", "euclid"):
        raise BuildError(
            f"stat_ellipse 的 type 只能是 't' / 'norm' / 'euclid'，收到 {ellipse_type!r}"
        )
    if segments < 1:
        raise BuildError(f"stat_ellipse 的 segments 必须是正整数，收到 {segments!r}")

    def group_fn(sub: ColumnTable, rows: np.ndarray) -> list[tuple[str, Column]] | None:
        del rows
        x = _numeric(sub.column("x"))
        y = _numeric(sub.column("y"))
        weight = _weight_values(sub)
        if weight is None:
            weight = np.ones(x.size, dtype=np.float64)
        if np.isnan(weight).any():
            raise BuildError("stat_ellipse 的 weight 不能有 NA（上游 cov.trob / cov.wt 同样报错）")
        dfn = 2
        dfd = x.size - 1
        if dfd < 3:
            _warnings.warn(
                "stat_ellipse：点太少，无法计算椭圆（至少需要 4 个点）。",
                BuildWarning,
                stacklevel=4,
            )
            return [
                ("x", _float_column([math.nan])),
                ("y", _float_column([math.nan])),
            ]
        normalized = weight / weight.sum()
        data = np.column_stack([x, y])
        if ellipse_type == "t":
            cov, center = _cov_trob(data, normalized * x.size)
        else:
            cov, center = _cov_wt(data, normalized)
            if ellipse_type == "euclid":
                cov = np.diag(np.repeat(np.min(np.diag(cov)), 2))
        try:
            upper = np.linalg.cholesky(cov).T
        except np.linalg.LinAlgError as exc:
            raise BuildError(f"stat_ellipse：协方差矩阵不是正定的（{exc}）") from None
        if ellipse_type == "euclid":
            radius = level / float(np.max(upper))
        else:
            radius = math.sqrt(dfn * _qf(level, float(dfn), float(dfd)))
        angles = np.arange(segments + 1, dtype=np.float64) * (2.0 * math.pi / segments)
        unit_circle = np.column_stack([np.cos(angles), np.sin(angles)])
        points = center + radius * (unit_circle @ upper)
        return [
            ("x", _float_column(points[:, 0])),
            ("y", _float_column(points[:, 1])),
        ]

    return _compute_panel(table, group_fn, stat="ellipse")


# ---------------------------------------------------------------------------
# stat_quantile（线性分位数回归）
# ---------------------------------------------------------------------------


def _rq_fit(
    x: np.ndarray, y: np.ndarray, tau: float, *, max_iter: int = 5000, tol: float = 1e-15
) -> tuple[float, float]:
    """线性分位数回归（`y ~ x`）的 IRLS 解（`quantreg::rq` 的同一最优解）。

    目标 `min Σ ρ_τ(y - b0 - b1 x)`；每步用 `w = 1/max(|r|, ε)` 的加权最小二乘，
    Barrowman 的迭代在有限步内收敛到分位数回归的精确解（线性规划的多解除外）。
    """
    design = np.column_stack([np.ones(x.size), x])
    beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    for _ in range(max_iter):
        residual = y - design @ beta
        # `rho_tau(r) = tau·r (r ≥ 0) / (tau-1)·r (r < 0)`：两段的权重斜率不同，
        # 只按 1/|r| 加权会退化成 tau = 0.5（最小绝对偏差）。
        direction = np.where(residual >= 0.0, tau, 1.0 - tau)
        weight = direction / np.maximum(np.abs(residual), 1e-12)
        weighted = design * np.sqrt(weight)[:, None]
        target = y * np.sqrt(weight)
        updated, *_ = np.linalg.lstsq(weighted, target, rcond=None)
        if np.max(np.abs(updated - beta)) <= tol * max(1.0, float(np.max(np.abs(beta)))):
            beta = updated
            break
        beta = updated
    return float(beta[0]), float(beta[1])


def _stat_quantile(table: ColumnTable, params: Mapping[str, Any]) -> ColumnTable:
    """`StatQuantile$compute_group()`：逐分位数拟合并在 100 点网格上预测。"""
    quantiles = params.get("quantiles")
    if quantiles is None:
        quantiles = (0.25, 0.5, 0.75)
    quantiles = _as_quantiles(quantiles, "stat_quantile")
    if quantiles.size == 0:
        raise BuildError("stat_quantile 的 quantiles 必须是非空序列")
    if np.any((quantiles < 0.0) | (quantiles > 1.0)):
        raise BuildError("stat_quantile 的 quantiles 必须在 [0, 1] 之间")
    method = params.get("method", "rq")
    if method != "rq":
        raise BuildError(
            f"stat_quantile 只实现 method = 'rq'（线性分位数回归）；"
            f"收到 {method!r}（'rqss' 需要 quantreg::rqss 的平滑样条，未实现）"
        )
    formula = params.get("formula")
    if formula is not None and str(formula).replace(" ", "") != "y~x":
        raise BuildError(
            f"stat_quantile 只实现 formula = 'y ~ x'，收到 {formula!r}"
            "（其他 formula 需要 quantreg 的完整设计矩阵支持）"
        )
    method_args = _param(params, "method.args") or {}
    if not isinstance(method_args, Mapping):
        raise BuildError("stat_quantile 的 method.args 必须是映射")
    unknown = sorted(str(key) for key in method_args if key not in {"max_iter", "tol"})
    if unknown:
        raise BuildError(
            "stat_quantile 的 method.args 只支持 max_iter / tol（IRLS 的收敛口径），"
            f"收到 {', '.join(unknown)}"
        )
    max_iter = int(method_args.get("max_iter", 5000))
    tol = float(method_args.get("tol", 1e-15))
    xseq = params.get("xseq")

    def group_fn(sub: ColumnTable, rows: np.ndarray) -> list[tuple[str, Column]] | None:
        del rows
        x = _numeric(sub.column("x"))
        y = _numeric(sub.column("y"))
        if xseq is None:
            grid = _r_seq_length(float(np.min(x)), float(np.max(x)), 100)
        else:
            grid = np.asarray(xseq, dtype=np.float64)
        group_value = int(_column_values(sub.column("group"))[0]) if "group" in sub else -1
        frames: list[list[tuple[str, Column]]] = []
        for tau in quantiles:
            intercept, slope = _rq_fit(x, y, float(tau), max_iter=max_iter, tol=tol)
            predicted = intercept + slope * grid
            label = f"{group_value}-{_r_number(float(tau))}"
            frames.append(
                [
                    ("x", _float_column(grid)),
                    ("y", _float_column(predicted)),
                    ("quantile", _float_column([float(tau)] * grid.size)),
                    ("group", _str_column([label] * grid.size)),
                ]
            )
        names = [name for name, _ in frames[0]]
        merged: list[tuple[str, Column]] = []
        for position, name in enumerate(names):
            parts = [frame[position][1] for frame in frames]
            concatenated = Column(
                parts[0].kind,
                np.concatenate([np.asarray(part.values) for part in parts]),
                levels=parts[0].levels,
                na_mask=np.concatenate([np.asarray(part.na_mask) for part in parts]),
            )
            merged.append((name, concatenated))
        return merged

    return _compute_panel(table, group_fn, stat="quantile")


def _as_quantiles(value: Any, stat: str) -> np.ndarray:
    """标量 / 序列 → 一维分位数数组（R 的 `quantiles = 0.5` 是长度为 1 的向量）。"""
    array = np.asarray(value, dtype=np.float64)
    if array.ndim == 0:
        array = array.reshape(1)
    if array.ndim != 1:
        raise BuildError(f"{stat} 的 quantiles 必须是一维序列")
    return array


def _r_number(value: float) -> str:
    """R 的 `paste()` 数字口径（`0.5` / `1` / `0.25`）。"""
    if value == int(value):
        return str(int(value))
    return repr(float(value))


# ---------------------------------------------------------------------------
# stat_summary / stat_summary_bin
# ---------------------------------------------------------------------------

_SUMMARY_FUNCTIONS: Mapping[str, Callable[[np.ndarray], float]] = {
    "mean": lambda values: float(np.mean(values)),
    "median": lambda values: float(np.median(values)),
    "sd": lambda values: float(np.std(values, ddof=1)) if values.size > 1 else math.nan,
    "var": lambda values: float(np.var(values, ddof=1)) if values.size > 1 else math.nan,
    "min": lambda values: float(np.min(values)),
    "max": lambda values: float(np.max(values)),
    "sum": lambda values: float(np.sum(values)),
    "length": lambda values: float(values.size),
    "first": lambda values: float(values[0]),
    "last": lambda values: float(values[-1]),
}


def _mean_se(values: np.ndarray, mult: float = 1.0) -> dict[str, float]:
    """上游 `mean_se()`：`y = mean`、`± mult · sqrt(var/n)`。"""
    values = values[~np.isnan(values)]
    se = mult * math.sqrt(_variance(values) / values.size) if values.size > 1 else math.nan
    mean = float(np.mean(values)) if values.size else math.nan
    return {"y": mean, "ymin": mean - se, "ymax": mean + se}


def _mean_cl_normal(values: np.ndarray, mult: float = 1.96) -> dict[str, float]:
    """`Hmisc::smean.cl.normal()` 的闭式口径（不比 Hmisc 少任何近似）。"""
    values = values[~np.isnan(values)]
    if values.size < 2:
        mean = float(np.mean(values)) if values.size else math.nan
        return {"y": mean, "ymin": math.nan, "ymax": math.nan}
    mean = float(np.mean(values))
    se = math.sqrt(_variance(values) / values.size)
    half = mult * se
    return {"y": mean, "ymin": mean - half, "ymax": mean + half}


def _mean_sdl(values: np.ndarray, mult: float = 2.0) -> dict[str, float]:
    values = values[~np.isnan(values)]
    mean = float(np.mean(values)) if values.size else math.nan
    half = mult * float(np.std(values, ddof=1)) if values.size > 1 else math.nan
    return {"y": mean, "ymin": mean - half, "ymax": mean + half}


def _median_hilow(values: np.ndarray, conf_int: float = 0.95) -> dict[str, float]:
    values = values[~np.isnan(values)]
    if values.size == 0:
        return {"y": math.nan, "ymin": math.nan, "ymax": math.nan}
    alpha = (1.0 - conf_int) / 2.0
    low, middle, high = _r_quantile(values, [alpha, 0.5, 1.0 - alpha])
    return {"y": float(middle), "ymin": float(low), "ymax": float(high)}


_SUMMARY_DATA_FUNCTIONS: Mapping[str, Callable[..., Mapping[str, float]]] = {
    "mean_se": _mean_se,
    "mean_cl_normal": _mean_cl_normal,
    "mean_sdl": _mean_sdl,
    "median_hilow": _median_hilow,
}


def _resolve_summary_fun(fun: Any, name: str) -> Callable[[np.ndarray], float] | None:
    if fun is None:
        return None
    if isinstance(fun, str):
        if fun not in _SUMMARY_FUNCTIONS:
            raise BuildError(
                f"stat_{name} 的 {name} 字符串别名不认识：{fun!r}；"
                f"可用：{', '.join(sorted(_SUMMARY_FUNCTIONS))}，或传可调用"
            )
        return _SUMMARY_FUNCTIONS[fun]
    if not callable(fun):
        raise BuildError(f"stat_{name} 的函数参数必须是可调用或字符串别名，收到 {fun!r}")
    return fun


def _resolve_fun_data(fun_data: Any, name: str) -> Callable[..., Mapping[str, float]] | None:
    if fun_data is None:
        return None
    if isinstance(fun_data, str):
        if fun_data not in _SUMMARY_DATA_FUNCTIONS:
            raise BuildError(
                f"stat_{name} 的 fun.data 字符串别名不认识：{fun_data!r}；"
                f"可用：{', '.join(sorted(_SUMMARY_DATA_FUNCTIONS))}，或传可调用"
            )
        return _SUMMARY_DATA_FUNCTIONS[fun_data]
    if not callable(fun_data):
        raise BuildError(f"stat_{name} 的 fun.data 必须是可调用或字符串别名，收到 {fun_data!r}")
    return fun_data


def _summary_callable(params: Mapping[str, Any], name: str) -> Callable[[np.ndarray], dict]:
    """上游 `make_summary_fun()`：`fun.data` 优先，其次 `fun` / `fun.min` / `fun.max`。"""
    fun_data = _resolve_fun_data(_param(params, "fun.data"), name)
    fun = _resolve_summary_fun(params.get("fun"), name)
    fun_min = _resolve_summary_fun(_param(params, "fun.min"), name)
    fun_max = _resolve_summary_fun(_param(params, "fun.max"), name)
    raw_args = _param(params, "fun.args")
    if raw_args is None:
        raw_args = {}
    if not isinstance(raw_args, Mapping):
        raise BuildError(f"stat_{name} 的 fun.args 必须是映射（R 的 list(...)）")
    extra = dict(raw_args)
    if fun_data is not None:
        return lambda values: dict(fun_data(values, **extra))
    if fun is not None or fun_min is not None or fun_max is not None:

        def summarize(values: np.ndarray) -> dict:
            def call(function: Callable | None) -> float:
                return math.nan if function is None else float(function(values, **extra))

            return {"ymin": call(fun_min), "y": call(fun), "ymax": call(fun_max)}

        return summarize
    _warnings.warn(
        f"stat_{name} 没有给汇总函数，按上游缺省 mean_se() 处理。",
        BuildWarning,
        stacklevel=4,
    )

    def default(values: np.ndarray) -> dict:
        return dict(_mean_se(values, **extra))

    return default


def _summary_columns(summary: Mapping[str, float]) -> list[tuple[str, Column]]:
    """`fun.data` 的输出 → 列（顺序照 R 的 `data_frame0()`：`y`、`ymin`、`ymax`）。"""
    order = ("y", "ymin", "ymax")
    names = [key for key in order if key in summary]
    names.extend(key for key in summary if key not in order)
    return [(name, _float_column([float(summary[name])])) for name in names]


def _split_by(values: np.ndarray) -> list[np.ndarray]:
    """`split()` 的顺序：单个键按升序（数值）取值分组。"""
    unique = np.unique(values)
    return [np.flatnonzero(values == key) for key in unique]


def _stat_summary(table: ColumnTable, params: Mapping[str, Any], *, flipped: bool) -> ColumnTable:
    """`StatSummary$compute_panel()`：按 `(group, x)` 汇总。"""
    summary = _summary_callable(params, "summary")
    work = _flip_table(table) if flipped else table
    groups = np.asarray(work.column("group").values).astype(np.int64)
    x_values = _numeric(work.column("x"))
    frames: list[list[tuple[str, Column]]] = []
    for group_id in np.unique(groups):
        group_rows = np.flatnonzero(groups == group_id)
        for rows in _split_by(x_values[group_rows]):
            picked = group_rows[rows]
            y = _numeric(_slice(work, picked).column("y"))
            output = summary(y)
            frame: list[tuple[str, Column]] = [
                ("x", _float_column([float(x_values[picked[0]])])),
                ("group", Column("int", np.array([int(group_id)], dtype=np.int64))),
            ]
            frame.extend(_summary_columns(output))
            frames.append(frame)
    if not frames:
        return _EMPTY
    names = [name for name, _ in frames[0]]
    columns: list[tuple[str, Column]] = []
    for position, name in enumerate(names):
        parts = [frame[position][1] for frame in frames]
        columns.append((name, _concat(parts)))
    for name, column in _items(work):
        if name in names:
            continue
        values = _column_values(column)
        if len({_freeze(value) for value in values.tolist()}) > 1:
            continue
        columns.append((name, _repeat_constant(column, values[0], len(frames))))
    columns.append(("flipped_aes", _bool_column([flipped] * len(frames))))
    result = ColumnTable(columns)
    return _flip_table(result) if flipped else result


def _stat_summary_bin(
    table: ColumnTable, params: Mapping[str, Any], *, scales: Any, flipped: bool
) -> ColumnTable:
    """`StatSummaryBin$compute_group()`：先分箱，再按箱汇总。"""
    summary = _summary_callable(params, "summary_bin")
    work = _flip_table(table) if flipped else table
    bins_param = params.get("bins")
    binwidth = params.get("binwidth")
    breaks = params.get("breaks")
    center = params.get("center")
    boundary = params.get("boundary")
    closed = params.get("closed", ("right", "left"))
    if isinstance(closed, (list, tuple)):
        closed = closed[0]
    width_param = params.get("width")

    def group_fn(sub: ColumnTable, rows: np.ndarray) -> list[tuple[str, Column]] | None:
        del rows
        x = _numeric(sub.column("x"))
        x_range = _dimension(scales, "x", x)
        bins = _compute_bins(
            breaks=breaks,
            binwidth=None if binwidth is None else float(binwidth),
            bins=None if bins_param is None else int(bins_param),
            center=None if center is None else float(center),
            boundary=None if boundary is None else float(boundary),
            closed=str(closed),
            x_range=x_range,
        )
        codes = bins.cut(x)
        labels = _bin_labels(bins.breaks, str(closed))
        frames: list[list[tuple[str, Column]]] = []
        for index in range(len(labels)):
            picked = np.flatnonzero(codes == index)
            if picked.size == 0:
                continue
            y = _numeric(_slice(sub, picked).column("y"))
            output = summary(y)
            frame: list[tuple[str, Column]] = [
                ("bin", _str_column([labels[index]])),
            ]
            frame.extend(_summary_columns(output))
            centres = (bins.breaks[index] + bins.breaks[index + 1]) / 2.0
            frame.append(("x", _float_column([float(centres)])))
            length = float(bins.breaks[index + 1] - bins.breaks[index])
            frame.append(
                (
                    "width",
                    _float_column([float(width_param) if width_param is not None else length]),
                )
            )
            frames.append(frame)
        if not frames:
            return None
        names = [name for name, _ in frames[0]]
        merged: list[tuple[str, Column]] = []
        for position, name in enumerate(names):
            merged.append((name, _concat([frame[position][1] for frame in frames])))
        merged.append(("flipped_aes", _bool_column([flipped] * len(frames))))
        return merged

    result = _compute_panel(work, group_fn, stat="summary_bin")
    if result.nrows == 0:
        return _EMPTY
    return _flip_table(result) if flipped else result


def _bin_labels(breaks: np.ndarray, closed: str) -> list[str]:
    """R 的 `cut(..., include.lowest = TRUE)` 区间标签（`dig.lab = 3` 起）。"""
    finite = np.asarray(breaks, dtype=np.float64)
    nb = finite.size
    digits = 3
    chosen: list[str] | None = None
    while digits <= max(12, 3):
        texts = [_r_format_c(0.0 + value, digits) for value in finite]
        if all(texts[index] != texts[index + 1] for index in range(nb - 1)):
            chosen = texts
            break
        digits += 1
    labels: list[str] = []
    if chosen is None:
        return [f"Range_{index + 1}" for index in range(nb - 1)]
    right = closed == "right"
    for index in range(nb - 1):
        opening = "(" if right else "["
        closing = "]" if right else ")"
        labels.append(f"{opening}{chosen[index]},{chosen[index + 1]}{closing}")
    if right:
        labels[0] = "[" + labels[0][1:]
    else:
        labels[-1] = labels[-1][:-1] + "]"
    return labels


def _r_format_c(value: float, digits: int) -> str:
    """`formatC(x, digits = d, width = 1)` 的 `g` 口径（去掉多余的 0）。"""
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.{digits}g}"


def _freeze(value: Any) -> Any:
    return None if isinstance(value, float) and math.isnan(value) else value


def _concat(parts: Sequence[Column]) -> Column:
    kind = parts[0].kind
    for column in parts[1:]:
        if column.kind != kind:
            raise BuildError(f"stat 拼接时列类型不一致：{kind} / {column.kind}")
    return Column(
        kind,
        np.concatenate([np.asarray(column.values) for column in parts]),
        levels=parts[0].levels,
        na_mask=np.concatenate([np.asarray(column.na_mask) for column in parts]),
    )


def _repeat_constant(column: Column, value: Any, nrows: int) -> Column:
    """组内恒定的列 → 每行一个（R 的 `uniquecols()` + `merge()`）。"""
    if column.kind == "str":
        return _str_column([str(value)] * nrows)
    if column.kind == "categorical":
        return Column(
            "categorical", np.full(nrows, int(value), dtype=np.int32), levels=column.levels
        )
    if column.kind == "bool":
        return _bool_column([bool(value)] * nrows)
    if column.kind == "int":
        return Column("int", np.full(nrows, float(value)))
    return _float_column([float(value)] * nrows)


# ---------------------------------------------------------------------------
# stat_sum / stat_unique
# ---------------------------------------------------------------------------

#: 上游 `ggplot_global$all_aesthetics`（只列 `stat_sum` 可能碰到的那些）。
_ALL_AESTHETICS: tuple[str, ...] = (
    "x",
    "y",
    "xmin",
    "xmax",
    "ymin",
    "ymax",
    "xend",
    "yend",
    "colour",
    "fill",
    "size",
    "shape",
    "linetype",
    "linewidth",
    "alpha",
    "stroke",
    "group",
    "label",
    "weight",
    "PANEL",
)


def _stat_sum(table: ColumnTable, params: Mapping[str, Any]) -> ColumnTable:
    """`StatSum$compute_panel()`：`count(data, group_by, wt_var = "weight")`。"""
    del params
    weight = _weight_values(table)
    if weight is None:
        weight = np.ones(table.nrows, dtype=np.float64)
    keys = [name for name in table.names if name in _ALL_AESTHETICS and name != "weight"]
    # R 的 count() 把 PANEL 排在最前（ggcore 的常量列顺序随输入，这里显式对齐）。
    if "PANEL" in keys:
        keys = ["PANEL"] + [name for name in keys if name != "PANEL"]
    columns_values = {name: _column_values(table.column(name)) for name in keys}
    grouping = np.zeros(table.nrows, dtype=np.int64)
    for name in keys:
        grouping = _stable_combine(grouping, columns_values[name])
    unique_groups = _unique_rows(grouping)
    panel_groups = (
        np.asarray(_column_values(table.column("group")).astype(np.int64))
        if "group" in table
        else np.full(table.nrows, -1, dtype=np.int64)
    )
    counts = np.zeros(len(unique_groups), dtype=np.float64)
    representative = np.zeros(len(unique_groups), dtype=np.int64)
    for position, rows in enumerate(unique_groups):
        counts[position] = float(weight[rows].sum())
        representative[position] = int(rows[0])
    totals: dict[int, float] = {}
    for position, rows in enumerate(unique_groups):
        group_id = int(panel_groups[rows[0]])
        totals[group_id] = totals.get(group_id, 0.0) + abs(float(counts[position]))
    prop = np.array(
        [
            counts[position] / totals[int(panel_groups[rows[0]])]
            if totals[int(panel_groups[rows[0]])] != 0.0
            else math.nan
            for position, rows in enumerate(unique_groups)
        ],
        dtype=np.float64,
    )
    columns: list[tuple[str, Column]] = []
    for name in keys:
        column = table.column(name)
        picked = _take(column, representative)
        columns.append((name, picked))
    columns.append(("n", _float_column(counts)))
    columns.append(("prop", _float_column(prop)))
    return ColumnTable(columns)


def _take(column: Column, rows: np.ndarray) -> Column:
    mask = np.asarray(column.na_mask)[rows]
    return Column(
        column.kind,
        np.asarray(column.values)[rows],
        levels=column.levels,
        na_mask=mask,
    )


def _stable_combine(ids: np.ndarray, values: np.ndarray) -> np.ndarray:
    """把一列取值并入分组 id（按首次出现顺序编号，NA 也算一个水平）。"""
    lookup: dict[Any, int] = {}
    next_id = 0
    out = np.empty(ids.size, dtype=np.int64)
    for index in range(ids.size):
        key = (int(ids[index]), _freeze(values[index]))
        found = lookup.get(key)
        if found is None:
            found = next_id
            lookup[key] = found
            next_id += 1
        out[index] = found
    return out


def _unique_rows(ids: np.ndarray) -> list[np.ndarray]:
    order: dict[int, list[int]] = {}
    for index, value in enumerate(ids.tolist()):
        order.setdefault(int(value), []).append(index)
    return [np.asarray(rows, dtype=np.int64) for rows in order.values()]


def _stat_unique(table: ColumnTable) -> ColumnTable:
    """`StatUnique`：`unique0(data)`（保留首次出现的行序）。"""
    seen: set[tuple] = set()
    rows: list[int] = []
    columns_values = [_column_values(column) for column in table.columns()]
    for index in range(table.nrows):
        key = tuple(_freeze(column[index]) for column in columns_values)
        if key in seen:
            continue
        seen.add(key)
        rows.append(index)
    picked = np.asarray(rows, dtype=np.int64)
    return ColumnTable([(name, _take(column, picked)) for name, column in _items(table)])


# ---------------------------------------------------------------------------
# 核密度：`stats::density()` 的 bin + FFT 实现（逐值对齐）
# ---------------------------------------------------------------------------

_KERNEL_NAMES = ("gaussian",)


def _bw_nrd0(values: np.ndarray) -> float:
    """`stats::bw.nrd0()`。"""
    if values.size < 2:
        raise BuildError("带宽自动选择至少需要 2 个观测（R 的 bw.nrd0 同样报错）")
    hi = float(np.std(values, ddof=1))
    q = np.quantile(values, [0.25, 0.75], method="linear")
    lo = min(hi, float(q[1] - q[0]) / 1.34)
    if not lo:  # NA / 0：R 的 `if(!(lo <- min(...)))`
        lo = hi
        if not lo:
            lo = abs(float(values[0]))
            if not lo:
                lo = 1.0
    return 0.9 * lo * values.size ** (-0.2)


def _bw_nrd(values: np.ndarray) -> float:
    """`stats::bw.nrd()`：`1.06 · min(sd, IQR/1.34) · n^(-1/5)`。"""
    if values.size < 2:
        raise BuildError("带宽自动选择至少需要 2 个观测（R 的 bw.nrd 同样报错）")
    hi = float(np.std(values, ddof=1))
    q = np.quantile(values, [0.25, 0.75], method="linear")
    lo = min(hi, float(q[1] - q[0]) / 1.34)
    return 1.06 * lo * values.size ** (-0.2)


def _precompute_bw(values: np.ndarray, bw: Any) -> float:
    """上游 `precompute_bw()`：字符串规则或正数带宽。"""
    if isinstance(bw, str):
        name = bw.lower()
        if name == "nrd0":
            value = _bw_nrd0(values)
        elif name == "nrd":
            value = _bw_nrd(values)
        else:
            raise BuildError(
                f"stat_density 的 bw 规则只实现 'nrd0' / 'nrd'（或直接给正数）；"
                f"收到 {bw!r}（ucv / bcv / sj 需要 R 的交叉验证实现）"
            )
    else:
        value = float(bw)
    if not math.isfinite(value) or value <= 0:
        raise BuildError(f"stat_density 的 bw 必须是有限正数，收到 {bw!r}")
    return value


def _kernel_values(kords: np.ndarray, bw: float, kernel: str) -> np.ndarray:
    if kernel not in _KERNEL_NAMES:
        raise BuildError(
            f"stat_density 的 kernel 只实现 'gaussian'，收到 {kernel!r}"
            "（其余核在 R 里也是同一条 FFT 路径，补起来是纯算术，按需再加）"
        )
    return np.exp(-0.5 * (kords / bw) ** 2) / (bw * math.sqrt(2.0 * math.pi))


def _bin_dist(x: np.ndarray, weights: np.ndarray, lo: float, up: float, n: int) -> np.ndarray:
    """`stats` 的 `C_BinDist`（`massdist.c`）：线性分摊到 2n 个网格点。"""
    out = np.zeros(2 * n, dtype=np.float64)
    xdelta = (up - lo) / (n - 1)
    ixmin, ixmax = 0, n - 2
    with np.errstate(invalid="ignore", divide="ignore"):
        position = (x - lo) / xdelta
    good = np.isfinite(x) & np.isfinite(position)
    good &= (position <= np.iinfo(np.int32).max) & (position >= np.iinfo(np.int32).min)
    position = position[good]
    weight = weights[good]
    ix = np.floor(position).astype(np.int64)
    fx = position - ix
    inside = (ix >= ixmin) & (ix <= ixmax)
    np.add.at(out, ix[inside], (1.0 - fx[inside]) * weight[inside])
    np.add.at(out, ix[inside] + 1, fx[inside] * weight[inside])
    left = ix == -1
    np.add.at(out, np.zeros(int(left.sum()), dtype=np.int64), fx[left] * weight[left])
    right = ix == ixmax + 1
    np.add.at(out, ix[right], (1.0 - fx[right]) * weight[right])
    return out


def _r_density(
    values: np.ndarray,
    weights: np.ndarray,
    *,
    from_: float,
    to: float,
    bw: float,
    adjust: float,
    kernel: str,
    n: int,
) -> tuple[np.ndarray, np.ndarray]:
    """`stats::density()` 的核心（bin + FFT + `approx`），`values` 已去缺失。"""
    n_user = int(n)
    n = max(n_user, 512)
    if n > 512:
        n = 2 ** math.ceil(math.log2(n))
    bw = adjust * bw
    if not math.isfinite(bw) or bw <= 0:
        raise BuildError(f"stat_density 的带宽必须是有限正数，实际 {bw!r}")
    if not math.isfinite(from_) or not math.isfinite(to):
        raise BuildError("stat_density 的 from / to 必须是有限值")
    ext = 4.0
    lo = from_ - ext * bw
    up = to + ext * bw
    total_mass = float(weights.sum())
    y = _bin_dist(values, weights, lo, up, n) * total_mass
    kords = _r_seq_length(0.0, (2.0 * n - 1.0) / (n - 1.0) * (up - lo), 2 * n)
    kords[n + 1 : 2 * n] = -kords[np.arange(n - 1, 0, -1)]
    kords = _kernel_values(kords, bw, kernel)
    spectrum = np.fft.fft(y) * np.conj(np.fft.fft(kords))
    smoothed = np.real(np.fft.ifft(spectrum)) * spectrum.size / y.size
    smoothed = np.maximum(0.0, smoothed[:n])
    xords = _r_seq_length(lo, up, n)
    xs = _r_seq_length(from_, to, n_user)
    out = np.interp(xs, xords, smoothed)
    outside = (xs < xords[0]) | (xs > xords[-1])
    out = np.where(outside, math.nan, out)
    return xs, out


def _compute_density(
    values: np.ndarray,
    weights: np.ndarray | None,
    *,
    from_: float,
    to: float,
    bw: Any,
    adjust: float,
    kernel: str,
    n: int,
    bounds: Sequence[float],
    stat: str,
) -> dict[str, Any]:
    """上游 `compute_density()`：权重归一、边界反射、`scaled` / `count` 等派生列。"""
    nx = int(values.size)
    if weights is None:
        weights = np.full(nx, 1.0 / nx, dtype=np.float64)
        w_sum = float(nx)
    else:
        w_sum = float(weights.sum())
        weights = weights / w_sum
    # `fit_data_to_bounds()`
    low_bound, high_bound = (float(bounds[0]), float(bounds[1]))
    inside = (low_bound <= values) & (values <= high_bound)
    if not bool(inside.all()):
        _warnings.warn(
            f"stat_{stat}：有数据点落在 bounds 之外，已按上游口径删除。",
            BuildWarning,
            stacklevel=4,
        )
        values = values[inside]
        weights = weights[inside]
        new_sum = float(weights.sum())
        if new_sum > 0:
            weights = weights / new_sum
        w_sum = new_sum * w_sum
        nx = int(values.size)
    if nx < 2:
        _warnings.warn(
            f"stat_{stat}：少于两个数据点的分组已被丢弃。",
            BuildWarning,
            stacklevel=4,
        )
        return {
            "x": np.array([math.nan]),
            "density": np.array([math.nan]),
            "scaled": np.array([math.nan]),
            "ndensity": np.array([math.nan]),
            "count": np.array([math.nan]),
            "wdensity": np.array([math.nan]),
            "n": np.array([math.nan]),
        }
    bandwidth = _precompute_bw(values, bw)
    has_bounds = math.isfinite(low_bound) or math.isfinite(high_bound)
    if has_bounds:
        low_bound, high_bound = sorted((low_bound, high_bound))
        span = to - from_
        lo = from_ - span * float(math.isfinite(low_bound))
        hi = to + span * float(math.isfinite(high_bound))
        n_used = int(n) * (int(math.isfinite(low_bound)) + int(math.isfinite(high_bound)) + 1)
        grid_x, grid_y = _r_density(
            values,
            weights,
            from_=lo,
            to=hi,
            bw=bandwidth,
            adjust=adjust,
            kernel=kernel,
            n=n_used,
        )

        # `reflect_density()`：把界外的两条尾巴折回来。
        def linear(xout: np.ndarray) -> np.ndarray:
            out = np.interp(xout, grid_x, grid_y)
            return np.where((xout < grid_x[0]) | (xout > grid_x[-1]), 0.0, out)

        left = max(from_, low_bound)
        right = min(to, high_bound)
        out_x = _r_seq_length(left, right, grid_x.size)
        left_reflection = linear(low_bound + (low_bound - out_x))
        right_reflection = linear(high_bound + (high_bound - out_x))
        out_y = linear(out_x) + left_reflection + right_reflection
        grid_x, grid_y = out_x, out_y
    else:
        grid_x, grid_y = _r_density(
            values,
            weights,
            from_=from_,
            to=to,
            bw=bandwidth,
            adjust=adjust,
            kernel=kernel,
            n=n,
        )
    maximum = float(np.max(grid_y)) if grid_y.size else math.nan
    scaled = grid_y / maximum if maximum not in (0.0, math.nan) else grid_y * math.nan
    return {
        "x": grid_x,
        "density": grid_y,
        "scaled": scaled,
        "ndensity": scaled,
        "count": grid_y * nx,
        "wdensity": grid_y * w_sum,
        "n": np.full(grid_x.size, nx, dtype=np.float64),
    }


def _density_bounds(params: Mapping[str, Any], stat: str) -> tuple[float, float]:
    bounds = params.get("bounds")
    if bounds is None:
        return (-math.inf, math.inf)
    values = np.asarray(bounds, dtype=np.float64)
    if values.size != 2:
        raise BuildError(f"stat_{stat} 的 bounds 必须是长度 2 的序列，收到 {bounds!r}")
    return float(values[0]), float(values[1])


def _stat_density(
    table: ColumnTable, params: Mapping[str, Any], *, scales: Any, flipped: bool
) -> ColumnTable:
    """`StatDensity$compute_group()`：`density()` + `flipped_aes`。"""
    bw = params.get("bw", "nrd0")
    adjust = float(params.get("adjust", 1))
    kernel = str(params.get("kernel", "gaussian"))
    n = int(params.get("n", 512))
    trim = bool(params.get("trim", False))
    bounds = _density_bounds(params, "density")
    work = _flip_table(table) if flipped else table

    def group_fn(sub: ColumnTable, rows: np.ndarray) -> list[tuple[str, Column]] | None:
        del rows
        values = _numeric(sub.column("x"))
        if trim:
            value_range = np.array([float(np.min(values)), float(np.max(values))])
        else:
            value_range = _dimension(scales, "x", values)
        density = _compute_density(
            values,
            _weight_values(sub),
            from_=float(value_range[0]),
            to=float(value_range[1]),
            bw=bw,
            adjust=adjust,
            kernel=kernel,
            n=n,
            bounds=bounds,
            stat="density",
        )
        columns: list[tuple[str, Column]] = [
            ("x", _float_column(density["x"])),
            ("density", _float_column(density["density"])),
            ("scaled", _float_column(density["scaled"])),
            ("ndensity", _float_column(density["ndensity"])),
            ("count", _float_column(density["count"])),
            ("wdensity", _float_column(density["wdensity"])),
            ("n", Column("int", np.asarray(density["n"], dtype=np.float64))),
            ("flipped_aes", _bool_column([flipped] * density["x"].size)),
        ]
        return columns

    result = _compute_panel(work, group_fn, stat="density")
    if result.nrows == 0:
        return _EMPTY
    return _flip_table(result) if flipped else result


# ---------------------------------------------------------------------------
# stat_ydensity（小提琴密度）
# ---------------------------------------------------------------------------


def _stat_ydensity(
    table: ColumnTable, params: Mapping[str, Any], *, scales: Any, flipped: bool
) -> ColumnTable:
    """`StatYdensity`：逐组密度 → `violinwidth` → 分位线插值。"""
    del scales
    if "draw_quantiles" in params:
        _warnings.warn(
            "stat_ydensity 的 draw_quantiles 已弃用（4.0.0），改用 quantiles。",
            BuildWarning,
            stacklevel=4,
        )
        params = {**params, "quantiles": params["draw_quantiles"]}
    bw = params.get("bw", "nrd0")
    adjust = float(params.get("adjust", 1))
    kernel = str(params.get("kernel", "gaussian"))
    trim = bool(params.get("trim", True))
    drop = bool(params.get("drop", True))
    width_param = params.get("width")
    bounds = _density_bounds(params, "ydensity")
    scale = str(params.get("scale", "area"))
    if scale not in ("area", "count", "width"):
        raise BuildError(f"stat_ydensity 的 scale 只能是 area / count / width，收到 {scale!r}")
    quantiles = params.get("quantiles", (0.25, 0.5, 0.75))
    if quantiles is not None:
        quantiles = _as_quantiles(quantiles, "stat_ydensity")
        if np.any((quantiles < 0) | (quantiles > 1)):
            raise BuildError("stat_ydensity 的 quantiles 必须在 [0, 1] 之间")
    work = _flip_table(table) if flipped else table

    def group_fn(sub: ColumnTable, rows: np.ndarray) -> list[tuple[str, Column]] | None:
        del rows
        y = _numeric(sub.column("y"))
        n = y.size
        if n < 2:
            if drop:
                _warnings.warn(
                    "stat_ydensity：少于两个数据点的分组已被丢弃"
                    "（drop = FALSE 可保留以供位置调整）。",
                    BuildWarning,
                    stacklevel=4,
                )
                return None
            return [
                ("x", _float_column(_numeric(sub.column("x")))),
                ("n", Column("int", np.full(n, float(n)))),
            ]
        value_range = np.array([float(np.min(y)), float(np.max(y))])
        bandwidth = _precompute_bw(y, bw)
        modifier = 0.0 if trim else 3.0
        density = _compute_density(
            y,
            _weight_values(sub),
            from_=float(value_range[0]) - modifier * bandwidth,
            to=float(value_range[1]) + modifier * bandwidth,
            bw=bandwidth,
            adjust=adjust,
            kernel=kernel,
            n=512,
            bounds=bounds,
            stat="ydensity",
        )
        dens_y = density["x"].copy()
        x_values = _numeric(sub.column("x"))
        if np.unique(x_values).size > 1:
            dens_x = np.full(dens_y.size, float(np.mean(value_range)))
            width = float(np.max(x_values) - np.min(x_values)) * 0.9
        else:
            dens_x = np.full(dens_y.size, float(x_values[0]))
            width = None if width_param is None else float(width_param)
        columns: dict[str, np.ndarray] = {
            "x": dens_x,
            "density": density["density"],
            "scaled": density["scaled"],
            "ndensity": density["ndensity"],
            "count": density["count"],
            "wdensity": density["wdensity"],
            "n": density["n"],
            "y": dens_y,
            "quantile": np.full(dens_y.size, math.nan),
        }
        if quantiles is not None and quantiles.size:
            weight = _weight_values(sub)
            if weight is not None and np.any(weight != 1):
                _warnings.warn(
                    "stat_ydensity：加权数据的分位线未实现（上游同样告警）。",
                    BuildWarning,
                    stacklevel=4,
                )
            quantile_values = np.asarray(_r_quantile(y, quantiles), dtype=np.float64)
            quantile_rows: dict[str, np.ndarray] = {
                "y": quantile_values,
                "quantile": quantiles.copy(),
            }
            for name, values in columns.items():
                if name in ("y", "quantile"):
                    continue
                quantile_rows[name] = np.interp(
                    quantile_values, dens_y, np.asarray(values, dtype=np.float64)
                )
            keep = ~np.isin(dens_y, quantile_values)
            for name in columns:
                columns[name] = np.concatenate(
                    [np.asarray(columns[name])[keep], quantile_rows[name]]
                )
        order = [
            "x",
            "density",
            "scaled",
            "ndensity",
            "count",
            "wdensity",
            "n",
            "y",
        ]
        if quantiles is not None and quantiles.size:
            order.append("quantile")
        # `width` 只在 geom 需要时保留（上游 `omit = "width"` 把这个参数从 stat 里
        # 去掉）。R 的 `compute_group()` 把它按行展开，分位线那几行也带同一份宽度，
        # 所以长度必须跟着**合并后**的列走，不能再用单个分组的密度网格长度。
        if width is not None:
            order.append("width")
            columns["width"] = np.full(np.asarray(columns["y"]).size, float(width))
        # 有分位线时 R 的 `vec_c()` 把 n 抬成 double（分位行是插值出来的）；没有
        # 分位线时 `n` 保持 integer。
        has_quantiles = quantiles is not None and quantiles.size > 0
        output: list[tuple[str, Column]] = []
        for name in order:
            values = columns[name]
            if name == "n" and not has_quantiles:
                output.append((name, Column("int", np.asarray(values, dtype=np.float64))))
            else:
                output.append((name, _float_column(values)))
        return output

    result = _compute_panel(work, group_fn, stat="ydensity")
    if result.nrows == 0 or "density" not in result:
        # `drop = FALSE` 且有不足两点的分组时，上游只留下 `x, n` 两列。
        return _EMPTY if result.nrows == 0 else result
    density_values = np.asarray(_column_values(result.column("density")), dtype=np.float64)
    maximum = float(np.max(density_values)) if density_values.size else math.nan
    if scale == "area":
        violin = density_values / maximum if maximum else density_values * math.nan
    elif scale == "count":
        counts = np.asarray(_column_values(result.column("n")), dtype=np.float64)
        top = float(np.max(counts)) if counts.size else math.nan
        if maximum and top:
            violin = density_values / maximum * counts / top
        else:
            violin = density_values * math.nan
    else:
        violin = np.asarray(_column_values(result.column("scaled")), dtype=np.float64)
    columns = list(_items(result))
    columns.append(("violinwidth", _float_column(violin)))
    columns.append(("flipped_aes", _bool_column([flipped] * result.nrows)))
    final = ColumnTable(columns)
    return _flip_table(final) if flipped else final


# ---------------------------------------------------------------------------
# stat_function
# ---------------------------------------------------------------------------

_FUNCTION_ALIASES: Mapping[str, Callable[[np.ndarray], np.ndarray]] = {
    "sin": np.sin,
    "cos": np.cos,
    "tan": np.tan,
    "exp": np.exp,
    "log": np.log,
    "sqrt": np.sqrt,
    "abs": np.abs,
    "identity": lambda values: values,
}


def _stat_function(table: ColumnTable, params: Mapping[str, Any], *, scales: Any) -> ColumnTable:
    """`StatFunction$compute_group()`：`fun` 在 `xlim`（或 x 标度范围）上的网格求值。"""
    fun = params.get("fun")
    if fun is None:
        raise BuildError("stat_function 需要 fun（可调用；字符串别名只支持基础函数）")
    if isinstance(fun, str):
        target = _FUNCTION_ALIASES.get(fun)
        if target is None:
            raise BuildError(
                f"stat_function 的 fun 字符串别名不认识：{fun!r}；"
                f"可用：{', '.join(sorted(_FUNCTION_ALIASES))}，或传可调用"
            )
        function: Callable[[np.ndarray], Any] = target
    elif callable(fun):
        function = fun
    else:
        raise BuildError(f"stat_function 的 fun 必须是可调用，收到 {fun!r}")
    n = int(params.get("n", 101))
    if n < 1:
        raise BuildError(f"stat_function 的 n 必须是正整数，收到 {n!r}")
    args = params.get("args") or {}
    if not isinstance(args, Mapping):
        raise BuildError("stat_function 的 args 必须是映射（R 的 list(...)）")
    xlim = params.get("xlim")
    x_scale = scales.scale("x") if scales is not None else None
    if xlim is None:
        if x_scale is None:
            limits = (0.0, 1.0)
        else:
            limits = _dimension(scales, "x", np.array([], dtype=np.float64))
    else:
        values = np.asarray(xlim, dtype=np.float64)
        if values.size != 2:
            raise BuildError(f"stat_function 的 xlim 必须是长度 2 的序列，收到 {xlim!r}")
        limits = (float(values[0]), float(values[1]))
    xseq = _r_seq_length(limits[0], limits[1], n)
    discrete = x_scale is not None and bool(getattr(x_scale, "discrete", False))
    if discrete or x_scale is None:
        x_trans = xseq
    else:
        transform = getattr(x_scale, "transform_", None)
        x_trans = xseq if transform is None else np.asarray(transform.inverse(xseq))
    y_out = np.asarray(function(x_trans, **dict(args)), dtype=np.float64)
    if y_out.shape != xseq.shape:
        raise BuildError(
            f"stat_function 的 fun 必须向量化：返回形状 {y_out.shape} 与 x 网格 {xseq.shape} 不符"
        )
    y_scale = scales.scale("y") if scales is not None else None
    if y_scale is not None and not getattr(y_scale, "discrete", False):
        transform = getattr(y_scale, "transform_", None)
        if transform is not None:
            transformed, missing = transform.transform(y_out)
            y_out = np.where(missing, math.nan, transformed)
    columns: list[tuple[str, Column]] = [
        ("x", _float_column(xseq)),
        ("y", _float_column(y_out)),
    ]
    for name, column in _items(table):
        if name in ("x", "y"):
            continue
        values = _column_values(column)
        columns.append((name, _repeat_constant(column, values[0], xseq.size)))
    return ColumnTable(columns)


# ---------------------------------------------------------------------------
# stat_connect
# ---------------------------------------------------------------------------

_CONNECTIONS: Mapping[str, tuple[tuple[float, float], ...]] = {
    "hv": ((1.0, 0.0), (1.0, 1.0)),
    "vh": ((0.0, 0.0), (0.0, 1.0)),
    "mid": ((0.5, 0.0), (0.5, 1.0)),
    "linear": ((0.0, 0.0), (1.0, 1.0)),
}

_X_AES = ("x", "xmin", "xmax", "xend", "xintercept")
_Y_AES = ("y", "ymin", "ymax", "yend", "yintercept")


def _connection_matrix(value: Any) -> np.ndarray | None:
    if value is None:
        value = "hv"
    if isinstance(value, str):
        matrix = _CONNECTIONS.get(value)
        if matrix is None:
            raise BuildError(
                f"stat_connect 的 connection 不认识：{value!r}；"
                f"可用：{', '.join(sorted(_CONNECTIONS))}，或给 2 列的数值矩阵"
            )
        return np.asarray(matrix, dtype=np.float64)
    matrix = np.asarray(value, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[1] != 2:
        raise BuildError(
            "stat_connect 的 connection 必须是 2 列的数值矩阵（或 hv / vh / mid / linear）"
        )
    if not np.all(np.isfinite(matrix)):
        raise BuildError("stat_connect 的 connection 不能含缺失 / 非有限值")
    if matrix.shape[0] < 1:
        return None
    return matrix


def _stat_connect(table: ColumnTable, params: Mapping[str, Any], *, flipped: bool) -> ColumnTable:
    """`StatConnect$compute_group()`：按 `connection` 矩阵在相邻点之间插值。"""
    connection = _connection_matrix(params.get("connection"))
    work = _flip_table(table) if flipped else table
    x_names = [name for name in work.names if name in _X_AES]
    y_names = [name for name in work.names if name in _Y_AES]
    if not x_names or not y_names:
        raise BuildError("stat_connect 需要 x / y 系列美学")

    def group_fn(sub: ColumnTable, rows: np.ndarray) -> list[tuple[str, Column]] | None:
        del rows
        n = sub.nrows
        if n <= 1 or connection is None:
            return [(name, column) for name, column in _items(sub)]
        x_main = np.asarray(_column_values(sub.column(x_names[0])), dtype=np.float64)
        order = np.argsort(x_main, kind="stable")
        data = {name: _column_values(column) for name, column in _items(sub)}
        data = {name: values[order] for name, values in data.items()}
        m = connection.shape[0]
        before = np.repeat(np.arange(n - 1), m)
        after = np.repeat(np.arange(1, n), m)
        x_just = np.tile(connection[:, 0], n - 1)
        y_just = np.tile(connection[:, 1], n - 1)
        result: dict[str, np.ndarray] = {}
        for name in x_names:
            values = np.asarray(data[name], dtype=np.float64)
            result[name] = values[before] * (1.0 - x_just) + values[after] * x_just
        for name in y_names:
            values = np.asarray(data[name], dtype=np.float64)
            result[name] = values[before] * (1.0 - y_just) + values[after] * y_just
        new_rows = len(before)
        prepend = not np.allclose(connection[0], (0.0, 0.0))
        append = not np.allclose(connection[m - 1], (1.0, 1.0))
        total = new_rows + int(prepend) + int(append)
        columns: list[tuple[str, Column]] = []
        for name, column in _items(sub):
            if name in result:
                pieces = [result[name]]
                if prepend:
                    pieces.insert(0, np.asarray([data[name][0]], dtype=np.float64))
                if append:
                    pieces.append(np.asarray([data[name][n - 1]], dtype=np.float64))
                columns.append((name, _float_column(np.concatenate(pieces))))
            else:
                values = np.asarray(data[name])
                pieces = [values[before]]
                if prepend:
                    pieces.insert(0, values[:1])
                if append:
                    pieces.append(values[n - 1 :])
                columns.append((name, _repeat_row_column(column, np.concatenate(pieces))))
        assert len(columns[0][1].values) == total
        return columns

    result = _compute_panel(work, group_fn, stat="connect")
    if result.nrows == 0:
        return _EMPTY
    return _flip_table(result) if flipped else result


def _repeat_row_column(column: Column, values: np.ndarray) -> Column:
    """把一列按行下标重排成新的 Column（保留 kind / levels）。"""
    if column.kind == "str":
        return _str_column([str(value) for value in values.tolist()])
    if column.kind == "categorical":
        return Column("categorical", np.asarray(values, dtype=np.int32), levels=column.levels)
    if column.kind == "bool":
        return _bool_column(np.asarray(values, dtype=bool))
    if column.kind == "int":
        return Column("int", np.asarray(values, dtype=np.float64))
    return _float_column(np.asarray(values, dtype=np.float64))


# ---------------------------------------------------------------------------
# stat_manual
# ---------------------------------------------------------------------------


def _column_table_to_mapping(table: ColumnTable) -> dict[str, np.ndarray]:
    """给用户函数的数据视图：列名 → numpy 数组（NA 是 NaN / None）。"""
    out: dict[str, np.ndarray] = {}
    for name, column in _items(table):
        values = np.asarray(column.values)
        mask = np.asarray(column.na_mask, dtype=bool)
        if column.kind in ("str", "categorical"):
            text = values.astype(object)
            text[mask] = None
            out[name] = text
        elif column.kind == "int":
            integer = values.astype(np.int64)
            out[name] = integer
        else:
            numeric = values.astype(np.float64)
            numeric[mask] = np.nan
            out[name] = numeric
    return out


def _mapping_to_columns(values: Any) -> list[tuple[str, Column]]:
    """用户函数的返回值（dict / ColumnTable）→ 列。"""
    if isinstance(values, ColumnTable):
        return list(_items(values))
    if not isinstance(values, Mapping):
        raise BuildError(
            f"stat_manual 的 fun 必须返回映射或 ColumnTable，收到 {type(values).__name__}"
        )
    columns: list[tuple[str, Column]] = []
    for name, items in values.items():
        array = np.asarray(items)
        if array.ndim != 1:
            raise BuildError(f"stat_manual 的 fun 返回的 {name!r} 必须是一维序列")
        if array.dtype.kind in ("U", "S", "O"):
            columns.append((str(name), _str_column([str(item) for item in array.tolist()])))
        elif array.dtype.kind == "b":
            columns.append((str(name), _bool_column(array)))
        elif array.dtype.kind in ("i", "u"):
            columns.append((str(name), Column("int", array.astype(np.float64))))
        else:
            columns.append((str(name), _float_column(array.astype(np.float64))))
    return columns


def _stat_manual(table: ColumnTable, params: Mapping[str, Any]) -> ColumnTable:
    """`StatManual`：`fun(data, **args)`；缺省是恒等。"""
    fun = params.get("fun")
    if fun is None:
        fun = lambda data: data  # noqa: E731 - 上游 `fun = identity`
    elif isinstance(fun, str):
        raise BuildError(
            f"stat_manual 的 fun 必须是可调用，收到字符串 {fun!r}（上游也要求函数对象）"
        )
    elif not callable(fun):
        raise BuildError(f"stat_manual 的 fun 必须是可调用，收到 {fun!r}")
    args = params.get("args") or {}
    if not isinstance(args, Mapping):
        raise BuildError("stat_manual 的 args 必须是映射（R 的 list(...)）")

    def group_fn(sub: ColumnTable, rows: np.ndarray) -> list[tuple[str, Column]] | None:
        del rows
        data = _column_table_to_mapping(sub)
        output = fun(data, **dict(args))
        if output is data:
            return [(name, column) for name, column in _items(sub)]
        return _mapping_to_columns(output)

    return _compute_panel(table, group_fn, stat="manual")

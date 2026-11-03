"""日期时间标度的纯计算工具：`pretty()`、`breaks_width()`、格式化。

M2-4 A 段的 `scale_*_date` / `_datetime` / `_time` 把日期时间搬进连续标度的
数值空间（`ggio` 已经归一成「自 1970-01-01 起的天 / 秒」，见
`docs/notes/data.md`），断点与标签的默认值照上游：

- 变换的默认断点是 `breaks_pretty()` = base R 的 `pretty()`。这里逐行移植
  `R_pretty()`（`src/appl/pretty.c` + `pretty.default`），所以断点与 R 浮点
  相等，而不是换一套 `extended_breaks`。
- `date_breaks = "1 month"` 走 `scales::breaks_width()` → `fullseq()`；日 / 周 /
  月 / 年 / 季度的对齐规则照 `cut.Date()` / `cut.POSIXt()`（周一为一周之始，
  月/年是日历对齐）。`hms` 按「一天内的秒」做数值对齐。
- 默认标签是 R 的 `format()`：Date → `%Y-%m-%d`，POSIXct → 有非零时刻时
  `%Y-%m-%d %H:%M:%S`（全是零点时只到日期，与 `format.POSIXct` 一致），
  hms → `%H:%M:%S`。

本模块只依赖标准库；`scales.py` 负责把结果接进标度。
"""

from __future__ import annotations

import datetime as _dt
import math
from collections.abc import Sequence
from typing import Any

__all__ = [
    "DATE_EPOCH",
    "breaks_width_date",
    "breaks_width_hms",
    "breaks_width_time",
    "format_date",
    "format_datetime",
    "format_hms",
    "parse_unit_spec",
    "pretty",
    "unit_seconds",
]

_EPOCH = _dt.date(1970, 1, 1)
_EPOCH_DT = _dt.datetime(1970, 1, 1, tzinfo=_dt.UTC)
DATE_EPOCH = _EPOCH

_DAY = 86400.0


# ---------------------------------------------------------------------------
# base R pretty()
# ---------------------------------------------------------------------------


def _rp(
    lo: float, up: float, ndiv: int, min_n: int, shrink: float, h: float, h5: float, f_min: float
) -> tuple[float, float, int]:
    """`R_pretty()` 的移植（bounds = TRUE）。返回 `(l, u, ndiv)`。"""
    lo_, up_ = lo, up
    dx = up_ - lo_
    eps = 1e-10
    dbL_eps = 2.220446049250313e-16
    max_f = 1.25

    if dx == 0 and up_ == 0:
        cell = 1.0
        i_small = True
    else:
        cell = max(abs(lo_), abs(up_))
        upper = 1 + (1 / (1 + h) if h5 >= 1.5 * h + 0.5 else 1.5 / (1 + h5))
        upper *= max(1, ndiv) * dbL_eps
        i_small = dx < cell * upper * 3

    if i_small:
        if cell > 10:
            cell = 9 + cell / 10
        cell *= shrink
        if min_n > 1:
            cell /= min_n
    else:
        cell = dx
        if math.isfinite(dx):
            if ndiv > 1:
                cell /= ndiv
        else:  # pragma: no cover - 非有限范围在调用方已被过滤
            cell = up_ / ndiv - lo_ / ndiv

    subsmall = f_min * 5e-324
    if subsmall == 0:
        subsmall = 5e-324
    if cell < subsmall:
        cell = subsmall
    elif cell > 1.7976931348623157e308 / max_f:
        cell = 1.7976931348623157e308 / max_f

    base = 10.0 ** math.floor(math.log10(cell))

    unit = base
    if (candidate := 2 * base) - cell < h * (cell - unit):
        unit = candidate
        if (candidate := 5 * base) - cell < h5 * (cell - unit):
            unit = candidate
            if (candidate := 10 * base) - cell < h * (cell - unit):
                unit = candidate

    ns = math.floor(lo_ / unit + eps)
    nu = math.ceil(up_ / unit - eps)

    while ns * unit > lo_ + eps * unit:
        ns -= 1
    while nu * unit < up_ - eps * unit:
        nu += 1

    k = int(0.5 + nu - ns)
    if k < min_n:
        k = min_n - k
        if lo_ == 0 and ns == 0 and up_ != 0:
            nu += k
        elif up_ == 0 and nu == 0 and lo_ != 0:
            ns -= k
        elif ns >= 0:
            nu += k // 2
            ns -= k // 2 + k % 2
        else:
            ns -= k // 2
            nu += k // 2 + k % 2
        ndiv = min_n
    else:
        ndiv = k

    if ns * unit < lo_:
        lo_ = ns * unit
    if nu * unit > up_:
        up_ = nu * unit
    return lo_, up_, ndiv


def pretty(low: float, high: float, n: int = 5) -> tuple[float, ...]:
    """base R `pretty()`（`n = 5`、默认参数、`bounds = TRUE`）。

    与 R 的差别只有一处：R 会忽略非有限值后返回空向量，这里同样返回 `()`。
    """
    values = [float(value) for value in (low, high) if math.isfinite(float(value))]
    if not values:
        return ()
    lo, hi = min(values), max(values)
    low_value, high_value, ndiv = _rp(
        lo, hi, max(1, int(n)), max(1, int(n)) // 3, 0.75, 1.5, 2.75, 0.5**20
    )
    if ndiv <= 0:
        return (low_value, high_value)
    step = (high_value - low_value) / ndiv
    out = [low_value + index * step for index in range(ndiv + 1)]
    delta = abs(high_value - low_value) / ndiv
    return tuple(0.0 if abs(value) < 1e-14 * delta else value for value in out)


# ---------------------------------------------------------------------------
# scales::breaks_width()
# ---------------------------------------------------------------------------


def parse_unit_spec(text: str) -> tuple[float, str]:
    """`"2 months"` → `(2.0, "month")`；`"week"` → `(1.0, "week")`。

    与 `scales:::parse_unit_spec()` 一样：可选倍数 + 单位（去掉末尾的 s）。
    """
    parts = str(text).strip().split()
    if not parts:
        raise ValueError(f"无法解析时间间隔：{text!r}")
    if len(parts) == 1:
        mult, unit = 1.0, parts[0]
    elif len(parts) == 2:
        mult, unit = float(parts[0]), parts[1]
    else:
        raise ValueError(f"无法解析时间间隔：{text!r}")
    unit = unit[:-1] if unit.endswith("s") else unit
    if unit == "minute":
        unit = "min"
    if unit == "second":
        unit = "sec"
    if unit == "hour":
        unit = "hour"
    if unit == "hms":
        unit = "sec"
    return mult, unit


def unit_seconds(text: str) -> float:
    """`scales:::unit_seconds()`：一个间隔规格的秒数（月 = 31 天，年 = 365 天）。"""
    mult, unit = parse_unit_spec(text)
    seconds = {
        "sec": 1.0,
        "min": 60.0,
        "hour": 3600.0,
        "day": _DAY,
        "week": 7 * _DAY,
        "month": 31 * _DAY,
        "year": 365 * _DAY,
    }
    if unit not in seconds:
        raise ValueError(f"不支持的时间单位：{unit!r}")
    return mult * seconds[unit]


def _round_any(value: float, accuracy: float, *, up: bool) -> float:
    """`scales:::round_any()` 的 floor / ceiling 两种（避免浮点尾巴）。"""
    ratio = value / accuracy
    rounded = math.ceil(ratio - 1e-12) if up else math.floor(ratio + 1e-12)
    return rounded * accuracy


def _seq(start: float, stop: float, step: float) -> list[float]:
    """闭区间等距序列（含两端，容忍浮点误差）。"""
    if step <= 0:
        return [start]
    count = math.floor((stop - start) / step + 1e-9)
    return [start + index * step for index in range(max(0, count) + 1)]


def fullseq_numeric(low: float, high: float, size: float) -> tuple[float, ...]:
    """`scales:::fullseq.numeric()`：按数值栅格 floor / ceil 后等距取点。"""
    low, high = sorted((float(low), float(high)))
    if low == high:
        return (low - size / 2, low + size / 2)
    start = _round_any(low, size, up=False)
    stop = _round_any(high, size, up=True)
    return tuple(_seq(start, stop, size))


# -- 日历对齐 ---------------------------------------------------------------


def _date_from_days(days: float) -> _dt.date:
    return _EPOCH + _dt.timedelta(days=float(days))


def _days_from_date(value: _dt.date) -> float:
    return float((value - _EPOCH).days)


def _month_floor(value: _dt.date) -> _dt.date:
    return value.replace(day=1)


def _month_ceil_at(value: _dt.date, step_months: int) -> _dt.date:
    """`ceiling_date(value, "N months")`：先往后推 31×N 天，再对齐到月首。"""
    shifted = value + _dt.timedelta(days=31 * step_months)
    return _month_floor(shifted)


def _add_months(value: _dt.date, months: int) -> _dt.date:
    total = value.year * 12 + (value.month - 1) + months
    return _dt.date(total // 12, total % 12 + 1, 1)


def _week_floor(value: _dt.date) -> _dt.date:
    """`cut.Date(..., start.on.monday = TRUE)`：周一是一周之始。"""
    return value - _dt.timedelta(days=value.weekday())


def fullseq_date(low: float, high: float, spec: str) -> tuple[float, ...]:
    """`scales:::fullseq.Date()`（值是天数）。

    日 / 周用数值栅格；月 / 年 / 季度按日历对齐（`cut.Date()` 的口径）。
    """
    low, high = sorted((float(low), float(high)))
    mult, unit = parse_unit_spec(spec)
    lo_date = _date_from_days(low)
    hi_date = _date_from_days(high)

    if unit == "day":
        return fullseq_numeric(low, high, mult)
    if unit == "week":
        step = 7.0 * mult
        start = _week_floor(lo_date)
        stop = _week_floor(hi_date + _dt.timedelta(days=round(7 * mult)))
        days = _seq(_days_from_date(start), _days_from_date(stop), step)
        return tuple(days)
    if unit in ("month", "quarter", "year"):
        step_months = {"month": int(mult), "quarter": 3 * int(mult), "year": 12 * int(mult)}[unit]
        start = _month_floor(lo_date)
        if unit == "year":
            start = start.replace(month=1)
        elif unit == "quarter":
            start = start.replace(month=3 * ((start.month - 1) // 3) + 1)
        stop = _month_ceil_at(hi_date, step_months)
        # 按日历逐格生成（月长度不同，不能按天数等距）。
        out: list[float] = []
        current = start
        while current <= stop:
            out.append(_days_from_date(current))
            current = _add_months(current, step_months)
        return tuple(out)
    raise ValueError(f"Date 标度不支持的时间单位：{unit!r}")


def fullseq_time(low: float, high: float, spec: str) -> tuple[float, ...]:
    """`scales:::fullseq.POSIXt()`（值是秒，按 UTC 日历对齐）。"""
    low, high = sorted((float(low), float(high)))
    mult, unit = parse_unit_spec(spec)
    if unit in ("sec", "min"):
        return fullseq_numeric(low, high, mult * (1.0 if unit == "sec" else 60.0))
    if unit == "hour":
        return fullseq_numeric(low, high, mult * 3600.0)

    lo_dt = _EPOCH_DT + _dt.timedelta(seconds=low)
    hi_dt = _EPOCH_DT + _dt.timedelta(seconds=high)

    if unit == "day":
        step = mult * _DAY
        start = lo_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        stop = (hi_dt + _dt.timedelta(seconds=mult * _DAY)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return tuple(_seq(_seconds_from_dt(start), _seconds_from_dt(stop), step))

    if unit == "week":
        start = _week_floor(lo_dt.date())
        stop = _week_floor((hi_dt + _dt.timedelta(seconds=mult * 7 * _DAY)).date())
        step = 7.0 * mult * _DAY
        return tuple(_seq(_seconds_from_date(start), _seconds_from_date(stop), step))

    if unit in ("month", "quarter", "year"):
        step_months = {"month": int(mult), "quarter": 3 * int(mult), "year": 12 * int(mult)}[unit]
        start = _month_floor(lo_dt.date())
        if unit == "year":
            start = start.replace(month=1)
        elif unit == "quarter":
            start = start.replace(month=3 * ((start.month - 1) // 3) + 1)
        stop = _month_ceil_at(hi_dt.date(), step_months)
        out: list[float] = []
        current = start
        while current <= stop:
            out.append(_seconds_from_date(current))
            current = _add_months(current, step_months)
        return tuple(out)
    raise ValueError(f"datetime 标度不支持的时间单位：{unit!r}")


def _seconds_from_date(value: _dt.date) -> float:
    return float((value - _EPOCH).days) * _DAY


def _seconds_from_dt(value: _dt.datetime) -> float:
    return (value - _EPOCH_DT).total_seconds()


def _limits_pair(limits: Any, high: float | None = None) -> tuple[float, float]:
    """`breaks_width()` 的回调口径：上游收**一个** limits 向量（`function(x)`），

    本仓历史上写成 `(low, high)` 两个位置参数；两种形态都接受，避免调用点各记一套。
    """
    if high is None:
        low_value, high_value = (float(value) for value in limits)
        return low_value, high_value
    return float(limits), float(high)


def breaks_width_date(spec: str):
    """`breaks_width(spec)` 作用在天数上。"""

    def breaks(limits: Any, n: int | None = None, high: float | None = None):
        low, upper = _limits_pair(limits, high)
        return fullseq_date(low, upper, spec)

    return breaks


def breaks_width_time(spec: str):
    """`breaks_width(spec)` 作用在秒上。"""

    def breaks(limits: Any, n: int | None = None, high: float | None = None):
        low, upper = _limits_pair(limits, high)
        return fullseq_time(low, upper, spec)

    return breaks


def breaks_width_hms(spec: str):
    """`breaks_width(spec)` 作用在「一天内的秒」上（difftime：纯数值栅格）。"""
    width = unit_seconds(spec)

    def breaks(limits: Any, n: int | None = None, high: float | None = None):
        low, upper = _limits_pair(limits, high)
        return fullseq_numeric(low, upper, width)

    return breaks


# ---------------------------------------------------------------------------
# 默认标签（R 的 format()）
# ---------------------------------------------------------------------------


def format_date(days: float, fmt: str = "%Y-%m-%d") -> str:
    """Date 的默认 / 自定义格式（值是自 epoch 起的天数）。"""
    return _date_from_days(round(float(days))).strftime(fmt)


def format_datetime(seconds: float, fmt: str | None = None) -> str:
    """POSIXct 的默认 / 自定义格式（UTC）。"""
    value = _EPOCH_DT + _dt.timedelta(seconds=float(seconds))
    if fmt is None:
        fmt = "%Y-%m-%d" if value.hour == value.minute == value.second == 0 else "%Y-%m-%d %H:%M:%S"
    return value.strftime(fmt)


def format_hms(seconds: float, fmt: str = "%H:%M:%S") -> str:
    """一天内的秒 → `HH:MM:SS`（hms 的默认口径）。"""
    return (_EPOCH_DT + _dt.timedelta(seconds=float(seconds))).strftime(fmt)


def date_formatter(kind: str, fmt: str | None):
    """把 (kind, format) 绑成一个 `labels(breaks)` 回调。"""
    if kind == "date":
        return lambda values: [format_date(value, fmt or "%Y-%m-%d") for value in values]
    if kind == "time":
        return lambda values: [format_datetime(value, fmt) for value in values]
    return lambda values: [format_hms(value, fmt or "%H:%M:%S") for value in values]


def calendar_breaks(kind: str, spec: str):
    """按 trans 类型选 `breaks_width` 的实现。"""
    if kind == "date":
        return breaks_width_date(spec)
    if kind == "time":
        return breaks_width_time(spec)
    return breaks_width_hms(spec)


def as_sequence(values: Sequence[float]) -> tuple[float, ...]:
    return tuple(float(value) for value in values)


# ---------------------------------------------------------------------------
# pretty.Date / pretty.POSIXt（日期时间标度的默认断点 + 自带格式）
# ---------------------------------------------------------------------------

_DAY_SECONDS = 86400.0
_YEAR = 365.25 * _DAY_SECONDS
_MONTH = _YEAR / 12


class _Step:
    __slots__ = ("format", "months", "seconds", "spec", "start")

    def __init__(self, spec, seconds=None, months=0, start=None, fmt=None):
        self.spec = spec
        self.seconds = seconds
        self.months = months
        self.start = start
        self.format = fmt


def _steps_table(xspan: float) -> list[_Step]:
    """`pretty.Date` / `pretty.POSIXt` 的 step 阶梯（格式按上游规则继承）。"""
    day = _DAY_SECONDS
    hour = 3600.0
    minute = 60.0
    raw = [
        _Step("1 sec", 1, start="mins", fmt="%S"),
        _Step("2 secs", 2),
        _Step("5 secs", 5),
        _Step("10 secs", 10),
        _Step("15 secs", 15),
        _Step("30 secs", 30, fmt="%H:%M:%S"),
        _Step("1 min", minute, fmt="%H:%M"),
        _Step("2 mins", 2 * minute, start="hours"),
        _Step("5 mins", 5 * minute),
        _Step("10 mins", 10 * minute),
        _Step("15 mins", 15 * minute),
        _Step("30 mins", 30 * minute),
        _Step("1 hour", hour, fmt="%H:%M" if xspan <= day else "%b %d %H:%M"),
        _Step("3 hours", 3 * hour, start="days"),
        _Step("6 hours", 6 * hour, fmt="%b %d %H:%M"),
        _Step("12 hours", 12 * hour),
        _Step("1 DSTday", day, fmt="%b %d"),
        _Step("2 DSTdays", 2 * day),
        _Step("1 week", 7 * day, start="weeks"),
        _Step("halfmonth", _MONTH / 2, start="months"),
        _Step("1 month", None, months=1, fmt="%b" if xspan < _YEAR else "%b %Y"),
        _Step("3 months", None, months=3, start="years"),
        _Step("6 months", None, months=6, fmt="%Y-%m"),
        _Step("1 year", None, months=12, fmt="%Y"),
        _Step("2 years", None, months=24, start="decades"),
        _Step("5 years", None, months=60),
        _Step("10 years", None, months=120),
        _Step("20 years", None, months=240, start="centuries"),
        _Step("50 years", None, months=600),
        _Step("100 years", None, months=1200),
        _Step("200 years", None, months=2400),
        _Step("500 years", None, months=6000),
        _Step("1000 years", None, months=12000),
    ]
    for index in range(1, len(raw)):
        if raw[index].format is None:
            raw[index].format = raw[index - 1].format
        if raw[index].start is None:
            raw[index].start = raw[index - 1].start
    return raw


def _dt_from_seconds(seconds: float) -> _dt.datetime:
    return _EPOCH_DT + _dt.timedelta(seconds=float(seconds))


def _seconds_of(value: _dt.datetime) -> float:
    return (value - _EPOCH_DT).total_seconds()


def _advance(value: _dt.datetime, step: _Step) -> _dt.datetime:
    if step.months:
        total = value.year * 12 + (value.month - 1) + step.months
        year, month = divmod(total, 12)
        day = min(value.day, 28) if value.day > 28 else value.day
        base = value.replace(year=year, month=month + 1, day=day, microsecond=0)
        return base
    return value + _dt.timedelta(seconds=step.seconds)


def _trunc_to(value: _dt.datetime, unit: str | None) -> _dt.datetime:
    unit = unit or "days"
    midnight = value.replace(hour=0, minute=0, second=0, microsecond=0)
    if unit == "mins":
        return value.replace(second=0, microsecond=0)
    if unit == "hours":
        return value.replace(minute=0, second=0, microsecond=0)
    if unit == "days":
        return midnight
    if unit == "weeks":
        return midnight - _dt.timedelta(days=midnight.weekday())
    if unit == "months":
        return midnight.replace(day=1)
    if unit == "years":
        return midnight.replace(month=1, day=1)
    if unit == "decades":
        year = midnight.year - midnight.year % 10
        return midnight.replace(year=year, month=1, day=1)
    if unit == "centuries":
        year = midnight.year - midnight.year % 100
        return midnight.replace(year=year, month=1, day=1)
    return midnight


def _calc_steps(step: _Step, low: float, high: float) -> list[float]:
    start = _trunc_to(_dt_from_seconds(low), step.start)
    values = [_seconds_of(start)]
    current = start
    # `seqDtime(start, end = lim[2], by = spec)`：最后一点不晚于 lim[2]
    guard = 0
    while True:
        nxt = _advance(current, step)
        if nxt <= _dt_from_seconds(high):
            values.append(_seconds_of(nxt))
            current = nxt
            guard += 1
            if guard > 100000:  # pragma: no cover - 防御
                break
        else:
            break
    if not values:
        return []
    r1 = sum(1 for value in values if value <= low)
    r2 = len(values) + 1 - sum(1 for value in values if value >= high)
    if r2 == len(values) + 1:
        nxt = _advance(_dt_from_seconds(values[-1]), step)
        if _seconds_of(nxt) > values[-1]:
            values.append(_seconds_of(nxt))
        else:  # pragma: no cover
            r2 = len(values)
    return values[max(0, r1 - 1) : r2]


def _r_round(value: float) -> int:
    """R 的 `round()`：.5 取偶。"""
    return round(value)


def _pretty_datetime_like(
    values: Sequence[float], n: int, *, is_date: bool
) -> tuple[list[float], str]:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    if not finite:
        return [], "%Y-%m-%d" if is_date else "%Y-%m-%d %H:%M:%S"
    low, high = min(finite), max(finite)
    span_days = (high - low) / _DAY_SECONDS
    min_n = max(1, n // 2)

    if is_date and span_days <= n:
        # 纯日刻度：`seq.Date(x1 - m, x2 + m2, by = "1 day")`。
        r = _r_round(n - span_days)
        m = max(0, r // 2)
        m2 = m + (r % 2)
        start = low - m * _DAY_SECONDS
        stop = high + m2 * _DAY_SECONDS
        while round((stop - start) / _DAY_SECONDS) + 1 < min_n + 1:
            if m < m2:
                m += 1
            else:
                m2 += 1
            start = low - m * _DAY_SECONDS
            stop = high + m2 * _DAY_SECONDS
        count = round((stop - start) / _DAY_SECONDS)
        out = [
            round(start / _DAY_SECONDS) * _DAY_SECONDS + index * _DAY_SECONDS
            for index in range(count + 1)
        ]
        return out, "%b %d"

    xspan = high - low
    steps = _steps_table(xspan)
    step_seconds = [
        (step.seconds if step.seconds is not None else step.months * _MONTH) for step in steps
    ]
    initial = min(range(len(steps)), key=lambda index: abs(xspan / step_seconds[index] - n))
    initial_index = initial

    def calc(index: int) -> list[float]:
        return _calc_steps(steps[index], low, high)

    current = calc(initial)
    while len(current) - 1 < min_n:
        if initial > 0:
            initial -= 1
            current = calc(initial)
        else:  # pragma: no cover - 极小范围
            break

    dn = len(current) - 1 - n
    if dn > 0:
        nl = sum(1 for value in current if value <= low) - 1
        nr = sum(1 for value in current if value >= high) - 1
        if nl > 0 or nr > 0:
            total = nl + nr
            if dn < total:
                nl = _r_round(dn * nl / total)
                nr = dn - nl
            keep = current[nl : len(current) - nr if nr > 0 else len(current)]
            current = keep

    dn = len(current) - 1 - n
    if dn == 0 or (dn > 0 and initial < initial_index) or (dn < 0 and initial == 0):
        return current, steps[initial].format

    new_index = min(initial + 1, len(steps) - 1) if dn > 0 else initial - 1
    new_values = calc(new_index)
    new_n = len(new_values) - 1
    if new_n < min_n:
        new_n = -math.inf
    if abs(new_n - n) < abs(dn):
        return new_values, steps[new_index].format
    return current, steps[initial].format


def pretty_date(days: Sequence[float], n: int = 5) -> tuple[list[float], str]:
    """`pretty.Date()`：返回（天数断点, 标签格式）。"""
    seconds = [float(value) * _DAY_SECONDS for value in days]
    found, fmt = _pretty_datetime_like(seconds, n, is_date=True)
    return [round(value / _DAY_SECONDS) * 1.0 for value in found], fmt


def pretty_datetime(seconds: Sequence[float], n: int = 5) -> tuple[list[float], str]:
    """`pretty.POSIXt()`：返回（秒断点, 标签格式）。"""
    return _pretty_datetime_like(seconds, n, is_date=False)

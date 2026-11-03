"""上游快照复刻：sec_axis, custom transform。

源：sec-axis/sec-axis-custom-transform.svg（vdiffr 名 "sec_axis, custom transform"）。

R（DInfanger 的 #2798 复现）：

    magnify_trans_log <- function(interval_low = 0.05, interval_high = 1,
                                  reducer = 0.05, reducer2 = 8) {
      trans <- Vectorize(function(x, i_low, i_high, r, r2) {
        if (is.na(x) || (x >= i_low & x <= i_high)) x
        else if (x < i_low) log10(x / r) / r2 + i_low
        else log10((x - i_high) / r + i_high) / r2
      })
      inv <- Vectorize(function(x, i_low, i_high, r, r2) {
        if (is.na(x) || (x >= i_low & x <= i_high)) x
        else if (x < i_low) 10^(-(i_low - x) * r2) * r
        else i_high + 10^(x * r2) * r - i_high * r
      })
      new_transform(name = "customlog", transform = trans, inverse = inv, domain = c(1e-16, Inf))
    }

    x <- seq(-1, 1, length.out = 1000)
    y <- c(x[x < 0] + 1, -x[x > 0] + 1) + 1e-6
    dat <- data_frame(x = c(NA, x), y = c(1, y))

    ggplot(dat, aes(x, y)) + geom_line(linewidth = 1, na.rm = TRUE) +
      scale_y_continuous(
        transform = magnify_trans_log(interval_low = 0.5, interval_high = 1,
                                      reducer = 0.5, reducer2 = 8),
        breaks = c(0.001, 0.01, 0.1, 0.5, 0.6, 0.7, 0.8, 0.9, 1),
        limits = c(0.001, 1),
        sec.axis = sec_axis(transform = ~ . * (1 / 2),
                            breaks = c(0.001, 0.01, 0.1, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5))
      ) +
      theme_linedraw()
"""

import numpy as np

from ggcore.plot import aes, geom_line, ggplot, labs, scale_y_continuous, sec_axis
from ggcore.scales import new_transform
from ggcore.theme import theme_linedraw
from ggio.frame import to_column_table


def _magnify(
    interval_low: float = 0.05,
    interval_high: float = 1.0,
    reducer: float = 0.05,
    reducer2: float = 8.0,
):
    """`magnify_trans_log()`：把 (0, interval_low) 拉长、区间内保恒等。"""

    def transform(values):
        values = np.asarray(values, dtype=np.float64)
        out = np.array(values, dtype=np.float64, copy=True)
        low = np.isfinite(values) & (values < interval_low)
        high = np.isfinite(values) & (values > interval_high)
        with np.errstate(divide="ignore", invalid="ignore"):
            out[low] = np.log10(values[low] / reducer) / reducer2 + interval_low
            out[high] = (
                np.log10((values[high] - interval_high) / reducer + interval_high) / reducer2
            )
        return out

    def inverse(values):
        values = np.asarray(values, dtype=np.float64)
        out = np.array(values, dtype=np.float64, copy=True)
        low = np.isfinite(values) & (values < interval_low)
        high = np.isfinite(values) & (values > interval_high)
        with np.errstate(over="ignore", invalid="ignore"):
            out[low] = 10.0 ** (-(interval_low - values[low]) * reducer2) * reducer
            out[high] = (
                interval_high
                + 10.0 ** (values[high] * reducer2) * reducer
                - interval_high * reducer
            )
        return out

    return new_transform("customlog", transform, inverse, domain=(1e-16, np.inf))


_X = np.linspace(-1.0, 1.0, 1000)
_Y = np.concatenate([_X[_X < 0] + 1.0, -_X[_X > 0] + 1.0]) + 1e-6

DATA = {
    "x": [float("nan"), *[float(value) for value in _X]],
    "y": [1.0, *[float(value) for value in _Y]],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_line(linewidth=1, na_rm=True)
        + scale_y_continuous(
            transform=_magnify(interval_low=0.5, interval_high=1.0, reducer=0.5, reducer2=8.0),
            breaks=(0.001, 0.01, 0.1, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
            limits=(0.001, 1.0),
            **{
                "sec.axis": sec_axis(
                    lambda v: v * 0.5,
                    breaks=(0.001, 0.01, 0.1, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5),
                )
            },
        )
        + theme_linedraw()
        + labs(title="sec_axis, custom transform")
    )
    return {"plot": p, "size": [10, 8]}

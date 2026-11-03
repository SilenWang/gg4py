"""上游快照复刻：scale_x_date(labels = label_date("%m/%d"))。

源：scale_date/scale-x-date-labels-label-date-m-d.svg。
vdiffr 名：scale_x_date(labels = label_date("%m/%d"))。

`set.seed(321)` 的 `dx` / `price` 由 R 4.5 直接导出
（`sample(100, 50)` + `runif(50)`），不是本仓生成的随机数。

expected.svg 是上游那份，未改写。
"""

import datetime

from ggcore.plot import aes, geom_line, ggplot, labs, scale_x_date
from ggcore.scales_date import date_formatter
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {
    "dx": [
        datetime.date(2012, 2, 29),
        datetime.date(2012, 3, 3),
        datetime.date(2012, 3, 6),
        datetime.date(2012, 3, 7),
        datetime.date(2012, 3, 8),
        datetime.date(2012, 3, 10),
        datetime.date(2012, 3, 12),
        datetime.date(2012, 3, 14),
        datetime.date(2012, 3, 16),
        datetime.date(2012, 3, 17),
        datetime.date(2012, 3, 19),
        datetime.date(2012, 3, 22),
        datetime.date(2012, 3, 24),
        datetime.date(2012, 3, 28),
        datetime.date(2012, 3, 29),
        datetime.date(2012, 3, 30),
        datetime.date(2012, 4, 2),
        datetime.date(2012, 4, 3),
        datetime.date(2012, 4, 4),
        datetime.date(2012, 4, 9),
        datetime.date(2012, 4, 13),
        datetime.date(2012, 4, 14),
        datetime.date(2012, 4, 15),
        datetime.date(2012, 4, 16),
        datetime.date(2012, 4, 17),
        datetime.date(2012, 4, 19),
        datetime.date(2012, 4, 22),
        datetime.date(2012, 4, 26),
        datetime.date(2012, 4, 27),
        datetime.date(2012, 4, 28),
        datetime.date(2012, 4, 30),
        datetime.date(2012, 5, 1),
        datetime.date(2012, 5, 2),
        datetime.date(2012, 5, 5),
        datetime.date(2012, 5, 11),
        datetime.date(2012, 5, 13),
        datetime.date(2012, 5, 15),
        datetime.date(2012, 5, 16),
        datetime.date(2012, 5, 17),
        datetime.date(2012, 5, 18),
        datetime.date(2012, 5, 19),
        datetime.date(2012, 5, 20),
        datetime.date(2012, 5, 22),
        datetime.date(2012, 5, 26),
        datetime.date(2012, 5, 27),
        datetime.date(2012, 5, 28),
        datetime.date(2012, 5, 29),
        datetime.date(2012, 6, 3),
        datetime.date(2012, 6, 6),
        datetime.date(2012, 6, 7),
    ],
    "price": [
        0.9616501040,
        0.1624869567,
        0.0412904064,
        0.1565073295,
        0.5024147367,
        0.7918214588,
        0.0852337643,
        0.5842047508,
        0.3109124061,
        0.8940171362,
        0.6412378051,
        0.9455218136,
        0.7880687607,
        0.2636332642,
        0.1869768053,
        0.6517536691,
        0.9137707094,
        0.9281317706,
        0.5269326805,
        0.6258383121,
        0.1299404269,
        0.7331085226,
        0.5964183512,
        0.4944653544,
        0.4151498503,
        0.1815023392,
        0.0621891215,
        0.5988593667,
        0.6920898366,
        0.5219928171,
        0.2529071253,
        0.1591295504,
        0.5071416628,
        0.6335240912,
        0.5045890666,
        0.6020734545,
        0.1328208803,
        0.8721084816,
        0.1653388974,
        0.9785593627,
        0.4015488112,
        0.6336023652,
        0.6511391723,
        0.5311487252,
        0.9967931078,
        0.8299274566,
        0.9569348753,
        0.8791833892,
        0.2694185616,
        0.5792052438,
    ],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="dx", y="price"))
        + geom_line()
        + scale_x_date(labels=date_formatter("date", "%m/%d"))
        + theme_test()
        + labs(title='scale_x_date(labels = label_date("%m/%d"))')
    )
    return {"plot": p, "size": [10, 8]}

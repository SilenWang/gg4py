"""上游快照复刻：sec_axis, datetime scale。

源：sec-axis/sec-axis-datetime-scale.svg（vdiffr 名 "sec_axis, datetime scale"）。

R：

    df <- data_frame(
      x = as.POSIXct(c("2016-11-30 00:00:00", "2016-11-30 06:00:00",
                       "2016-11-30 12:00:00", "2016-11-30 18:00:00",
                       "2016-12-01 00:00:00"), tz = "UTC"),
      y = c(0, -1, 0, 1, 0)
    )
    ggplot(df, aes(x = x, y = y)) +
      geom_line() +
      scale_x_datetime("UTC", date_breaks = "2 hours", date_labels = "%I%p",
                       sec.axis = dup_axis(~ . - 8 * 60 * 60, name = "PST")) +
      theme_linedraw()

时间是 POSIXct（自 epoch 起的秒）。主轴是 UTC、每 2 小时一个断点；次轴把时间
平移 -8 小时（PST），标签用同一套日期格式。
"""

import datetime

from ggcore.plot import (
    aes,
    dup_axis,
    geom_line,
    ggplot,
    labs,
    scale_x_datetime,
)
from ggcore.theme import theme_linedraw
from ggio.frame import to_column_table

DATA = {
    "x": [
        datetime.datetime(2016, 11, 30, 0, 0, tzinfo=datetime.UTC),
        datetime.datetime(2016, 11, 30, 6, 0, tzinfo=datetime.UTC),
        datetime.datetime(2016, 11, 30, 12, 0, tzinfo=datetime.UTC),
        datetime.datetime(2016, 11, 30, 18, 0, tzinfo=datetime.UTC),
        datetime.datetime(2016, 12, 1, 0, 0, tzinfo=datetime.UTC),
    ],
    "y": [0.0, -1.0, 0.0, 1.0, 0.0],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_line()
        + scale_x_datetime(
            name="UTC",
            date_breaks="2 hours",
            date_labels="%I%p",
            **{"sec.axis": dup_axis(lambda seconds: seconds - 8.0 * 60.0 * 60.0, name="PST")},
        )
        + theme_linedraw()
        + labs(title="sec_axis, datetime scale")
    )
    return {"plot": p, "size": [10, 8]}

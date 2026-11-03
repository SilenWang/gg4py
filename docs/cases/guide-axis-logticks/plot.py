"""guide：`guide_axis_logticks()`（log10 轴的三档次刻度）。"""

from ggcore.plot import aes, geom_point, ggplot, guide_axis_logticks, scale_x_log10
from ggio.frame import to_column_table

DATA = {
    "x": [1.5, 1.8, 2.2, 2.6, 3.0, 3.4, 3.8, 4.2, 4.6, 5.0, 5.3, 5.6],
    "y": [26.0, 25.0, 24.5, 23.0, 22.5, 21.0, 20.5, 19.5, 18.0, 17.5, 16.5, 15.0],
}
SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point(shape=19, size=1.8)
        + scale_x_log10()
        + guide_axis_logticks("x")
    )
    return {"plot": p, "size": SIZE}

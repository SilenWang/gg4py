"""上游快照复刻：sec_axis, independent transformations。

源：sec-axis/sec-axis-independent-transformations.svg
（vdiffr 名 "sec_axis, independent transformations"）。

R：

    data <- data_frame(
      Value = c(0.18, 0.29, 0.35, 0.46, 0.50, 0.50, 0.51),
      Probability = c(0.045, 0.090, 0.136, 0.181, 0.227, 0.272, 0.318)
    )
    ggplot(data, aes(Probability, Value)) +
      geom_point() +
      scale_x_continuous(
        transform = scales::transform_probability(distribution = "norm", lower.tail = FALSE),
        sec.axis = sec_axis(transform = ~ 1 / ., name = "Return Period")
      ) +
      theme_linedraw()

主轴是「正态上尾概率」的 probit 变换（`lower.tail = FALSE` 即 `-qnorm(p)`），次轴是
它的倒数（重现期）。两条轴各自独立变换。
"""

from ggcore.plot import aes, geom_point, ggplot, labs, scale_x_continuous, sec_axis
from ggcore.scales import transform_probability
from ggcore.theme import theme_linedraw
from ggio.frame import to_column_table

DATA = {
    "Value": [0.18, 0.29, 0.35, 0.46, 0.50, 0.50, 0.51],
    "Probability": [0.045, 0.090, 0.136, 0.181, 0.227, 0.272, 0.318],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="Probability", y="Value"))
        + geom_point()
        + scale_x_continuous(
            transform=transform_probability("norm", lower_tail=False),
            **{"sec.axis": sec_axis(lambda v: 1.0 / v, name="Return Period")},
        )
        + theme_linedraw()
        + labs(title="sec_axis, independent transformations")
    )
    return {"plot": p, "size": [10, 8]}

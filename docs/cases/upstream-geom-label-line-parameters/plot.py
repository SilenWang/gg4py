"""上游快照复刻：geom_label with line parameters（geom-label/geom-label-with-line-parameters.svg）。

源：`test-geom-label.R` 的 "geom_label handles line parameters and colours"
（vdiffr 名 `geom_label with line parameters`）。

R：

    df <- data.frame(x = 1:3, labels = c("foo", "bar", "baz"))
    ggplot(df, aes(x, label = labels, colour = labels, linewidth = x)) +
      geom_label(aes(y = 1), border.colour = "black", linetype = 1) +
      geom_label(aes(y = 2), text.colour = "black", linetype = 2) +
      scale_linewidth(range = c(0.1, 1))

第一层：黑边框 + 实线，文字/底色走 colour；第二层：虚线边框（颜色仍走 colour），
文字是黑色。
"""

from ggcore.plot import aes, geom_label, ggplot, labs, scale_linewidth
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DAT = {"x": [1.0, 2.0, 3.0], "labels": ["foo", "bar", "baz"]}


def build():
    p = (
        ggplot(
            to_column_table(DAT),
            aes(x="x", label="labels", colour="labels", linewidth="x"),
        )
        + geom_label(aes(y=1), border_colour="black", linetype=1)
        + geom_label(aes(y=2), text_colour="black", linetype=2)
        + scale_linewidth(range=(0.1, 1))
        + theme_test()
        + labs(title="geom_label with line parameters")
    )
    return {"plot": p, "size": [10, 8]}

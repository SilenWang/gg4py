"""上游快照复刻：parsed facet labels。

源：facet-labels/parsed-facet-labels.svg
（vdiffr 名 "parsed facet labels"）。

R：

    df <- data_frame(x = 1, y = 1, f = "alpha ^ beta")
    ggplot(df, aes(x, y)) +
      labs(x = NULL, y = NULL) +
      facet_wrap(~ f, labeller = label_parsed)

strip 里的标签是 plotmath 表达式 `alpha ^ beta`：底数 `α` 用 8.8pt、上标 `β` 用
6.16pt（0.7 倍）并抬 0.502em，两段各落一次字（见 `ggcore/plotmath.py`）。

主题按快照反推：白底 + `#333333` 面板边框 = `theme_test()`（同文件的
`outside-justified labels` 是 `theme_grey()` 的灰底，两者不是同一个全局主题）。
"""

from ggcore.plot import aes, facet_wrap, geom_point, ggplot, label_parsed, labs
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1.0], "y": [1.0], "f": ["alpha ^ beta"]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + facet_wrap("f", labeller=label_parsed)
        + theme_test()
        + labs(x=None, y=None, title="parsed facet labels")
    )
    return {"plot": p, "size": [10, 8]}

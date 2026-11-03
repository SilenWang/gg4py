"""upstream/theme-bw：`geom_point()` + `facet_wrap(~a)` + `theme_bw()`。

复刻上游 `tests/testthat/test-theme.R` 的 "themes don't change without
acknowledgement" 用例；expected.svg 就是上游 `_snaps/theme/theme-bw.svg`。
"""

from ggcore.plot import aes, facet_wrap, geom_point, ggplot, labs
from ggcore.theme import theme_bw
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 2, 3], "z": ["a", "b", "a"], "a": [1, 1, 1]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="z"))
        + geom_point()
        + facet_wrap("a")
        + theme_bw()
        # vdiffr 把 doppelganger 的名字写成标题；上游快照里有这一行。
        + labs(title="theme_bw")
    )
    return {"plot": p, "size": [10, 8]}

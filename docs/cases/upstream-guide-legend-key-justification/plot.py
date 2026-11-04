"""上游快照复刻：`legend key justification`。

源：`guide-legend/legend-key-justification.svg`

R：

    p <- ggplot(mtcars, aes(mpg, disp, colour = factor(cyl), size = drat)) +
      geom_point() +
      scale_size_continuous(range = c(0, 20), breaks = c(3, 4, 5), limits = c(2.5, 5)) +
      scale_colour_discrete(labels = c("one line", "up\nto\nfour\nlines",
                                       "up\nto\nfive\nwhole\nlines")) +
      theme(legend.key.justification = c(1, 0))
    expect_doppelganger("legend key justification", p)

两条图例的**逐键**尺寸不同：`size` 图例的键高 = `(size + linewidth) / 10` cm，而
`size` 走 `pal_area()`（面积 → 直径，`sqrt`），所以三行分别是 0.894 / 1.549 / 2.0 cm，
不再等高；`colour` 图例的行高由多行标签撑开。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _fixtures import mtcars

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_legend,
    guides,
    labs,
    scale_colour_discrete,
    scale_size_continuous,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {
    "mpg": mtcars["mpg"],
    "disp": mtcars["disp"],
    "cyl": [str(value) for value in mtcars["cyl"]],
    "drat": mtcars["drat"],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="mpg", y="disp", colour="cyl", size="drat"))
        + geom_point()
        + scale_size_continuous(range=(0.0, 20.0), breaks=(3.0, 4.0, 5.0), limits=(2.5, 5.0))
        + scale_colour_discrete(
            labels=("one line", "up\nto\nfour\nlines", "up\nto\nfive\nwhole\nlines")
        )
        # R 没写 `order` 时按 `order_<rlang::hash>` 排（drat 在前）；这里显式钉住
        # 同一个顺序，不让哈希决定快照顺序。
        + guides(size=guide_legend(order=1), colour=guide_legend(order=2))
        # vdiffr 把 doppelganger 名写进 `plot.title`。
        + labs(title="legend key justification", colour="factor(cyl)")
        + theme(**{"legend.key.justification": (1.0, 0.0)})
    )
    return {"plot": p, "size": [10, 8]}

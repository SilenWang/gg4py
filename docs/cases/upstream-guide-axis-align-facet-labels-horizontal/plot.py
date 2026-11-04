"""上游快照复刻：align facet labels, facets horizontal。

源：`guide-axis/align-facet-labels-facets-horizontal.svg`
（vdiffr 名 "align facet labels, facets horizontal"）。

R：

    ggplot(mpg, aes(hwy, reorder(model, hwy))) +
      geom_point() +
      facet_grid(manufacturer ~ ., scales = "free", space = "free") +
      theme_test() +
      theme(strip.text.y = element_text(angle = 0))

`mpg` 的 manufacturer / model / hwy 三列与 `levels(reorder(model, hwy))` 的 38 个
水平在 `tools/upstream/fixtures/mpg_models.json`（R 4.5.3 逐值导出）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _fixtures import factor_column, mpg_model_levels, mpg_models, replace_column

from ggcore.plot import aes, facet_grid, geom_point, ggplot, labs
from ggcore.theme import element_text, theme, theme_test
from ggio.frame import to_column_table

DATA = mpg_models
TABLE = replace_column(
    to_column_table(DATA), "model", factor_column(DATA["model"], mpg_model_levels)
)


def build():
    p = (
        ggplot(TABLE, aes(x="hwy", y="model"))
        + geom_point()
        + facet_grid(rows="manufacturer", scales="free", space="free")
        + theme_test()
        + theme(**{"strip.text.y": element_text(angle=0)})
        + labs(title="align facet labels, facets horizontal", y="reorder(model, hwy)")
    )
    return {"plot": p, "size": [10, 8]}

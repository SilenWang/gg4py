"""Scratch: guide-axis/align-facet-labels-facets-vertical."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "docs" / "cases"))

from _fixtures import factor_column, mpg_model_levels, mpg_models, replace_column

from ggcore.plot import aes, facet_grid, geom_point, ggplot, labs
from ggcore.theme import element_text, theme, theme_test
from ggio.frame import to_column_table

SNAPSHOT = "guide-axis/align-facet-labels-facets-vertical.svg"

DATA = mpg_models
TABLE = replace_column(
    to_column_table(DATA), "model", factor_column(DATA["model"], mpg_model_levels)
)


def build():
    p = (
        ggplot(TABLE, aes(x="model", y="hwy"))
        + geom_point()
        + facet_grid(cols="manufacturer", scales="free", space="free")
        + theme_test()
        + theme(**{"axis.text.x": element_text(angle=90, hjust=1, vjust=0.5)})
        + labs(title="align facet labels, facets vertical", x="reorder(model, hwy)")
    )
    return {"plot": p, "size": [10, 8]}

"""Scratch: guide-axis/guides-specified-in-guides."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _fixtures import mpg

from ggcore.plot import aes, geom_point, ggplot, guide_axis, guides, labs
from ggcore.theme import theme_test
from ggio.frame import to_column_table


def build():
    p = (
        ggplot(to_column_table(mpg), aes(x="class", y="hwy"))
        + geom_point()
        + guides(
            x=guide_axis(n_dodge=2),
            y=guide_axis(n_dodge=2),
            **{"x.sec": guide_axis(n_dodge=2), "y.sec": guide_axis(n_dodge=2)},
        )
        + theme_test()
        + labs(title="guides specified in guides()")
    )
    return {"plot": p, "size": [10, 8]}

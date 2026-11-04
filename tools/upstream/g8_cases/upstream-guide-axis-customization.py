"""Scratch: guide-axis/guide-axis-customization."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _fixtures import mpg

from ggcore.plot import (
    aes,
    dup_axis,
    geom_point,
    ggplot,
    guide_axis,
    labs,
    scale_x_discrete,
    scale_y_continuous,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table


def build():
    p = (
        ggplot(to_column_table(mpg), aes(x="class", y="hwy"))
        + geom_point()
        + scale_y_continuous(
            guide=guide_axis(n_dodge=2),
            **{"sec.axis": dup_axis(guide=guide_axis(n_dodge=2))},
        )
        + scale_x_discrete(guide=guide_axis(n_dodge=2))
        + theme_test()
        + labs(title="guide_axis() customization")
    )
    return {"plot": p, "size": [10, 8]}

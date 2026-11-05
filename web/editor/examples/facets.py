"""示例 5 / 9 · 分面：一张图按列切成小面板，各面板共享同一条标度。"""

from ggcore.plot import aes, facet_wrap, geom_point, geom_smooth, ggplot, labs, theme_minimal
from ggio.frame import to_column_table

needs = ["numpy"]

GROUPS = ["north", "south", "east"]
DATA = {
    "x": list(range(1, 11)) * 3,
    "y": [
        (0.9 * x + 1.0) if i == 0 else (0.4 * x + 3.0) if i == 1 else (1.4 * x - 1.0)
        for i in range(3)
        for x in range(1, 11)
    ],
    "region": [GROUP for GROUP in GROUPS for _ in range(10)],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point(size=1.6, colour="#4a5568", alpha=0.7)
        + geom_smooth(method="lm", colour="#2b6cb0")
        + facet_wrap(("region",))
        + labs(title="Facets", subtitle="facet_wrap(('region',))", x="x", y="y")
        + theme_minimal()
    )
    return {"plot": p, "size": [5.0, 3.5]}

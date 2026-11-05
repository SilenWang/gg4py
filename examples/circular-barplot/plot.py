"""示例：分组环形柱状图（`geom_col` + `coord_polar()`）。

对应参考图 <https://r-graph-gallery.com/297-circular-barplot-with-groups.html>。
做法完全在本体内：柱子排在一条连续的 x 上，组与组之间留一格空位，再整体卷成极坐标。
数值是固定种子生成的合成数据。

    pixi run examples:circular-barplot    # 重画本目录下的 circular-barplot.png / .svg
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ggcore.plot import aes, coord_polar, geom_col, ggplot, labs
from ggcore.theme import theme, theme_void
from ggio.frame import from_dict

SLUG = "circular-barplot"
SIZE_IN = (7.6, 6.2)

GROUPS = ["Alpha", "Bravo", "Charlie", "Delta"]
PER_GROUP = 6
#: 组与组之间让出的空位数（单位是「一根柱子 + 它的间距」）。
GAP = 1.0


def data():
    """4 组 × 6 根柱子；x 是连续位置，组间留空位当分组间隔。"""
    rng = np.random.default_rng(7)
    position: list[float] = []
    value: list[float] = []
    group: list[str] = []
    x = 1.0
    for name in GROUPS:
        for _ in range(PER_GROUP):
            position.append(x)
            value.append(float(rng.integers(20, 100)))
            group.append(name)
            x += 1.0
        x += GAP
    return from_dict({"position": position, "value": value, "group": group})


def plot() -> ggplot:
    return (
        ggplot(data(), aes(x="position", y="value", fill="group"))
        + geom_col(width=0.82)
        + coord_polar()
        + labs(title="Values around the circle", subtitle="four groups, gaps widened")
        + theme_void()
        # 图例放右边：`theme_void()` + 底部图例在版式里不预留高度（见 docs/examples.md
        # 「已知缺口」），会把面板压出页面。
        + theme(**{"legend.position": "right"})
    )


def main() -> None:
    from ggskia import ggsave  # 出图要 skia 后端，它按 X1 的约定住在 ggcore 之外

    here = Path(__file__).resolve().parent
    width, height = SIZE_IN
    p = plot()
    result = ggsave(p, here / f"{SLUG}.png", width=width, height=height, dpi=150)
    ggsave(p, here / f"{SLUG}.svg", width=width, height=height)
    print(f"{result.path.name}: {result.size_px[0]}×{result.size_px[1]} px, {result.bytes} bytes")


if __name__ == "__main__":
    main()

"""示例：排名变化图（bump chart，`geom_line` + `geom_point` + 反转的 y 轴）。

对应参考图 <https://r-graph-gallery.com/409-customize-bump-plot.html>。上游示例用
`ggbump` 包画弯头连线；这里只用本体能力：排名当 y、`scale_y_reverse()` 把第 1 名
放到顶部、`colour` 区分对象。数据是手写的排名表，不需要外部数据。

    pixi run examples:bump-chart      # 重画本目录下的 bump-chart.png / bump-chart.svg
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ggcore.plot import (
    aes,
    geom_line,
    geom_point,
    ggplot,
    labs,
    scale_x_continuous,
    scale_y_reverse,
)
from ggio.frame import from_dict

SLUG = "bump-chart"
SIZE_IN = (8.0, 4.8)

YEARS = [2019, 2020, 2021, 2022, 2023, 2024]
RUNTIMES = ["Python", "Rust", "Go", "TypeScript", "Julia", "Zig"]

#: 每一行是一个年份，按 `RUNTIMES` 的顺序给出该年的名次（1 = 第一）。
RANKS = [
    [1, 2, 3, 4, 5, 6],
    [1, 2, 3, 5, 4, 6],
    [1, 3, 2, 5, 4, 6],
    [2, 3, 1, 4, 5, 6],
    [2, 1, 3, 5, 4, 6],
    [2, 1, 4, 3, 5, 6],
]


def data():
    year: list[int] = []
    runtime: list[str] = []
    rank: list[float] = []
    for yi, name in enumerate(YEARS):
        for runtime_name, place in zip(RUNTIMES, RANKS[yi], strict=True):
            year.append(name)
            runtime.append(runtime_name)
            rank.append(float(place))
    return from_dict({"year": year, "runtime": runtime, "rank": rank})


def plot() -> ggplot:
    return (
        ggplot(data(), aes(x="year", y="rank", colour="runtime"))
        + geom_line(linewidth=1.1)
        + geom_point(size=3.2)
        + scale_x_continuous(breaks=YEARS)
        + scale_y_reverse(breaks=[1, 2, 3, 4, 5, 6])
        + labs(
            title="Ranking over time",
            subtitle="synthetic ranks, six runtimes",
            x=None,
            y="Rank",
            colour=None,
        )
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

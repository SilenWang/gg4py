"""示例：镜像密度图（`geom_density` + `after_stat()` 取负）。

对应参考图 <https://r-graph-gallery.com/density_mirror_ggplot2.html>。两组分布共用
一条 y = 0 的基线，一组画在基线上方（`after_stat("density")`），另一组把同一列
密度取负后画在下方（`after_stat("-density")`）。数据是固定种子生成的两段正态样本。

    pixi run examples:mirrored-density    # 重画本目录下的 mirrored-density.png / .svg
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from gg4py import aes, after_stat, annotate, from_dict, geom_density, ggplot, labs

SLUG = "mirrored-density"
SIZE_IN = (8.0, 4.8)

UPPER = "#3B7EA1"
LOWER = "#E08A2B"


def data():
    """两段固定种子的正态样本：`2024` 在上、`2010` 在下（口径对称）。"""
    rng = np.random.default_rng(11)
    return (
        from_dict({"value": rng.normal(0.0, 1.0, 400)}),
        from_dict({"value": rng.normal(1.2, 0.7, 400)}),
    )


def plot() -> ggplot:
    recent, earlier = data()
    return (
        ggplot(recent, aes(x="value", y=after_stat("density")))
        + geom_density(fill=UPPER, colour=UPPER, alpha=0.9, linewidth=0.4)
        + geom_density(
            data=earlier,
            mapping=aes(x="value", y=after_stat("-density")),
            fill=LOWER,
            colour=LOWER,
            alpha=0.9,
            linewidth=0.4,
        )
        # 系列名写在填充色块内部（白字），不额外占图例的位置。
        + annotate("text", x=-0.15, y=0.30, label="2024", colour="white", size=4.5)
        + annotate("text", x=1.2, y=-0.34, label="2010", colour="white", size=4.5)
        + labs(
            title="Two distributions, one baseline",
            subtitle="density mirrored around y = 0",
            x="daily mean (°C)",
            y="Density",
        )
    )


def main() -> None:
    from gg4py import ggsave  # 顶层入口惰性加载 skia 后端（X1 约束不变）

    here = Path(__file__).resolve().parent
    width, height = SIZE_IN
    p = plot()
    result = ggsave(p, here / f"{SLUG}.png", width=width, height=height, dpi=150)
    ggsave(p, here / f"{SLUG}.svg", width=width, height=height)
    print(f"{result.path.name}: {result.size_px[0]}×{result.size_px[1]} px, {result.bytes} bytes")


if __name__ == "__main__":
    main()

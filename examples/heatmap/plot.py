"""示例：月度平均气温热图（`geom_tile` + viridis 渐变）。

对应参考图 <https://r-graph-gallery.com/215-the-heatmap-function.html>。数据是
**合成的**一条正弦季节曲线 + 逐年缓慢升温 + 固定种子噪声，不下载任何外部数据，
所以同一台机器上重跑得到逐字节相同的 PNG / SVG。

    pixi run examples:heatmap      # 重画本目录下的 heatmap.png / heatmap.svg
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ggcore.plot import (
    aes,
    geom_tile,
    ggplot,
    labs,
    scale_fill_viridis_c,
)
from ggio.frame import from_dict

SLUG = "heatmap"
SIZE_IN = (8.0, 4.8)

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
YEARS = [str(year) for year in range(2018, 2026)]


def data():
    """12 个月 × 8 年：正弦季节曲线 + 每年 +0.45 °C + 固定种子噪声。"""
    rng = np.random.default_rng(2026)
    month: list[str] = []
    year: list[str] = []
    temp: list[float] = []
    for yi, label in enumerate(YEARS):
        for mi, name in enumerate(MONTHS):
            seasonal = 11.5 + 9.5 * np.sin(2.0 * np.pi * (mi - 3.5) / 12.0)
            month.append(name)
            year.append(label)
            temp.append(round(float(seasonal + 0.45 * yi + rng.normal(0.0, 0.55)), 3))
    return from_dict({"month": month, "year": year, "temp": temp})


def plot() -> ggplot:
    return (
        ggplot(data(), aes(x="month", y="year", fill="temp"))
        + geom_tile(colour="white", linewidth=0.6)
        + scale_fill_viridis_c(name="°C")
        + labs(
            title="Monthly mean temperature",
            subtitle="synthetic station data, 2018–2025",
            x=None,
            y=None,
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

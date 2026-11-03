#!/usr/bin/env python
"""M1 出口复现件：2×2 分面 + colour 图例 + 标题 / 轴标题的报告图（PNG + SVG）。

只用公开 API（`ggplot` / `facet_wrap` / `labs` / `theme_grey` / `ggio.frame`
的列式适配 / `ggsave`），数据自造且确定性，不读仓库外的东西：同样的图能在任何
检出的分支上逐次复跑，用来人眼对拍 R 侧（`scripts/exit_report.R` 是同一份数据、
同一段绘图代码，出图走 svglite）。

    pixi run python scripts/exit_report.py

产物默认落 `dist/exit-report/`（不入库）：

    report.png   4×3 in，150 dpi
    report.svg   同一张图的矢量版（细线 / 图例盒的几何直接在这里量）

**不是** `cases:matrix` 的 case：这里没有 expected.svg、没有容差、不进 CI 门禁，
它只是出口验收时「拿同一张图跟 R 并排看」的那张图。
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ggcore.plot import aes, facet_wrap, geom_line, geom_point, ggplot, labs, theme_grey  # noqa: E402
from ggio.frame import to_column_table  # noqa: E402
from ggskia import ggsave  # noqa: E402

#: 分面与系列（2×2 面板，每面板两条线、各 15 个点）——与 `scripts/exit_report.R`
#: 逐字一致，两边都不读外部文件。
FACETS = ("Alpha", "Beta", "Gamma", "Delta")
SERIES = ("control", "treated")
POINTS = 15

DEFAULT_OUT_DIR = REPO / "dist" / "exit-report"
DEFAULT_WIDTH_IN = 4.0
DEFAULT_HEIGHT_IN = 3.0
DEFAULT_DPI = 150


def report_data() -> dict[str, list]:
    """确定性的报告数据（纯函数：两次调用逐值相等）。"""
    data: dict[str, list] = {"facet": [], "series": [], "x": [], "y": []}
    for fi, facet in enumerate(FACETS):
        for si, series in enumerate(SERIES):
            phase = fi * 0.9 + si * 1.3
            for i in range(1, POINTS + 1):
                x = float(i * 2)
                y = 3.0 + 0.05 * x + 0.9 * math.sin(x / 4.0 + phase) + 0.15 * ((i + fi + si) % 3)
                data["facet"].append(facet)
                data["series"].append(series)
                data["x"].append(x)
                data["y"].append(y)
    return data


def report_plot() -> ggplot:
    """报告图本身（同一份代码在 R 侧是 `ggplot(df, aes(...)) + ...`）。"""
    return (
        ggplot(
            to_column_table(report_data()),
            aes(x="x", y="y", colour="series", group="series"),
        )
        + geom_line(linewidth=0.6)
        + geom_point(size=1.6)
        + facet_wrap("facet", ncol=2)
        + labs(
            title="M1 report: seasonal response by site",
            x="Elapsed time (days)",
            y="Response (arb. units)",
            colour="Series",
        )
        + theme_grey()
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="exit_report", description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="产物目录（默认 dist/exit-report，不入库）",
    )
    parser.add_argument("--width", type=float, default=DEFAULT_WIDTH_IN, help="页面宽，英寸")
    parser.add_argument("--height", type=float, default=DEFAULT_HEIGHT_IN, help="页面高，英寸")
    parser.add_argument("--dpi", type=float, default=DEFAULT_DPI, help="PNG 的 dpi")
    args = parser.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    plot = report_plot()
    for suffix, dpi in (("png", args.dpi), ("svg", 72.0)):
        path = args.out_dir / f"report.{suffix}"
        result = ggsave(plot, path, width=args.width, height=args.height, dpi=dpi)
        print(
            f"{result.path}: {result.bytes} bytes, "
            f"{result.width_pt:g}×{result.height_pt:g} pt"
            f"{f', {result.size_px[0]}×{result.size_px[1]} px' if result.size_px else ''}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

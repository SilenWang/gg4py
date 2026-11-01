"""`pixi run diff` —— 参考图 × 实测图的像素差分（M0-9）。

一条链只有一个实现：

    expected.svg ──resvg──┐
                          ├─ PNG ─→ 像素 diff ─→ 报告 + 热图 + 退出码
    current/*.svg ─resvg──┘

- **统一栅格**：两侧都用 resvg（`pixi` 依赖）光栅化，参考图是 R + svglite 产物、
  实测图是 skia SVG 设备产物，文字与抗锯齿不再各走一套。`--dpi 72` 让 1 pt = 1 px
  （R 的 svglite 写 `288pt`，我们的设备写 `288` 用户单位）。
- **判据**：图级差异（单像素最大通道差 > `--pixel-threshold` 的像素占比）与平均
  差异（全通道平均绝对差 / 255）同时低于阈值才算通过；口径见
  `docs/notes/snapshot-policy.md`。
- **结构化输出**：`--json` 把结论、两个百分比、阈值与热图路径打成 JSON，矩阵与
  下游脚本只认它，不再解析人读文本。

CLI 契约（`tools/cases/matrix.py` 的 `TaskBackend` 依赖）：

    pixi run diff <case-dir> --report <case>/current/diff_report.md [--tolerance 0.02] --json
    退出码 0 = 通过；1 = 超容差；2 = 用法 / IO 错误
"""

from __future__ import annotations

from ggdiff.compare import DiffResult, compare_images, load_image
from ggdiff.raster import RasterError, rasterize_svg
from ggdiff.report import render_report

__all__ = [
    "DiffResult",
    "RasterError",
    "compare_images",
    "load_image",
    "rasterize_svg",
    "render_report",
]

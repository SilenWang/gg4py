"""人读报告：`diff_report.md`（逐图指标 + 判定 + 热图指向）。

报告是每次运行的产物，不入库（`docs/cases/*/current/` 已在 `.gitignore`）；
需要留档时把报告与热图一起贴进 PR / issue。CI 的 step summary 直接贴这份
markdown，不再从 stdout 末尾截三行——「差多少」正是要稳定的那部分。
"""

from __future__ import annotations

import os
from pathlib import Path

from ggdiff.compare import DiffResult

__all__ = ["render_report"]


def _display(path: Path) -> str:
    """尽量给相对路径（报告要贴进 PR，绝对路径没法点））。"""
    try:
        return os.path.relpath(path, Path.cwd())
    except ValueError:  # pragma: no cover - 跨盘符才会发生（Windows）
        return str(path)


def _verdict_text(result: DiffResult) -> str:
    return "**通过**" if result.ok else "**失败**"


def render_report(
    result: DiffResult,
    *,
    title: str,
    reference: Path,
    actual: Path,
    rasterized: str,
    heatmap: Path | None,
    resvg: str = "",
) -> str:
    """生成 markdown 报告。`rasterized` 描述两侧各自怎么落到 PNG 的。"""
    thresholds = result.thresholds
    lines = [
        f"# 差分报告：{title}",
        "",
        f"- 判定：{_verdict_text(result)}" + (f"（{result.reason}）" if result.reason else ""),
        f"- 图级差异：**{result.image_diff_fraction:.4%}**"
        f"（阈值 {thresholds['image_diff_fraction']:.2%}，"
        f"单像素阈值 {int(thresholds['pixel_threshold'])}/255）",
        f"- 平均差异：**{result.mean_diff:.4%}**（阈值 {thresholds['mean_diff']:.2%}）",
        f"- 差异像素：{result.diff_pixels} / {result.total_pixels}"
        f"（{result.width}×{result.height}）",
        f"- 最大通道差：{result.max_channel_diff}/255",
        "",
        "| 项 | 路径 |",
        "| --- | --- |",
        f"| 参考 | `{_display(reference)}` |",
        f"| 实测 | `{_display(actual)}` |",
    ]
    if heatmap is not None:
        lines.append(f"| 热图 | `{_display(heatmap)}` |")
    lines.extend(
        [
            "",
            "## 栅格",
            "",
            f"- {rasterized}",
        ]
    )
    if resvg:
        lines.append(f"- 光栅器：`{resvg}`")
    lines.extend(
        [
            "",
            "口径见 `docs/notes/snapshot-policy.md`：图级差异与平均差异**同时**低于阈值"
            "才算通过；只调容差不算修好。",
            "",
        ]
    )
    return "\n".join(lines)

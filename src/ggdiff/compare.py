"""像素差分：图级差异百分比 + 平均差异。

两个指标共同判绿（`docs/notes/snapshot-policy.md`）：

- **图级差异** `image_diff_fraction`：单像素最大通道绝对差 **> pixel_threshold**
  的像素占全部像素的比例。阈值默认 4/255（X4 的抗锯齿舍入口径）。
- **平均差异** `mean_diff`：`mean(|a - b|) / 255`，所有像素、所有通道一起平均。
  它抓「大面积轻微偏色」——图级差异抓不到，但人眼看得出来。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ggdiff.image import load_image

__all__ = ["DiffResult", "compare_images", "load_image"]

#: 图级差异的默认上限：2%（issue 的验收阈值）。
DEFAULT_MAX_FRACTION = 0.02
#: 平均差异的默认上限：1%。
DEFAULT_MAX_MEAN = 0.01
#: 单像素算「不一样」的最大通道差（0..255）：X4 的 4/255。
DEFAULT_PIXEL_THRESHOLD = 4


@dataclass(frozen=True, slots=True)
class DiffResult:
    """一次比较的全部结论；`--json` 就是它的字段（外加路径）。"""

    verdict: str
    image_diff_fraction: float
    mean_diff: float
    diff_pixels: int
    total_pixels: int
    width: int
    height: int
    max_channel_diff: int
    thresholds: dict[str, float]
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.verdict == "pass"

    def as_dict(self) -> dict[str, object]:
        return {
            "verdict": self.verdict,
            "ok": self.ok,
            "image_diff_fraction": self.image_diff_fraction,
            "mean_diff": self.mean_diff,
            "diff_pixels": self.diff_pixels,
            "total_pixels": self.total_pixels,
            "width": self.width,
            "height": self.height,
            "max_channel_diff": self.max_channel_diff,
            "thresholds": dict(self.thresholds),
            "reason": self.reason,
        }


def _fail(
    reference: np.ndarray,
    reason: str,
    thresholds: dict[str, float],
    *,
    image_diff_fraction: float = 1.0,
    mean_diff: float = 1.0,
) -> DiffResult:
    height, width = reference.shape[:2]
    return DiffResult(
        verdict="fail",
        image_diff_fraction=image_diff_fraction,
        mean_diff=mean_diff,
        diff_pixels=width * height,
        total_pixels=width * height,
        width=width,
        height=height,
        max_channel_diff=255,
        thresholds=thresholds,
        reason=reason,
    )


def compare_images(
    reference: np.ndarray,
    actual: np.ndarray,
    *,
    max_fraction: float = DEFAULT_MAX_FRACTION,
    max_mean: float = DEFAULT_MAX_MEAN,
    pixel_threshold: int = DEFAULT_PIXEL_THRESHOLD,
) -> tuple[DiffResult, np.ndarray, np.ndarray]:
    """比较两张 `(H, W, 3)` uint8 RGB 图。

    返回（结论, 差异掩码 `(H, W)` bool, 每像素最大通道差 `(H, W)` uint8）。
    尺寸不一致直接判红：参考图与实测图必须是同一个页面尺寸，缩放比对会把
    「画错位置」变成「看着差不多」。
    """
    thresholds = {
        "image_diff_fraction": float(max_fraction),
        "mean_diff": float(max_mean),
        "pixel_threshold": float(pixel_threshold),
    }
    if reference.shape != actual.shape:
        return (
            _fail(
                reference,
                f"尺寸不一致：参考 {reference.shape[1]}×{reference.shape[0]}，"
                f"实测 {actual.shape[1]}×{actual.shape[0]}",
                thresholds,
            ),
            np.ones(reference.shape[:2], dtype=bool),
            np.full(reference.shape[:2], 255, dtype=np.uint8),
        )

    difference = np.abs(reference.astype(np.int16) - actual.astype(np.int16)).astype(np.uint8)
    per_pixel = difference.max(axis=2)
    mask = per_pixel > int(pixel_threshold)
    height, width = mask.shape
    total = int(height * width)
    diff_pixels = int(mask.sum())
    fraction = diff_pixels / total if total else 0.0
    mean = float(difference.astype(np.float32).mean() / 255.0) if total else 0.0

    reasons: list[str] = []
    if fraction > max_fraction:
        reasons.append(f"图级差异 {fraction:.4%} > 阈值 {max_fraction:.2%}")
    if mean > max_mean:
        reasons.append(f"平均差异 {mean:.4%} > 阈值 {max_mean:.2%}")
    verdict = "fail" if reasons else "pass"
    return (
        DiffResult(
            verdict=verdict,
            image_diff_fraction=fraction,
            mean_diff=mean,
            diff_pixels=diff_pixels,
            total_pixels=total,
            width=int(width),
            height=int(height),
            max_channel_diff=int(per_pixel.max()) if total else 0,
            thresholds=thresholds,
            reason="；".join(reasons),
        ),
        mask,
        per_pixel,
    )

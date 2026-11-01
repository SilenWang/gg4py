"""位图读写：PNG → numpy RGB，差异热图 → PNG。

只依赖 Pillow（`pixi.toml` 的 `[pypi-dependencies]`）与 numpy；不引入绘图库。
RGB 是唯一口径：两张图都先 `convert("RGB")`，alpha 由 resvg / 设备的白底消解。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

__all__ = ["load_image", "save_heatmap", "save_png"]


def load_image(path: str | Path) -> np.ndarray:
    """读一张 PNG 成 `(H, W, 3)` 的 uint8 RGB。"""
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"), dtype=np.uint8).copy()


def save_png(path: str | Path, array: np.ndarray) -> Path:
    """把 `(H, W, 3)` uint8 写成 PNG（目录不存在就建）。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.ascontiguousarray(array, dtype=np.uint8), mode="RGB").save(
        target, format="PNG", optimize=False
    )
    return target


def save_heatmap(
    path: str | Path,
    reference: np.ndarray,
    mask: np.ndarray,
    *,
    amount: np.ndarray | None = None,
) -> Path:
    """差异热图：参考图灰化成底，差异像素按差值强度着红。

    `mask` 是 `(H, W)` 布尔（差异像素），`amount` 是每个像素的最大通道差
    （0..255）；不给时按 `mask` 二值着色。底图压到 25% 灰，红色叠到 80% 以上，
    这样一眼能看出「差在哪个位置」。
    """
    base = reference.astype(np.float32)
    grey = base.mean(axis=2, keepdims=True)
    canvas = (255.0 - (255.0 - grey) * 0.25).repeat(3, axis=2)
    if mask.any():
        if amount is None:
            strength = np.ones(mask.shape, dtype=np.float32)
        else:
            strength = np.clip(amount.astype(np.float32) / 255.0, 0.0, 1.0)
        # 红 = (255, 0, 0)，按差值强度混合到 55%..100%，弱差异也看得见。
        alpha = np.where(mask, 0.55 + 0.45 * strength, 0.0)[..., None]
        red = np.zeros_like(canvas)
        red[..., 0] = 255.0
        canvas = canvas * (1.0 - alpha) + red * alpha
    return save_png(path, np.clip(canvas, 0, 255).astype(np.uint8))

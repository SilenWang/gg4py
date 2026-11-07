"""把 `image-rendering="pixelated"` 的位图按设备像素铺好，再交给 resvg。

**为什么需要这一步**（SIL-867）：参考产线 svglite 对 `interpolate = FALSE` 的
raster 先把位图**最近邻放大到设备像素**再嵌进 SVG（每格点向上取整到整像素，
同 `ggskia.skia._cell_aligned` 的口径），所以参考图里的 `<image>` 位图尺寸与
目标矩形基本 1:1，后面谁光栅化都不再重采样。查看器按 SVG 语义写的是原图 +
`image-rendering="pixelated"`——Chromium 会做最近邻，图画得对。

但 resvg 0.47 **不认** `image-rendering`（实测：同一份 viewer SVG 加不加这个属性，
像素结果逐字节相同），一张 2×3 的棋盘格被平滑插值成一团灰：`geom-raster` 族
图级差异 42%–51%。这是光栅器的表达能力缺口，不是查看器画错，所以补在这一层，
和 `inline_text_paths`（resvg 取不出 CJK 字形轮廓）同一个位置。

口径（与 svglite 一致）：

    w_px = ceil(ceil(宽度 pt) / 列数) × 列数

`ceil` 一次都不能省：3×2 的 raster 铺进 586.448 × 474.884 pt 时 svglite 给的是
588×477（587→294×2 / 475→159×3），不是 586×477。**幂等**：位图已经是格点对齐
的尺寸（参考图、skia 设备腿都是）时原样返回，不重编码、不动字节。

位图按整块复制放大（`Image.NEAREST`）：格点对齐保证目标尺寸是格数的整数倍，
所以最近邻在这里没有「怎么取整」的自由度，R、Pillow、Chromium 得到同一张图。
"""

from __future__ import annotations

import base64
import io
import math
import re
from pathlib import Path

__all__ = ["SvgImageError", "cell_aligned_pixels", "snap_pixelated_images"]

_IMAGE = re.compile(r"<(?:[\w.-]+:)?image\b[^>]*>", re.S)
_DATA_URL = re.compile(r"(data:image/(?P<mime>[A-Za-z0-9.+-]+);base64,)(?P<data>[A-Za-z0-9+/=\s]+)")
_ATTR = re.compile(r"\b(?P<name>[\w:-]+)\s*=\s*(?P<quote>['\"])(?P<value>.*?)(?P=quote)", re.S)
_PIXELATED = re.compile(r"image-rendering\s*[:=]\s*['\"]?\s*pixelated", re.I)
_MATRIX = re.compile(r"matrix\(\s*([-+0-9.eE\s,]+)\)")
_SCALE = re.compile(r"scale\(\s*([-+0-9.eE]+)(?:[\s,]+([-+0-9.eE]+))?\s*\)")


class SvgImageError(RuntimeError):
    """SVG 无法解析或位图无法解码。"""


def cell_aligned_pixels(cells: int, target_pt: float) -> int:
    """`cells` 个格点铺满 `target_pt` 时 svglite 用的像素数（每格向上取整）。"""
    cells = max(1, int(cells))
    target = max(1, math.ceil(float(target_pt)))
    return -(-target // cells) * cells


def _attributes(tag: str) -> dict[str, str]:
    return {match.group("name"): match.group("value") for match in _ATTR.finditer(tag)}


def _scale_of(transform: str | None) -> float:
    """`transform` 的等比缩放（√|det|）；它决定「目标矩形」在设备上占几个像素。"""
    if not transform:
        return 1.0
    match = _MATRIX.search(transform)
    if match is not None:
        values = [float(item) for item in re.split(r"[\s,]+", match.group(1).strip()) if item]
        if len(values) == 6:
            a, b, c, d = values[:4]
            return math.sqrt(abs(a * d - b * c)) or 1.0
    match = _SCALE.search(transform)
    if match is not None:
        sx = float(match.group(1))
        sy = float(match.group(2)) if match.group(2) else sx
        return math.sqrt(abs(sx * sy)) or 1.0
    return 1.0


def _number(value: str | None) -> float | None:
    if value is None:
        return None
    match = re.match(r"\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)", value)
    return float(match.group(1)) if match else None


def _snap_tag(tag: str) -> tuple[str, bool]:
    """返回（改写后的 `<image>` 标签, 是否重编码了位图）。"""
    attributes = _attributes(tag)
    if not _PIXELATED.search(tag):
        return tag, False
    width = _number(attributes.get("width"))
    height = _number(attributes.get("height"))
    if width is None or height is None or width <= 0 or height <= 0:
        return tag, False
    scale = _scale_of(attributes.get("transform"))
    # 同一张位图在 `href` / `xlink:href` 里各写了一遍，两处都要换。
    matches = list(_DATA_URL.finditer(tag))
    if not matches:
        return tag, False
    payload = matches[0].group("data")
    try:
        raw = base64.b64decode(re.sub(r"\s+", "", payload), validate=True)
    except (ValueError, TypeError):
        return tag, False
    try:
        from PIL import Image

        with Image.open(io.BytesIO(raw)) as image:
            cells_x, cells_y = image.size
            target_x = cell_aligned_pixels(cells_x, width * scale)
            target_y = cell_aligned_pixels(cells_y, height * scale)
            if (target_x, target_y) == (cells_x, cells_y):
                return tag, False
            scaled = image.convert("RGBA").resize((target_x, target_y), Image.NEAREST)
    except Exception as error:  # PIL 的异常类型随格式而变，统一折成一种
        raise SvgImageError(f"位图解码失败：{error}") from error

    buffer = io.BytesIO()
    scaled.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    snapped = _DATA_URL.sub(lambda m: f"data:image/png;base64,{encoded}", tag)
    return snapped, True


def snap_pixelated_images(source: Path, target: Path | None = None) -> int:
    """把 `source` 里 pixelated 的位图按格点放大；返回重编码的图片数。

    `target` 缺省时**就地**改写 `source`（没有需要放大的图就一个字节都不动）。
    两侧都已经是格点对齐的尺寸时返回 0，文件原样保留。
    """
    payload = source.read_text(encoding="utf-8")
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        tag, changed = _snap_tag(match.group(0))
        count += int(changed)
        return tag

    updated = _IMAGE.sub(replace, payload)
    if target is None:
        if count:
            source.write_text(updated, encoding="utf-8")
    else:
        target.write_text(updated if count else payload, encoding="utf-8")
    return count

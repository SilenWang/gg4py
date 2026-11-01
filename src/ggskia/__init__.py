"""skia-python 设备（M0-8）：桌面 / 服务端的 PNG / SVG / PDF 三路出图。

`ggcore.device.Device` 是纯 Python 的协议（X1 门禁：`ggcore` 里不出现 skia /
harfbuzz）；这个包是它的实现，和 `ggshape` 之于度量后端是同一个分层。

```python
from ggskia import device_for

data = device_for("out.pdf", *scene.size).render(scene)   # 页面尺寸 pt，显式
```

口径见 `docs/notes/device.md`：文字在矢量后端一律是轮廓、`pch` 与曲线求值在
设备侧、CLI 是 `pixi run render --scene … --out …`。
"""

from __future__ import annotations

from pathlib import Path

from ggcore.device import FORMATS, Device, DeviceError, DeviceWarning
from ggskia.skia import SkiaPdfDevice, SkiaRasterDevice, SkiaSvgDevice

__all__ = [
    "Device",
    "DeviceError",
    "DeviceWarning",
    "SkiaPdfDevice",
    "SkiaRasterDevice",
    "SkiaSvgDevice",
    "device_for",
]


def device_for(kind: str | Path, width_pt: float, height_pt: float, dpi: float = 72.0) -> Device:
    """按格式名或文件后缀造设备（`.png` / `.svg` / `.pdf`）。"""
    name = str(kind).lower()
    if "." in name:
        name = Path(name).suffix.lstrip(".")
    if name in ("png", "raster"):
        return SkiaRasterDevice(width_pt, height_pt, dpi=dpi)
    if name == "svg":
        return SkiaSvgDevice(width_pt, height_pt, dpi=dpi)
    if name == "pdf":
        return SkiaPdfDevice(width_pt, height_pt, dpi=dpi)
    raise DeviceError(f"不认识的输出格式 {kind!r}（可选：{' / '.join(sorted(FORMATS))}）")

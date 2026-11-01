"""`ggcore.device.Device`：一页纸 + 一个 `ir.Scene` → 字节（M0-8）。

接口只有四个动作，顺序固定：

    device = SkiaRasterDevice(432, 324, dpi=150)   # 页面尺寸与 DPI 都是显式参数
    device.open()                                   # 建画布
    device.draw_scene(scene)                        # 画一份 IR（只认 ir.Scene）
    data = device.close()                           # 出字节，释放后端对象

`render(scene)` 是这三步的简写。单位统一是 **pt**（页面尺寸、坐标、线宽、
字号都是 pt）；`dpi` 只决定栅格化的像素换算，不改变几何
（`docs/notes/ir.md` §1）。

设备只吃 `ggcore.ir.Scene`：`ggcore.grobs.Scene` 的 float64 几何是遍历期的
中间形态，不进设备（`docs/notes/grobs.md` §7.2）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from ggcore.ir import Scene

__all__ = ["FORMATS", "Device", "DeviceError", "DeviceWarning"]

#: 输出格式 → 文件后缀（CLI 与测试共用）。
FORMATS = {"png": ".png", "svg": ".svg", "pdf": ".pdf"}


class DeviceError(RuntimeError):
    """设备用法或输入不合规（页面尺寸不符、格式不支持、后端失败）。"""


class DeviceWarning(UserWarning):
    """画得出来但按 R 的口径只能警告的事（例如没有定义的 `pch`）。"""


class Device(ABC):
    """一页纸的设备抽象。一次 `open` → 一次（或多次）`draw_scene` → 一次 `close`。"""

    format: ClassVar[str] = ""

    def __init__(self, width_pt: float, height_pt: float, dpi: float = 72.0) -> None:
        self.width_pt = float(width_pt)
        self.height_pt = float(height_pt)
        self.dpi = float(dpi)
        if self.width_pt <= 0 or self.height_pt <= 0:
            raise DeviceError(f"页面尺寸必须为正，收到 {self.width_pt}×{self.height_pt} pt")
        if self.dpi <= 0:
            raise DeviceError(f"dpi 必须为正，收到 {self.dpi}")
        self._state = "new"

    @property
    def size_pt(self) -> tuple[float, float]:
        return (self.width_pt, self.height_pt)

    @property
    def size_px(self) -> tuple[int, int]:
        """栅格化的像素尺寸（矢量后端只是给调用方参考）。"""
        return (
            round(self.width_pt / 72.0 * self.dpi),
            round(self.height_pt / 72.0 * self.dpi),
        )

    def open(self) -> None:
        if self._state != "new":
            raise DeviceError(f"{type(self).__name__} 已经 open 过（state={self._state}）")
        try:
            self._begin()
        except BaseException:
            self._abort()
            self._state = "aborted"
            raise
        self._state = "open"

    def draw_scene(self, scene: Scene) -> None:
        if self._state != "open":
            raise DeviceError(f"draw_scene 前要先 open()（state={self._state}）")
        if not isinstance(scene, Scene):
            raise DeviceError(f"设备只吃 ir.Scene，收到 {type(scene).__name__}")
        if tuple(scene.size) != self.size_pt:
            raise DeviceError(
                f"页面尺寸不符：设备 {self.size_pt} pt，场景 {tuple(scene.size)} pt"
                "（页面尺寸是显式参数，设备不替场景改纸）"
            )
        try:
            self._draw_scene(scene)
        except BaseException:
            # 画到一半失败（坏 blob、后端报错）也要把后端对象按安全顺序释放：
            # skia 的 PDF 文档晚于它的 stream 析构会段错误，所以不能只靠 GC。
            self._abort()
            self._state = "aborted"
            raise

    def close(self) -> bytes:
        if self._state != "open":
            raise DeviceError(f"close 前要先 open()（state={self._state}）")
        data = self._finish()
        self._state = "closed"
        return data

    def render(self, scene: Scene) -> bytes:
        """`open` + `draw_scene` + `close` 的简写。"""
        self.open()
        self.draw_scene(scene)
        return self.close()

    @abstractmethod
    def _begin(self) -> None: ...

    @abstractmethod
    def _draw_scene(self, scene: Scene) -> None: ...

    @abstractmethod
    def _finish(self) -> bytes: ...

    def _abort(self) -> None:
        """`open` / `draw_scene` 失败后的收尾钩子（缺省什么都不用做）。"""
        return None

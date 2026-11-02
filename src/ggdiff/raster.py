"""统一栅格：SVG → PNG 只走 resvg。

参考图（R + svglite）与实测图（skia 的 SVG 设备）结构不同：一边是 `<text>` +
`<circle>`，一边是字形轮廓 + 路径。像素 diff 之前必须落到同一张位图上，所以两侧
都由 **resvg** 光栅化——字体、抗锯齿、坐标舍入只剩一套实现。

几个口径：

- `--dpi 72`：1 pt = 1 px。svglite 写 `width='288.00pt'`，我们的 SVG 写
  `width='288'`（用户单位 = pt），两者在 72 dpi 下都是 288 px。
- 字体：`--skip-system-fonts` + `--use-fonts-dir <CONDA_PREFIX>/fonts`，只用 pixi
  受管的字体（`font-ttf-noto-cjk` 等）。不这样的话，同一份 SVG 在开发机与 CI
  会因为系统字体不同而画出不同的字。
- 找不到 resvg 时直接报错，不静默退化成别的光栅器：那会让「统一栅格」名存实亡。

需要换光栅器（例如 CI 装了别的版本）时用环境变量 `GGDIFF_RESVG` 指定路径，
`GGDIFF_FONTS` 指定字体目录。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

__all__ = ["RasterError", "rasterize_svg", "resvg_path", "resvg_version"]

DEFAULT_DPI = 72


class RasterError(RuntimeError):
    """光栅化失败（缺 resvg、SVG 坏、resvg 非 0 退出）。"""


def resvg_path() -> str:
    override = os.environ.get("GGDIFF_RESVG")
    if override:
        return override
    found = shutil.which("resvg")
    if found:
        return found
    prefix = os.environ.get("CONDA_PREFIX")
    if prefix:
        candidate = Path(prefix) / "bin" / "resvg"
        if candidate.is_file():
            return str(candidate)
    raise RasterError(
        "找不到 resvg：`pixi run diff` 需要在 pixi 环境里跑（resvg 在 pixi.toml 里声明），"
        "或用 GGDIFF_RESVG 指定路径"
    )


def fonts_dir() -> Path | None:
    override = os.environ.get("GGDIFF_FONTS")
    if override:
        return Path(override)
    prefix = os.environ.get("CONDA_PREFIX")
    if prefix:
        candidate = Path(prefix) / "fonts"
        if candidate.is_dir():
            return candidate
    return None


def resvg_version() -> str:
    """`resvg -V` 的第一行；报告里记一笔，便于判断差异是否换了光栅器。"""
    result = subprocess.run(
        [resvg_path(), "--version"], capture_output=True, text=True, check=False
    )
    return (
        (result.stdout or result.stderr).strip().splitlines()[0]
        if result.returncode == 0
        else "unknown"
    )


def rasterize_svg(
    svg: str | Path,
    out: str | Path,
    *,
    dpi: int = DEFAULT_DPI,
    background: str | None = None,
    zoom: float | None = None,
) -> Path:
    """把一张 SVG 光栅化成 PNG，返回输出路径。

    `dpi` 只作用于带单位的尺寸（`pt`）；skia 的 SVG 设备写 `width="288"` 这种
    无单位用户单位，`--dpi` 对它是无效的。这类输入要用 `zoom` 显式放大
    （同一张图 2× 对拍就是 `dpi=144` 对应 viewer、`zoom=2` 对应桌面设备）。
    """
    source = Path(svg)
    target = Path(out)
    target.parent.mkdir(parents=True, exist_ok=True)
    command = [resvg_path(), "--dpi", str(int(dpi))]
    fonts = fonts_dir()
    if fonts is not None:
        command.extend(["--skip-system-fonts", "--use-fonts-dir", str(fonts)])
    if background is not None:
        command.extend(["--background", background])
    if zoom is not None:
        command.extend(["--zoom", f"{float(zoom):g}"])
    command.extend([str(source), str(target)])
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not target.is_file():
        detail = (result.stderr or result.stdout or "").strip() or f"退出码 {result.returncode}"
        raise RasterError(f"resvg 无法光栅化 {source}：{detail}")
    return target

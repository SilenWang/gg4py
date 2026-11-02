"""Playwright 在 pixi 环境里要的两条环境变量（测试与截图脚本共用）。

1. `PLAYWRIGHT_BROWSERS_PATH`：`$HOME` 只读，浏览器装在仓库的
   `.playwright-browsers/`（`pixi run viewer:browsers`）；
2. `LD_LIBRARY_PATH` / `FONTCONFIG_FILE`：Chromium 要 libglib、libnss 与一份
   fontconfig 配置。pixi 环境里有这些库，但没有 `/etc/fonts/fonts.conf` 时
   Chromium 的字体管理器会直接 abort（`SkFontMgr_FontConfigInterface`）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

__all__ = ["REPO", "VIEWER", "configure"]

VIEWER = REPO / "web" / "viewer"


def configure() -> None:
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(REPO / ".playwright-browsers"))
    prefix = Path(sys.prefix)
    lib_dir = prefix / "lib"
    if lib_dir.is_dir():
        current = os.environ.get("LD_LIBRARY_PATH", "")
        os.environ["LD_LIBRARY_PATH"] = f"{lib_dir}:{current}" if current else str(lib_dir)
    fonts = prefix / "etc" / "fonts"
    if (fonts / "fonts.conf").is_file():
        os.environ.setdefault("FONTCONFIG_FILE", str(fonts / "fonts.conf"))
        os.environ.setdefault("FONTCONFIG_PATH", str(fonts))

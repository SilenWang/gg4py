"""受管字体定位（M0-7）。

字体文件只有一份来源：pixi 装进环境的 conda-forge 字体包。桌面、服务端、CI
三处读的是同一批字节，**不经过宿主 fontconfig**——`docs/spike/e3_export` 实测
容器里 fontconfig 配置缺失时 skia 的 `SkFont` 文本 API 会段错误，而按文件路径
直接建 face 不会。

定位顺序（第一个命中的生效）：

1. 显式传入的 `root`（测试与嵌入方用）；
2. 环境变量 `GG_FONT_DIR`（Pyodide / 自定义部署把字体放进虚拟 FS 时用）；
3. `$CONDA_PREFIX/fonts`（pixi 环境的标准位置）。

`FONT_FAMILIES` 同时给出文件名 → 字族名的映射：浏览器端（CanvasKit
`TypefaceFontProvider.registerFont`）与 TS SVG 序列化的 `font-family` 用的就是
这里的名字，不要在别处另写一份。
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from ggcore.metrics.faces import (
    FAMILY_FACES,
    FontFaceError,
    ResolvedFace,
    available_styles,
    canonical_family,
    resolve_face,
)
from ggcore.metrics.rules import DEFAULT_FONT_STACK, FONT_FAMILIES

__all__ = [
    "DEFAULT_FONT_STACK",
    "MANAGED_FONTS",
    "FontCatalog",
    "FontFaceError",
    "FontNotFound",
    "ManagedFont",
    "ResolvedFace",
    "default_font_dir",
]


@dataclass(frozen=True)
class ManagedFont:
    """仓库受管的一个字体文件。"""

    filename: str
    family: str


# 登记在 src/ggcore/metrics/data/rules.json 的受管字体。文件来自 pixi 的
# font-ttf-dejavu / font-ttf-noto / font-ttf-noto-cjk / font-ttf-noto-emoji。
MANAGED_FONTS: dict[str, ManagedFont] = {
    filename: ManagedFont(filename, family) for filename, family in FONT_FAMILIES.items()
}


class FontNotFound(LookupError):
    """字体目录或字体文件缺失。"""


def default_font_dir() -> Path:
    """按 `GG_FONT_DIR` → `$CONDA_PREFIX/fonts` 的顺序定位字体目录。"""
    override = os.environ.get("GG_FONT_DIR")
    if override:
        return Path(override)
    prefix = os.environ.get("CONDA_PREFIX")
    if prefix:
        return Path(prefix) / "fonts"
    raise FontNotFound(
        "no managed font directory: set GG_FONT_DIR or run through `pixi run`, "
        "which sets CONDA_PREFIX (docs/notes/metrics-ledger.md · M0-7)"
    )


class FontCatalog:
    """受管字体的统一入口：路径、字族名、字节、sha256。"""

    def __init__(self, root: str | os.PathLike[str] | None = None) -> None:
        self.root = Path(root) if root is not None else default_font_dir()
        if not self.root.is_dir():
            raise FontNotFound(f"font directory does not exist: {self.root}")
        self._sha256: dict[str, str] = {}

    def path(self, filename: str) -> Path:
        path = self.root / filename
        if not path.is_file():
            raise FontNotFound(f"managed font missing: {path}")
        return path

    def exists(self, filename: str) -> bool:
        return (self.root / filename).is_file()

    def read(self, filename: str) -> bytes:
        return self.path(filename).read_bytes()

    def family(self, filename: str) -> str:
        managed = MANAGED_FONTS.get(filename)
        if managed is not None:
            return managed.family
        # 字面文件（-Bold / -Italic …）在 faces.py 里登记，rules.json 只收了一部分
        # 常用文件名；两条声明都查一遍，避免 catalog.family() 返回文件主干名。
        for faces in FAMILY_FACES.values():
            for face in faces:
                if face.filename == filename:
                    return face.family
        # 未登记的文件按主干名兜底，保证两端至少拿到同一个名字。
        return Path(filename).stem

    # --- 字面解析（M1 文字测量） -----------------------------------------

    def resolve(
        self,
        family: str,
        weight: int = 400,
        italic: bool = False,
        *,
        strict: bool = True,
    ) -> ResolvedFace:
        """字族 + 字重 + 斜体 → 受管字面；文件不在目录里直接报错。"""
        resolved = resolve_face(family, weight, italic, strict=strict)
        if not self.exists(resolved.filename):
            raise FontNotFound(
                f"managed font missing for {resolved.family} "
                f"({resolved.style}): {self.root / resolved.filename}"
            )
        return resolved

    def styles(self, family: str) -> tuple[str, ...]:
        """该字族可用的字面名；未登记的字族返回空元组。"""
        return available_styles(family)

    def is_managed_family(self, family: str) -> bool:
        return canonical_family(family) is not None

    def sha256(self, filename: str) -> str:
        if filename not in self._sha256:
            self._sha256[filename] = hashlib.sha256(self.read(filename)).hexdigest()
        return self._sha256[filename]

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"FontCatalog(root={str(self.root)!r})"

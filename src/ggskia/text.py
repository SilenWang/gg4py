"""设备侧文字：字形选择（HarfBuzz）+ 排版（skia）+ 轮廓（PDF/SVG 用）。

IR 的 `text` 只带一个已解析的字体 key、字号、锚点和一个**最终宽度**
（`docs/notes/ir.md` §7）。设备不用那个宽度去排版——它自己排——那个宽度是
对齐与差分统计的口径。

三层，各管一件事：

1. **字体解析**：key → 受管字体栈。`sans`（grob 的缺省 key）解析成
   `NotoSansCJKsc-VF.ttf`（同时覆盖拉丁与中日韩，M0-8 的 CJK 验收靠它）；
   登记过的字族名解析成自己的文件，未知字族回落到 `sans`。
2. **run 切分**：沿用 M0-7 的 `ggcore.metrics.runs.split_runs()`——两端用的是
   同一份规则（`docs/spike/e2_metrics/report.md` 的 132/200 条就是没切 run
   造成的），每一个码点选字体栈里第一个 cmap 覆盖它的字面。一格里混排
   「中文 A」时，中文与拉丁各走各的字面。
3. **排版**：字形 id 按书写系统分两路——简单文字走 skia 的
   `Font.textToGlyphs()`（cmap 直映，与 `drawString()` 同一个映射），需要
   上下文 shaping 的文字才交给 HarfBuzz（连字、上下文替换、重排都在那一步
   发生，见 `docs/notes/device.md` §4 与 `is_supported()`）。两条路的笔位统一
   来自 skia 的 `Font.getXPos()`，也就是 `drawString()` 自己用的那套 hinted
   推进——**栅格设备于是能逐像素复现旧基线**，三个后端也落在同一组位置上。

`shortcut:` 推进用 skia 的 hinted `getXPos()`（整 pt 量化，长标签累计误差
< 1pt）；要线性度量（PDF 大字号更准）时换 `setLinearMetrics(True)` 并同步重录
`docs/cases/grob-*/baseline`。

矢量后端要的是**轮廓**：`Font.getPath(gid)` 返回的字形路径已经是 y 向下，
直接按笔位平移就能画，PDF 里不会出现 `/Font`，SVG 里不会出现 `<text>`
（`docs/notes/device.md` §3）。
"""

from __future__ import annotations

from dataclasses import dataclass

import skia
import uharfbuzz as hb

from ggcore.metrics.catalog import MANAGED_FONTS, FontCatalog
from ggcore.metrics.rules import DEFAULT_FONT_STACK
from ggcore.metrics.runs import is_supported, split_runs

__all__ = ["GlyphRun", "TextShaper", "resolve_stack"]

SANS = "NotoSansCJKsc-VF.ttf"


def resolve_stack(key: str) -> tuple[str, ...]:
    """IR 的字体 key → 受管字体栈（第一个是主字面）。"""
    family = key.split(":", 1)[0].strip()
    if family in ("", "sans"):
        return (SANS, *DEFAULT_FONT_STACK)
    for managed in MANAGED_FONTS.values():
        if managed.family.lower() == family.lower():
            return (managed.filename, SANS, *DEFAULT_FONT_STACK)
    # 未登记的字族不猜：回落到能覆盖 CJK 的缺省字面（粗体/斜体后缀同样忽略）。
    return (SANS, *DEFAULT_FONT_STACK)


@dataclass(frozen=True)
class GlyphRun:
    """一段同字面的已排好版的字形。"""

    filename: str
    gids: tuple[int, ...]
    offsets: tuple[float, ...]
    advance: float


class TextShaper:
    """字体目录 + HarfBuzz + skia 字体缓存的合成体。"""

    def __init__(self, catalog: FontCatalog | None = None) -> None:
        self.catalog = catalog if catalog is not None else FontCatalog()
        self._faces: dict[str, hb.Face] = {}
        self._hb_fonts: dict[str, hb.Font] = {}
        self._typefaces: dict[str, skia.Typeface] = {}
        self._skia_fonts: dict[tuple[str, float], skia.Font] = {}
        self._coverage: dict[tuple[str, int], bool] = {}
        self._shaped: dict[tuple[str, str, float], tuple[tuple[int, ...], float]] = {}

    def typeface(self, filename: str) -> skia.Typeface:
        cached = self._typefaces.get(filename)
        if cached is None:
            cached = skia.Typeface.MakeFromFile(str(self.catalog.path(filename)))
            if cached is None:  # pragma: no cover - 字体文件损坏才会发生
                raise RuntimeError(f"cannot load managed font {filename}")
            self._typefaces[filename] = cached
        return cached

    def font(self, filename: str, size_pt: float) -> skia.Font:
        key = (filename, round(float(size_pt), 4))
        cached = self._skia_fonts.get(key)
        if cached is None:
            cached = skia.Font(self.typeface(filename), max(float(size_pt), 0.1))
            self._skia_fonts[key] = cached
        return cached

    def _hb_font(self, filename: str) -> hb.Font:
        font = self._hb_fonts.get(filename)
        if font is None:
            face = self._faces.get(filename)
            if face is None:
                face = hb.Face(self.catalog.read(filename))
                self._faces[filename] = face
            font = hb.Font(face)
            # 设计单位：advance 与 shape 结果和度量端同口径（`ggshape.harfbuzz`）。
            font.scale = (face.upem, face.upem)
            self._hb_fonts[filename] = font
        return font

    def covers(self, filename: str, codepoint: int) -> bool:
        key = (filename, codepoint)
        covered = self._coverage.get(key)
        if covered is None:
            gid = self._hb_font(filename).get_nominal_glyph(codepoint)
            covered = gid is not None and gid != 0
            self._coverage[key] = covered
        return covered

    def _shape_one(self, filename: str, text: str, size_pt: float) -> tuple[tuple[int, ...], float]:
        """单字面 shaping：字形 id + 推进，单位 pt（skia 的 hinted 口径）。"""
        key = (filename, text, round(float(size_pt), 4))
        cached = self._shaped.get(key)
        if cached is not None:
            return cached
        skia_font = self.font(filename, size_pt)
        if is_supported(text):
            # 简单文字（拉丁/希腊/西里尔/CJK/emoji）：cmap 直映。与 skia 的
            # `drawString()`、M0-7 的兜底表同一口径——可变字体里 HarfBuzz 会给
            # 数字挑不同的字形实例（Noto CJK 的 '0' 是 63153 vs 17），两端会
            # 画出不同的数字，所以简单文字不绕 HB。
            gids = tuple(int(gid) for gid in skia_font.textToGlyphs(text))
        else:
            # 需要上下文 shaping 的书写系统（阿拉伯/印度诸语/泰文……）走 HarfBuzz：
            # 连写、重排、合字都在这一步发生，逐码点 cmap 映射画不出来。
            font = self._hb_font(filename)
            buffer = hb.Buffer()
            buffer.add_str(text)
            buffer.guess_segment_properties()
            hb.shape(font, buffer)
            gids = tuple(info.codepoint for info in buffer.glyph_infos)
        shaped = (gids, float(skia_font.measureText(text)))
        self._shaped[key] = shaped
        return shaped

    def runs(self, key: str, text: str, size_pt: float) -> tuple[GlyphRun, ...]:
        """把一段文字按字面切成 run，并逐个排版。"""
        stack = resolve_stack(key)
        pieces = split_runs(
            text, lambda index, codepoint: self.covers(stack[index], codepoint), len(stack)
        )
        out: list[GlyphRun] = []
        for piece in pieces:
            filename = stack[piece.font_index]
            gids, advance = self._shape_one(filename, piece.text, float(size_pt))
            if not gids:
                continue
            offsets = tuple(float(value) for value in self.font(filename, size_pt).getXPos(gids))
            out.append(GlyphRun(filename, gids, offsets, advance))
        return tuple(out)

"""HarfBuzz 后端：`ggcore.metrics.MetricsBackend` 的参考实现。

字面量来自 `FontCatalog`（受管字体文件，不经 fontconfig）。shaping 与浏览器端
CanvasKit 走的是同一个引擎（HarfBuzz 15.0.0），这也是 E2 双端差异能压到 0.241%
的原因；两端差异的门禁是 `pixi run gate:metrics`。
"""

from __future__ import annotations

from collections.abc import Sequence

import uharfbuzz as hb

from ggcore.metrics.catalog import DEFAULT_FONT_STACK, FontCatalog
from ggcore.metrics.provider import FontMetrics, MetricProvider, ShapedRun

__all__ = ["HarfBuzzBackend", "harfbuzz_provider"]

# emoji 合字探针：ZWJ 家庭序列 / 国旗 / keycap。三者都必须是单字形。
EMOJI_LIGATURE_PROBES = (
    "\U0001f468\u200d\U0001f469\u200d\U0001f467\u200d\U0001f466",
    "\U0001f1e8\U0001f1f3",
    "1\ufe0f\u20e3",
)


class HarfBuzzBackend:
    """逐字体缓存 `hb.Face`/`hb.Font`，scale 设成 upem（advance 直接用设计单位）。"""

    name = "harfbuzz"

    def __init__(self, catalog: FontCatalog | None = None) -> None:
        self.catalog = catalog if catalog is not None else FontCatalog()
        self._faces: dict[str, hb.Face] = {}
        self._fonts: dict[str, hb.Font] = {}
        self._coverage: dict[tuple[str, int], bool] = {}

    # --- MetricsBackend ---------------------------------------------------

    def font_metrics(self, filename: str) -> FontMetrics:
        face = self._face(filename)
        font = self._font(filename)
        extents = font.get_font_extents("ltr")
        return FontMetrics(
            upem=face.upem,
            ascent=int(extents.ascender),
            # HarfBuzz 的 descender 是负数，provider 的口径是「向下的正距离」。
            descent=int(-extents.descender),
        )

    def covers(self, filename: str, codepoint: int) -> bool:
        key = (filename, codepoint)
        covered = self._coverage.get(key)
        if covered is None:
            gid = self._font(filename).get_nominal_glyph(codepoint)
            covered = gid is not None and gid != 0
            self._coverage[key] = covered
        return covered

    def shape(self, filename: str, text: str) -> ShapedRun:
        font = self._font(filename)
        buffer = hb.Buffer()
        buffer.add_str(text)
        buffer.guess_segment_properties()
        hb.shape(font, buffer)
        return ShapedRun(
            gids=tuple(info.codepoint for info in buffer.glyph_infos),
            advances=tuple(float(pos.x_advance) for pos in buffer.glyph_positions),
        )

    def supports(self, text: str) -> bool:
        # HarfBuzz 会做完整的上下文 shaping（连写/重排/合字），没有能力盲区。
        return True

    # --- 额外能力 ---------------------------------------------------------

    def coverage(self, filename: str) -> tuple[list[int], list[int]]:
        """枚举 cmap 覆盖的码点及其 advance（字体设计单位），升序。"""
        font = self._font(filename)
        codepoints: list[int] = []
        advances: list[int] = []
        for cp in range(0x110000):
            if 0xD800 <= cp <= 0xDFFF:  # 代理区不可能是合法字符
                continue
            gid = font.get_nominal_glyph(cp)
            if gid:
                codepoints.append(cp)
                advances.append(int(font.get_glyph_h_advance(gid)))
        return codepoints, advances

    def ligates_emoji_clusters(self, filename: str) -> bool:
        """该字族是否把 emoji 序列（ZWJ / 国旗 / keycap）合成一个字形。

        探针要**同时**满足「单字形」，避免把「没有 emoji 覆盖、每个码点各一个
        `.notdef`」的字族误判成会合字。
        """
        for probe in EMOJI_LIGATURE_PROBES:
            if len(self.shape(filename, probe).gids) != 1:
                return False
        return True

    def glyph_advances(self, filename: str, gids: Sequence[int]) -> tuple[float, ...]:
        """按字形 id 取 advance（字体设计单位）——门禁的 skia 腿用它做逐字形对拍。"""
        font = self._font(filename)
        return tuple(float(font.get_glyph_h_advance(gid)) for gid in gids)

    def notdef_advance(self, filename: str) -> int:
        return int(self._font(filename).get_glyph_h_advance(0))

    # --- 内部 -------------------------------------------------------------

    def _face(self, filename: str) -> hb.Face:
        face = self._faces.get(filename)
        if face is None:
            face = hb.Face(self.catalog.read(filename))
            self._faces[filename] = face
        return face

    def _font(self, filename: str) -> hb.Font:
        font = self._fonts.get(filename)
        if font is None:
            face = self._face(filename)
            font = hb.Font(face)
            font.scale = (face.upem, face.upem)
            self._fonts[filename] = font
        return font


def harfbuzz_provider(
    catalog: FontCatalog | None = None,
    font_stack: Sequence[str] = DEFAULT_FONT_STACK,
    cache_size: int = 4096,
) -> MetricProvider:
    """CPython 侧的标准 provider：HarfBuzz 后端 + 受管字体。"""
    resolved = catalog if catalog is not None else FontCatalog()
    return MetricProvider(
        HarfBuzzBackend(resolved),
        catalog=resolved,
        font_stack=font_stack,
        cache_size=cache_size,
    )

"""设备侧文字：字面解析（FontCatalog）+ 排版（skia）+ 轮廓（PDF/SVG 用）。

IR 的 `text` 只带一个已解析的字体 key、字号、锚点和一个**最终宽度**
（`docs/notes/ir.md` §7）。设备不用那个宽度去排版——它自己排——那个宽度是
对齐与差分统计的口径。

四层，各管一件事：

1. **字面解析**：key 的 `family:face` 后缀（`bold` / `italic` / `bold-italic`）
   经 `ggcore.metrics.faces` 解析成受管字体文件；可变字体（Noto Sans 系列、
   Noto CJK）用 `wght` 轴落到 400/700。缺字面直接报错并列可用字面，不静默
   回落常规。三个后端共用这一条路径。
2. **run 切分**：沿用 M0-7 的 `ggcore.metrics.runs.split_runs()`——每个码点选
   字体栈里第一个 cmap 覆盖它的字面。emoji 例外：矢量后端把彩色 CBDT 字面换成
   单色 Noto Emoji 轮廓（`emoji="outline"`），栅格后端保留彩色位图。
3. **排版**：字形 id 按书写系统分两路——简单文字走 skia 的
   `Font.textToGlyphs()`（cmap 直映，与 `drawString()` 同一个映射），需要
   上下文 shaping 的文字才交给 HarfBuzz。两条路的笔位统一来自 skia 的
   `Font.getXPos()`；字体对象开**线性度量**（`setLinearMetrics(True)`），
   与 R 的 cairo/svglite 同口径（hinted 的整 pt 量化最大偏 10.6%，见
   `metrics-ledger.md` · M1-e）。
4. **多行**：`\\n` 切行。R 4.5.3 的 `grid` 实测行距是
   `1.2 × lineheight × fontsize`（默认 lineheight = 1.2 → 1.44 × fontsize），
   整块高度 = `(n-1) × 行距 + strheight`，而 R 的 `strheight` 是
   cap height × 72.27/72（`metrics-ledger.md` · M1-b/M1-d）。

矢量后端要的是**轮廓**：`Font.getPath(gid)` 返回的字形路径已经是 y 向下，
直接按笔位平移就能画，PDF 里不会出现 `/Font`，SVG 里不会出现 `<text>`
（`docs/notes/device.md` §3）。
"""

from __future__ import annotations

from dataclasses import dataclass

import skia
import uharfbuzz as hb

from ggcore.metrics.catalog import FontCatalog
from ggcore.metrics.faces import (
    FACE_SUFFIXES,
    canonical_family,
)
from ggcore.metrics.runs import is_supported, split_runs

__all__ = [
    "EMOJI_COLOR_FAMILY",
    "EMOJI_OUTLINE_FAMILY",
    "LINE_HEIGHT",
    "LINE_PITCH",
    "Face",
    "GlyphRun",
    "ShaperMetrics",
    "TextShaper",
    "parse_font_key",
    "resolve_stack",
]

SANS_FAMILY = "Noto Sans CJK SC"
EMOJI_COLOR_FAMILY = "Noto Color Emoji"
EMOJI_OUTLINE_FAMILY = "Noto Emoji"

#: grid 的 `gpar(lineheight = 1.2)` 缺省值；行距 = LINE_HEIGHT × 1.2 × fontsize。
LINE_HEIGHT = 1.2
#: R 4.5.3 实测的绘制行距系数（`lineheight = 1.2` 时 1.44 × fontsize）。
LINE_PITCH = 1.2 * LINE_HEIGHT


@dataclass(frozen=True, slots=True)
class Face:
    """解析后的一个受管字面（含可变轴取值）。"""

    family: str
    filename: str
    weight: int = 400
    italic: bool = False
    variation: int | None = None

    @property
    def key(self) -> tuple[str, int | None, bool]:
        return (self.filename, self.variation, self.italic)


def parse_font_key(key: str) -> tuple[str, int, bool]:
    """IR 字体 key →（字族名, weight, italic）。

    未登记的后缀按常规字面处理（与 M0 一致）；`sans` / 空串是缺省字族。
    """
    family, _, suffix = key.partition(":")
    family = family.strip()
    weight, italic = FACE_SUFFIXES.get(suffix.strip().lower(), (400, False))
    if not family or family.lower() == "sans":
        family = SANS_FAMILY
    return family, weight, italic


def _emoji_family(family: str, emoji: str) -> str:
    if emoji == "outline" and family == EMOJI_COLOR_FAMILY:
        return EMOJI_OUTLINE_FAMILY
    return family


def resolve_stack(
    key: str,
    *,
    emoji: str = "color",
    catalog: FontCatalog | None = None,
) -> tuple[Face, ...]:
    """IR 的字体 key → 受管字面栈（第一个是主字面）。

    主字族按请求的字重/斜体**严格**解析（缺字面报错）；回退字族（`sans` /
    DejaVu / CJK / emoji）按 best-effort：某档没有 italic 就用常规字面继续找
    覆盖，和 R 的 fontconfig 回退行为一致。
    """
    owner = catalog if catalog is not None else FontCatalog()
    family, weight, italic = parse_font_key(key)
    family = _emoji_family(family, emoji)
    strict = canonical_family(family) is not None
    if not strict and family != SANS_FAMILY:
        # 未登记的字族（R 的 svglite 默认写 "Arimo"、用户随手写的族名）沿用
        # M0 的口径：回落到能覆盖 CJK 的缺省字面，不因为「不在目录里」报错。
        family = SANS_FAMILY
    primary = owner.resolve(family, weight, italic, strict=strict)
    faces: list[Face] = [
        Face(primary.family, primary.filename, primary.weight, primary.italic, primary.variation)
    ]

    # 回退顺序：CJK 主字面之后先给 emoji 字面、再给 DejaVu。DejaVu 自带一些
    # 单色 emoji（U+1F600 / U+2764）且推进只有 1.05×fontsize，放在 emoji 字面
    # 前面会让 emoji 永远落不到 Noto Emoji/Color Emoji（R 的 1.25em 口径）。
    fallbacks: list[tuple[str, int, bool]] = [
        (SANS_FAMILY, weight, italic),
        (EMOJI_COLOR_FAMILY, 400, False),
        ("DejaVu Sans", weight, italic),
    ]
    for name, want_weight, want_italic in fallbacks:
        name = _emoji_family(name, emoji)
        try:
            resolved = owner.resolve(name, want_weight, want_italic, strict=False)
        except (LookupError, ValueError):
            continue
        face = Face(
            resolved.family,
            resolved.filename,
            resolved.weight,
            resolved.italic,
            resolved.variation,
        )
        if face.key not in {item.key for item in faces}:
            faces.append(face)
    return tuple(faces)


@dataclass(frozen=True)
class GlyphRun:
    """一段同字面的已排好版的字形。"""

    face: Face
    text: str
    gids: tuple[int, ...]
    offsets: tuple[float, ...]
    advance: float

    @property
    def filename(self) -> str:
        return self.face.filename


def _variation_args(variation: int) -> tuple[skia.FontArguments, tuple[object, ...]]:
    """`wght` 轴 → FontArguments。返回值第二项是「保活」引用。

    skia-python 的 `setVariationDesignPosition` 只持有 `VariationPosition` 的
    引用，不是拷贝；中间对象被回收后 `makeClone` 会静默退回设计默认字重
    （实测：不保活时 Bold 与 Regular 的推进完全相同）。所以把这些对象一起返回，
    调用方在 `makeClone` 期间保持引用。
    """
    axis = int.from_bytes(b"wght", "big")
    coordinate = skia.FontArguments.VariationPosition.Coordinate(axis, float(variation))
    coordinates = skia.FontArguments.VariationPosition.Coordinates([coordinate])
    position = skia.FontArguments.VariationPosition(coordinates)
    arguments = skia.FontArguments()
    arguments.setVariationDesignPosition(position)
    return arguments, (coordinate, coordinates, position)


class TextShaper:
    """字体目录 + HarfBuzz + skia 字体缓存的合成体。

    `emoji="outline"` 让 SVG/PDF 后端用单色 Noto Emoji 的字形轮廓；`"color"`
    （栅格缺省）保留 Noto Color Emoji 的 CBDT 位图。
    """

    def __init__(self, catalog: FontCatalog | None = None, *, emoji: str = "color") -> None:
        self.catalog = catalog if catalog is not None else FontCatalog()
        if emoji not in ("color", "outline"):
            raise ValueError(f"emoji must be 'color' or 'outline', got {emoji!r}")
        self.emoji = emoji
        self._faces: dict[tuple[str, int | None], hb.Face] = {}
        self._hb_fonts: dict[tuple[str, int | None], hb.Font] = {}
        self._typefaces: dict[tuple[str, int | None], skia.Typeface] = {}
        self._skia_fonts: dict[tuple[str, int | None, float], skia.Font] = {}
        self._coverage: dict[tuple[str, int | None, int], bool] = {}
        self._shaped: dict[tuple[str, int | None, str, float], tuple[tuple[int, ...], float]] = {}
        self._stacks: dict[str, tuple[Face, ...]] = {}

    # --- 字体 -------------------------------------------------------------

    def typeface(self, face: Face) -> skia.Typeface:
        key = (face.filename, face.variation)
        cached = self._typefaces.get(key)
        if cached is None:
            cached = skia.Typeface.MakeFromFile(str(self.catalog.path(face.filename)))
            if cached is None:  # pragma: no cover - 字体文件损坏才会发生
                raise RuntimeError(f"cannot load managed font {face.filename}")
            if face.variation is not None:
                arguments, keepalive = _variation_args(face.variation)
                cached = cached.makeClone(arguments)
                del keepalive  # 克隆完成，Skia 已复制坐标
            if cached is None:  # pragma: no cover - 变体轴不支持才会发生
                raise RuntimeError(f"cannot apply wght={face.variation} to {face.filename}")
            self._typefaces[key] = cached
        return cached

    def font(self, face: Face, size_pt: float) -> skia.Font:
        key = (face.filename, face.variation, round(float(size_pt), 4))
        cached = self._skia_fonts.get(key)
        if cached is None:
            cached = skia.Font(self.typeface(face), max(float(size_pt), 0.1))
            # 线性度量：R 的 cairo/svglite 推进是线性的，而 skia 的缺省 hinted
            # 推进按整 pt 量化。实测 12pt Bold 的 "Bold text sample"：hinted
            # 108.00 vs 线性/HarfBuzz 100.78/100.54 vs R 100.53——hinted 偏宽
            # 7.4%（Bold 每字多进 0.5pt 量级，沿字符串累积）。见
            # docs/notes/metrics-ledger.md · M1-e。
            cached.setLinearMetrics(True)
            self._skia_fonts[key] = cached
        return cached

    def _hb_font(self, face: Face) -> hb.Font:
        key = (face.filename, face.variation)
        font = self._hb_fonts.get(key)
        if font is None:
            face_obj = self._faces.get(key)
            if face_obj is None:
                face_obj = hb.Face(self.catalog.read(face.filename))
                self._faces[key] = face_obj
            font = hb.Font(face_obj)
            # 设计单位：advance 与 shape 结果和度量端同口径（`ggshape.harfbuzz`）。
            font.scale = (face_obj.upem, face_obj.upem)
            if face.variation is not None:
                font.set_variations({"wght": float(face.variation)})
            self._hb_fonts[key] = font
        return font

    def covers(self, face: Face, codepoint: int) -> bool:
        key = (face.filename, face.variation, codepoint)
        covered = self._coverage.get(key)
        if covered is None:
            gid = self._hb_font(face).get_nominal_glyph(codepoint)
            covered = gid is not None and gid != 0
            self._coverage[key] = covered
        return covered

    def harfbuzz_advance(self, face: Face, text: str, size_pt: float) -> float:
        """HarfBuzz 的整段推进（pt）。度量端的口径，用来和 skia 的推进对拍。"""
        font = self._hb_font(face)
        upem = self._faces[(face.filename, face.variation)].upem
        buffer = hb.Buffer()
        buffer.add_str(text)
        buffer.guess_segment_properties()
        hb.shape(font, buffer)
        total = sum(position.x_advance for position in buffer.glyph_positions)
        return total / upem * float(size_pt)

    def stack(self, key: str) -> tuple[Face, ...]:
        cached = self._stacks.get(key)
        if cached is None:
            cached = resolve_stack(key, emoji=self.emoji, catalog=self.catalog)
            self._stacks[key] = cached
        return cached

    def primary_face(self, key: str) -> Face:
        return self.stack(key)[0]

    # --- 排版 -------------------------------------------------------------

    def _shape_one(self, face: Face, text: str, size_pt: float) -> tuple[tuple[int, ...], float]:
        """单字面 shaping：字形 id + 推进，单位 pt（skia 的线性度量口径）。"""
        key = (face.filename, face.variation, text, round(float(size_pt), 4))
        cached = self._shaped.get(key)
        if cached is not None:
            return cached
        skia_font = self.font(face, size_pt)
        if is_supported(text):
            # 简单文字（拉丁/希腊/西里尔/CJK/emoji）：cmap 直映。与 skia 的
            # `drawString()`、M0-7 的兜底表同一口径——可变字体里 HarfBuzz 会给
            # 数字挑不同的字形实例（Noto CJK 的 '0' 是 63153 vs 17），两端会
            # 画出不同的数字，所以简单文字不绕 HB。
            gids = tuple(int(gid) for gid in skia_font.textToGlyphs(text))
        else:
            # 需要上下文 shaping 的书写系统（阿拉伯/印度诸语/泰文……）走 HarfBuzz：
            # 连写、重排、合字都在这一步发生，逐码点 cmap 映射画不出来。
            font = self._hb_font(face)
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
        stack = self.stack(key)
        pieces = split_runs(
            text, lambda index, codepoint: self.covers(stack[index], codepoint), len(stack)
        )
        out: list[GlyphRun] = []
        for piece in pieces:
            face = stack[piece.font_index]
            gids, advance = self._shape_one(face, piece.text, float(size_pt))
            if not gids:
                continue
            offsets = tuple(float(value) for value in self.font(face, size_pt).getXPos(gids))
            out.append(GlyphRun(face, piece.text, gids, offsets, advance))
        return tuple(out)


class ShaperMetrics:
    """`ggcore.units.Metrics` 的实现：宽度问设备自己的排版（英寸）。

    与设备逐字落地用的是同一份 `TextShaper`，所以写进 IR 的 `text.width` 与
    SVG / PNG 里实际占的宽度一致（M0-7 的「宽度来自实际渲染端」口径）。
    多行按 R 的 `stringWidth` 口径取各行的最大推进；`strheight` 按 R 的
    `stringHeight`（`(n-1) × 行距 + cap height`）。
    """

    def __init__(self, shaper: TextShaper | None = None) -> None:
        self.shaper = shaper if shaper is not None else TextShaper()

    def _lines(self, text: str) -> tuple[str, ...]:
        return tuple(text.split("\n"))

    def strwidth(self, text: str, *, fontsize: float, cex: float, font: str = "sans") -> float:
        size = float(fontsize) * float(cex)
        widths = [
            sum(run.advance for run in self.shaper.runs(font, line, size))
            for line in self._lines(text)
        ]
        return (max(widths) if widths else 0.0) / 72.0

    def strheight(self, text: str, *, fontsize: float, cex: float, font: str = "sans") -> float:
        size = float(fontsize) * float(cex)
        face = self.shaper.primary_face(font)
        metrics = self.shaper.font(face, size).getMetrics()
        # R 的 `stringHeight` = cap height（× 72.27/72 的 pt 换算），不是
        # ascent + descent；见 src/ggskia/skia.py 与 metrics-ledger。
        box = float(metrics.fCapHeight)
        if box > 0:
            box *= 72.27 / 72.0
        else:
            box = float(-metrics.fAscent + metrics.fDescent)
        lines = len(self._lines(text))
        pitch = LINE_PITCH * size
        return (box + (lines - 1) * pitch) / 72.0

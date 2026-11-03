"""受管字体的字面目录：`(族, weight, italic)` → 字体文件 + 可变轴取值。

rules.json 只登记「文件 → 字族名」；这里补上同一个字族内的字面（regular /
bold / italic / bold-italic）以及可变字体的 `wght` 轴。两条声明都只来自 pixi
装进环境的受管字体（`font-ttf-dejavu` / `font-ttf-noto` / `font-ttf-noto-cjk` /
`font-ttf-noto-emoji`），不经过 fontconfig。

gpar 的 `font` 只有 1..5（regular / bold / italic / bold-italic / symbol），
所以 weight 只按 400/700 两档取；可变字体用 `wght` 轴落到目标字重，静态字面直接
选文件。**没有对应字面时 `strict=True` 会报错并列出可用字面**，不静默回落常规
（`docs/notes/metrics-ledger.md` · M1 文字测量）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

__all__ = [
    "FACE_SUFFIXES",
    "FAMILY_FACES",
    "FontFace",
    "FontFaceError",
    "ResolvedFace",
    "available_styles",
    "canonical_family",
    "faces_for_family",
    "resolve_face",
    "style_name",
]


class FontFaceError(LookupError):
    """字族里没有请求的字面（或字族未登记）。"""


@dataclass(frozen=True, slots=True)
class FontFace:
    """一个受管字面。`weight_axis` 非空表示可变字重字体（含默认字重）。"""

    family: str
    filename: str
    weight: int = 400
    italic: bool = False
    weight_axis: tuple[int, int] | None = None


@dataclass(frozen=True, slots=True)
class ResolvedFace:
    """解析结果：文件 + 要应用的 `wght` 轴取值（None = 用设计默认值）。"""

    family: str
    filename: str
    weight: int
    italic: bool
    variation: int | None = None

    @property
    def style(self) -> str:
        return style_name(self.weight, self.italic)


def style_name(weight: int, italic: bool) -> str:
    bold = int(weight) >= 700
    if bold and italic:
        return "bold-italic"
    if bold:
        return "bold"
    if italic:
        return "italic"
    return "regular"


#: IR 字体 key 的后缀 → (weight, italic)。5 = symbol：R 的 symbol 字面不是这里
#: 的受管字体，按常规字面处理（M0 的口径，见 docs/notes/device.md §9）。
FACE_SUFFIXES: Mapping[str, tuple[int, bool]] = {
    "": (400, False),
    "regular": (400, False),
    "plain": (400, False),
    "bold": (700, False),
    "italic": (400, True),
    "oblique": (400, True),
    "bold-italic": (700, True),
    "bolditalic": (700, True),
    "bold.italic": (700, True),
    "symbol": (400, False),
}


#: 受管字面。顺序 = 报错时列出的顺序，也是「同字重优先静态字面」的查找顺序。
FAMILY_FACES: Mapping[str, tuple[FontFace, ...]] = {
    # R 参考产线的默认拉丁字面（SIL-715 #6）。svglite 把 `sans` / `""` 解析成
    # fontconfig 的第一个匹配族，在这套受管环境里就是 `Arimo`；conda-forge 只提供
    # 这一份 Arimo 文件（font-ttf-noto 里的 `Arimo-Italic-VF.ttf`，wght 轴只有
    # 400 一个实例、post.italicAngle = -12），所以「常规」和「粗体」都落到它：
    # 请求 700 时没有真粗体，与 R 侧 fontconfig 只能拿到同一条字面的事实一致。
    # 用哪份文件不是偏好问题——`expected.svg` 的 `textLength` 与该文件逐条对上
    # （0.13% 以内），与 Arimo 正体差 0.86%（docs/notes/metrics-ledger.md · M2-a）。
    "Arimo": (
        FontFace("Arimo", "Arimo-Italic-VF.ttf", 400, False),
        FontFace("Arimo", "Arimo-Italic-VF.ttf", 700, False),
        FontFace("Arimo", "Arimo-Italic-VF.ttf", 400, True),
        FontFace("Arimo", "Arimo-Italic-VF.ttf", 700, True),
    ),
    "Noto Sans CJK SC": (
        FontFace("Noto Sans CJK SC", "NotoSansCJKsc-VF.ttf", 400, False, (100, 900)),
    ),
    "Noto Sans": (
        FontFace("Noto Sans", "NotoSans-VF.ttf", 400, False, (100, 900)),
        FontFace("Noto Sans", "NotoSans-Italic-VF.ttf", 400, True, (100, 900)),
    ),
    "DejaVu Sans": (
        FontFace("DejaVu Sans", "DejaVuSans.ttf", 400, False),
        FontFace("DejaVu Sans", "DejaVuSans-Bold.ttf", 700, False),
        FontFace("DejaVu Sans", "DejaVuSans-Oblique.ttf", 400, True),
        FontFace("DejaVu Sans", "DejaVuSans-BoldOblique.ttf", 700, True),
    ),
    "DejaVu Serif": (
        FontFace("DejaVu Serif", "DejaVuSerif.ttf", 400, False),
        FontFace("DejaVu Serif", "DejaVuSerif-Bold.ttf", 700, False),
        FontFace("DejaVu Serif", "DejaVuSerif-Italic.ttf", 400, True),
        FontFace("DejaVu Serif", "DejaVuSerif-BoldItalic.ttf", 700, True),
    ),
    "Noto Serif": (
        FontFace("Noto Serif", "NotoSerif-VF.ttf", 400, False, (100, 900)),
        FontFace("Noto Serif", "NotoSerif-Italic-VF.ttf", 400, True, (100, 900)),
    ),
    # 彩色 emoji 是 CBDT 位图（没有 glyf/CFF），矢量后端不能画；单色 Noto Emoji
    # 是轮廓字体。两者在 device 里按后端选（docs/notes/metrics-ledger.md）。
    "Noto Color Emoji": (FontFace("Noto Color Emoji", "NotoColorEmoji.ttf", 400, False),),
    "Noto Emoji": (FontFace("Noto Emoji", "NotoEmoji-Regular.ttf", 400, False),),
}

#: 字族名按大小写不敏感解析；报错与文档仍用声明里的写法。
_BY_LOWER: Mapping[str, str] = {name.lower(): name for name in FAMILY_FACES}


def canonical_family(family: str) -> str | None:
    """登记过的字族名（保留声明写法）；没登记返回 None。"""
    return _BY_LOWER.get(family.strip().lower())


def faces_for_family(family: str) -> tuple[FontFace, ...]:
    name = canonical_family(family)
    return () if name is None else FAMILY_FACES[name]


def available_styles(family: str) -> tuple[str, ...]:
    """该字族可用的字面名（去重、按声明顺序）。

    可变字重的字面额外列出 `wght` 轴能落到的 bold：CJK 只登记了一个常规文件，
    但 `wght=700` 就是 bold，报错里不能只写「可用字面：regular」。
    """
    out: list[str] = []
    for face in faces_for_family(family):
        names = [style_name(face.weight, face.italic)]
        if face.weight_axis is not None and face.weight_axis[0] <= 700 <= face.weight_axis[1]:
            names.append(f"{style_name(700, face.italic)}（wght=700）")
        for name in names:
            if name not in out:
                out.append(name)
    return tuple(out)


def resolve_face(
    family: str,
    weight: int = 400,
    italic: bool = False,
    *,
    strict: bool = True,
) -> ResolvedFace:
    """在字族里选字面；可变字体返回要应用的 `wght` 值。

    `strict=False` 是回退字族用的：回退链里缺 italic 字面时用常规字面继续找
    覆盖（R 的 fontconfig 回退也不会因为缺斜体就整段放弃）。请求的字族本身
    （`strict=True`）缺字面则报错，并在消息里列出可用字面。
    """
    name = canonical_family(family)
    if name is None:
        raise FontFaceError(
            f"字族 {family!r} 不在受管字体目录里；可用字族：{', '.join(FAMILY_FACES)}"
        )
    weight = int(weight)
    faces = FAMILY_FACES[name]
    group = tuple(face for face in faces if face.italic == bool(italic))
    if not group:
        if strict:
            raise FontFaceError(
                f"{name} 没有 {style_name(weight, italic)} 字面；可用字面："
                f"{', '.join(available_styles(name))}"
            )
        group = tuple(face for face in faces if not face.italic)

    # 静态字面精确命中优先；可变字体按 wght 轴落字重。
    for face in group:
        if face.weight_axis is None and face.weight == weight:
            return ResolvedFace(name, face.filename, weight, bool(italic))
    for face in group:
        if face.weight_axis is None:
            continue
        low, high = face.weight_axis
        if low <= weight <= high:
            variation = None if weight == face.weight else weight
            return ResolvedFace(name, face.filename, weight, bool(italic), variation)
    # 该字重在这组字面里没有轴覆盖：取最近的静态字面（strict 时仍报错）。
    if group and not strict:
        nearest = min(group, key=lambda face: abs(face.weight - weight))
        return ResolvedFace(name, nearest.filename, nearest.weight, nearest.italic)
    raise FontFaceError(
        f"{name} 没有 weight={weight} / italic={italic} 的字面；可用字面："
        f"{', '.join(available_styles(name))}"
    )

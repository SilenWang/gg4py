"""把 SVG 里的 `<text>` 就地换成字形轮廓（`<path>`），再交给 resvg 栅格化。

**为什么需要这一步**（M0-9 踩到的真实坑）：resvg 0.47 无法从 pixi 的
`NotoSansCJKsc-VF.ttf`（36 MB、65535 个字形）里取出轮廓——同一份 SVG 在
`resvg` 里是**空白**，而 subset 过的同字体、以及 DejaVu 都能正常画。参考图里的
中文标签因此会整段消失，差分变成「拿空白比字」，比不出任何东西。

与其换光栅器或往仓库里塞一份静态字体，这里把 R 的文本按 svglite 的语义就地
转成路径：

- `x` / `y` / `text-anchor` 决定起点（`y` 是 alphabetic 基线）；
- `textLength` + `lengthAdjust="spacingAndGlyphs"` 表示「整段压/拉到这个宽度」，
  这里按同一个比例缩放字形与步进；
- 字形来自 `ggskia.text.TextShaper`（与设备同一份字体栈、同一套 cmap/hinting），
  所以轮廓与实测图同源；**宽度与位置仍以 R 写下的值为准**，两侧的度量差异不会
  被这一步掩盖。

转换只处理 svglite 会写的那几种属性；遇到 `<tspan>` 之类更复杂的结构原样保留
（resvg 画不出来时差分自然会红，而不是静默通过）。
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from xml.etree import ElementTree as ET

__all__ = ["SvgTextError", "inline_text_paths", "path_to_d"]

SVG_NS = "http://www.w3.org/2000/svg"
_TEXT = f"{{{SVG_NS}}}text"
_TSPAN = f"{{{SVG_NS}}}tspan"
_PATH = f"{{{SVG_NS}}}path"
_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


class SvgTextError(RuntimeError):
    """SVG 无法解析或文本转换失败。"""


def _number(value: str | None, default: float | None = None) -> float | None:
    if value is None:
        return default
    match = _NUMBER.match(value.strip())
    return float(match.group(0)) if match else default


def _style(element: ET.Element) -> dict[str, str]:
    """`style="a: b; c: d"` → 属性表（属性名小写）。"""
    properties: dict[str, str] = {}
    raw = element.get("style") or ""
    for item in raw.split(";"):
        if ":" not in item:
            continue
        key, _, value = item.partition(":")
        properties[key.strip().lower()] = value.strip()
    for name in (
        "font-size",
        "font-family",
        "font-weight",
        "font-style",
        "fill",
        "fill-opacity",
        "text-anchor",
        "data-baseline",
        "dominant-baseline",
        "alignment-baseline",
        "letter-spacing",
        "word-spacing",
        "opacity",
    ):
        if element.get(name) is not None and name not in properties:
            properties[name] = element.get(name, "")
    return properties


def _font_family(value: str) -> str:
    # 先按逗号取第一个族，再去引号：viewer 写的是 `"Noto Sans", "Noto Sans CJK SC", …`，
    # 先整体去引号只对 svglite 的单族写法有效（`"Noto Sans";`）。
    family = value.split(",")[0].strip().strip("'\"")
    return family or "sans"


def _font_key(properties: dict[str, str]) -> str:
    """svglite 的 `font-family` + `font-weight` + `font-style` → IR 字体 key。

    svglite 会写 `font-weight: bold` / `font-style: italic`（ggplot2 的
    `fontface = "bold.italic"`），轮廓转换必须按真实字面取字形，否则粗斜体
    会被画成常规字面（`docs/notes/metrics-ledger.md`）。
    """
    family = _font_family(properties.get("font-family", "sans"))
    weight = properties.get("font-weight", "").strip().lower()
    style = properties.get("font-style", "").strip().lower()
    bold = weight in ("bold", "bolder") or (weight.isdigit() and int(weight) >= 600)
    italic = style in ("italic", "oblique")
    suffix = "bold-italic" if bold and italic else "bold" if bold else "italic" if italic else ""
    return f"{family}:{suffix}" if suffix else family


def path_to_d(path) -> str:
    """skia 路径 → SVG `d`（conic 用 `ConvertConicToQuads` 折成二次段）。"""
    import skia

    iterator = skia.Path.Iter(path, False)
    parts: list[str] = []
    while True:
        verb, points = iterator.next()
        if verb == skia.Path.kMove_Verb:
            parts.append(f"M{points[0].x():.3f} {points[0].y():.3f}")
        elif verb == skia.Path.kLine_Verb:
            parts.append(f"L{points[1].x():.3f} {points[1].y():.3f}")
        elif verb == skia.Path.kQuad_Verb:
            parts.append(
                f"Q{points[1].x():.3f} {points[1].y():.3f} {points[2].x():.3f} {points[2].y():.3f}"
            )
        elif verb == skia.Path.kCubic_Verb:
            parts.append(
                f"C{points[1].x():.3f} {points[1].y():.3f} "
                f"{points[2].x():.3f} {points[2].y():.3f} "
                f"{points[3].x():.3f} {points[3].y():.3f}"
            )
        elif verb == skia.Path.kConic_Verb:
            quads = skia.Path.ConvertConicToQuads(
                points[0], points[1], points[2], iterator.conicWeight()
            )
            if quads and len(quads) >= 3:
                parts.append(
                    f"Q{quads[1].x():.3f} {quads[1].y():.3f} {quads[2].x():.3f} {quads[2].y():.3f}"
                )
                index = 3
                while index + 2 < len(quads):
                    parts.append(
                        f"Q{quads[index].x():.3f} {quads[index].y():.3f} "
                        f"{quads[index + 1].x():.3f} {quads[index + 1].y():.3f}"
                    )
                    index += 2
        elif verb == skia.Path.kClose_Verb:
            parts.append("Z")
        else:
            break
    return " ".join(parts)


def _text_runs(element: ET.Element) -> list[tuple[str, float, float]]:
    """一个 `<text>` 的文本行：`[（文字, x, y）…]`。

    查看器把多行写成 `<tspan x=… y=…>`；svglite 的多行也会落到 tspan。这里
    逐行取自己的 x / y，而不是把所有文字拼成一行——后者的行距会整段塌掉。
    """
    spans = [child for child in element if child.tag == _TSPAN]
    if not spans:
        return [
            (
                "".join(element.itertext()),
                _number(element.get("x"), 0.0) or 0.0,
                _number(element.get("y"), 0.0) or 0.0,
            )
        ]
    runs: list[tuple[str, float, float]] = []
    for span in spans:
        x = _number(span.get("x"), _number(element.get("x"), 0.0)) or 0.0
        y = _number(span.get("y"), _number(element.get("y"), 0.0)) or 0.0
        runs.append(("".join(span.itertext()), x, y))
    return runs


def _baseline_shift(properties: dict[str, str], shaper, font_key: str, size: float) -> float:
    """`dominant-baseline` → 相对 alphabetic 基线的 y 偏移。

    svglite 写的 `<text>` 都是 alphabetic 基线，查看器的 `<text>` 用
    `dominant-baseline="central"`（IR 的 `baseline` 是 middle / top / bottom）。
    转轮廓时不做这一步，文字会整体向下掉半个字高。

    这里的口径与 `ggskia.skia._place_text` 一致：R 的 strheight 是 **cap
    height × 72.27/72**，不是 ascent/descent。viewer 已经按 1.44 × size 写好
    tspan 的行距，所以每行的偏移只差一个 cap（middle 是 cap/2，top 是 cap，
    bottom / alphabetic 是 0）。
    """
    baseline = (
        (
            properties.get("data-baseline")
            or properties.get("dominant-baseline")
            or properties.get("alignment-baseline")
            or ""
        )
        .strip()
        .lower()
    )
    if not baseline:
        return 0.0
    metrics = shaper.font(shaper.primary_face(font_key), size).getMetrics()
    cap = float(metrics.fCapHeight)
    if cap > 0:
        cap *= 72.27 / 72.0
    else:  # 位图字体（CBDT）没有 cap height：退回字面框
        cap = float(-metrics.fAscent) + float(metrics.fDescent)
    if baseline in ("central", "middle"):
        return cap / 2.0
    if baseline in ("text-before-edge", "hanging", "top"):
        return cap
    return 0.0


def _text_path(
    element: ET.Element,
    shaper,
    text: str,
    x: float,
    y: float,
) -> tuple[str, float, float, str] | None:
    """一行 `<text>` →（`d`, 起点 x, 基线 y, style）。"""
    import skia

    if not text:
        return None
    properties = _style(element)
    size = _number(properties.get("font-size"), 12.0) or 12.0
    font_key = _font_key(properties)
    fill = properties.get("fill", "#000000")
    anchor = (properties.get("text-anchor") or element.get("text-anchor") or "start").strip()
    text_length = _number(element.get("textLength"))

    path = skia.Path()
    pen = 0.0
    measured = 0.0
    for run in shaper.runs(font_key, text, size):
        font = shaper.font(run.face, size)
        for gid, offset in zip(run.gids, run.offsets, strict=False):
            glyph = font.getPath(gid)
            if glyph is not None:
                path.addPath(glyph, pen + offset, 0.0)
        pen += run.advance
        measured += run.advance

    target = text_length if text_length is not None else measured
    if target and measured > 0 and abs(target - measured) > 1e-9:
        # `lengthAdjust="spacingAndGlyphs"`：字形与步进一起缩放。
        path.transform(skia.Matrix.Scale(target / measured, 1.0))
    shift = {"middle": 0.5, "end": 1.0}.get(anchor, 0.0)
    start = x - target * shift
    baseline = y + _baseline_shift(properties, shaper, font_key, size)
    style = f"fill: {fill}; stroke: none;"
    fill_opacity = properties.get("fill-opacity")
    if fill_opacity:
        style += f" fill-opacity: {fill_opacity};"
    return path_to_d(path), start, baseline, style


def inline_text_paths(source: Path, target: Path, *, shaper=None) -> int:
    """读 `source`，把 `<text>` 换成 `<path>` 写到 `target`；返回转换的文本数。

    没有 `<text>` 的 SVG（我们自己的设备产物）原样复制——路径与字体都在设备侧
    就已经是轮廓，这一步不该碰它。
    """
    from ggskia.text import TextShaper

    payload = source.read_text(encoding="utf-8")
    if "<text" not in payload:
        target.write_text(payload, encoding="utf-8")
        return 0
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise SvgTextError(f"{source} 不是合法 XML：{error}") from error

    shaper = shaper if shaper is not None else TextShaper(emoji="outline")
    parents = {child: parent for parent in root.iter() for child in parent}
    converted = 0
    for element in list(root.iter(_TEXT)):
        parent = parents.get(element)
        if parent is None:
            continue
        index = list(parent).index(element)
        replacements: list[ET.Element] = []
        for text, x, y in _text_runs(element):
            result = _text_path(element, shaper, text, x, y)
            if result is None:
                continue
            d, start, baseline, style = result
            if math.isnan(start) or math.isnan(baseline):
                continue
            # 查看器的文字把页面变换 / 旋转放在 `<text transform>` 上；转轮廓时
            # 必须保留它，否则所有文字都会落到页面原点（不是「近似」，是画错）。
            transform = f"translate({start:.3f} {baseline:.3f})"
            existing = (element.get("transform") or "").strip()
            if existing:
                transform = f"{existing} {transform}"
            replacements.append(
                ET.Element(
                    _PATH,
                    {
                        "d": d,
                        # 用内联 style 而不是 fill 属性：svglite 的 `<style>` 里
                        # `.svglite path { fill: none; stroke: #000 }` 的优先级高于表现属性，
                        # 只写 fill 的话字形会被画成描边轮廓（整张参考图因此变粗）。
                        "style": style,
                        "transform": transform,
                    },
                )
            )
        if not replacements:
            continue
        parent.remove(element)
        for offset, replacement in enumerate(replacements):
            parent.insert(index + offset, replacement)
        converted += 1

    target.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode"),
        encoding="utf-8",
    )
    return converted

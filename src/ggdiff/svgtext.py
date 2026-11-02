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
        "text-anchor",
        "opacity",
        "fill-opacity",
    ):
        if element.get(name) is not None and name not in properties:
            properties[name] = element.get(name, "")
    return properties


def _font_family(value: str) -> str:
    family = value.strip().strip("'\"").split(",")[0].strip()
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


def _text_path(element: ET.Element, shaper) -> tuple[str, float, float, str]:
    """一个 `<text>` →（`d`, 起点 x, 基线 y, fill）。"""
    import skia

    text = "".join(element.itertext())
    if not text:
        return "", 0.0, 0.0, "#000000"
    properties = _style(element)
    size = _number(properties.get("font-size"), 12.0) or 12.0
    font_key = _font_key(properties)
    fill = properties.get("fill", "#000000")
    x = _number(element.get("x"), 0.0) or 0.0
    y = _number(element.get("y"), 0.0) or 0.0
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
    return path_to_d(path), start, y, fill


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
        d, start, baseline, fill = _text_path(element, shaper)
        parent = parents.get(element)
        if parent is None or math.isnan(start) or math.isnan(baseline):
            continue
        replacement = ET.Element(
            _PATH,
            {
                "d": d,
                # 用内联 style 而不是 fill 属性：svglite 的 `<style>` 里
                # `.svglite path { fill: none; stroke: #000 }` 的优先级高于表现属性，
                # 只写 fill 的话字形会被画成描边轮廓（整张参考图因此变粗）。
                "style": f"fill: {fill}; stroke: none;",
                "transform": f"translate({start:.3f} {baseline:.3f})",
            },
        )
        index = list(parent).index(element)
        parent.remove(element)
        parent.insert(index, replacement)
        converted += 1

    target.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode"),
        encoding="utf-8",
    )
    return converted

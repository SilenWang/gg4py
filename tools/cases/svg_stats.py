#!/usr/bin/env python
"""SVG 笔画 / 填充统计（SIL-839）。

    pixi run svg:stats -- <a.svg> [b.svg ...]

为什么有这个工具：SIL-839 连着两轮把「白网格」数错——svglite 写
`stroke: #FFFFFF`、我们的设备写 `stroke="white"`，临场 `grep` 大小写一错就得出
「0 条」的结论。这里把两种写法归一化后再按 `(stroke, stroke-width)` 分组计数，
两个 SVG 并列打出来，差异一眼可见。

归一化口径：

- 颜色关键字 → 十六进制（`white` → `#FFFFFF`、`black` → `#000000`，覆盖 CSS 的
  16 个基本色 + `grey*` / `gray*` / `transparent` / `none`）；
- `rgb(r,g,b)` → `#RRGGBB`；
- 属性写法两种都认：`stroke="#FFF"` 与 `style='stroke: #FFFFFF; …'`；
- 线宽统一成两位小数（我们的设备写 `0.53348917`，svglite 写 `0.53`）。
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

__all__ = ["normalise_colour", "stats"]

_COLOURS = {
    "white": "#FFFFFF",
    "black": "#000000",
    "red": "#FF0000",
    "green": "#00FF00",
    "blue": "#0000FF",
    "yellow": "#FFFF00",
    "cyan": "#00FFFF",
    "magenta": "#FF00FF",
    "gray": "#BEBEBE",
    "grey": "#BEBEBE",
    "none": "none",
    "transparent": "none",
}

_ELEMENT = re.compile(r"<(path|polyline|polygon|line|rect|circle)\b([^>]*)>", re.S)
_ATTR = re.compile(r"([a-zA-Z-]+)\s*=\s*'([^']*)'|([a-zA-Z-]+)\s*=\s*\"([^\"]*)\"")
_STYLE_ITEM = re.compile(r"([a-zA-Z-]+)\s*:\s*([^;]+)")


def normalise_colour(value: str | None) -> str:
    """把颜色写法折成 `#RRGGBB` / `none` / `None`。"""
    if value is None:
        return "None"
    text = value.strip().strip("'\"").lower()
    if not text:
        return "None"
    if text in _COLOURS:
        return _COLOURS[text]
    match = re.fullmatch(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", text)
    if match:
        r, g, b = (int(part) for part in match.groups())
        return f"#{r:02X}{g:02X}{b:02X}"
    if re.fullmatch(r"#[0-9a-f]{3}", text):
        return "#" + "".join(char * 2 for char in text[1:]).upper()
    if re.fullmatch(r"#[0-9a-f]{6}", text):
        return text.upper()
    if re.fullmatch(r"(grey|gray)\d+", text):
        # `grey60` 这类：ggplot2 的 greyNN 是 NN% 灰度。
        level = int(re.sub(r"^(grey|gray)", "", text))
        value_255 = round(level * 255 / 100)
        return f"#{value_255:02X}{value_255:02X}{value_255:02X}"
    return text.upper()


def _attributes(body: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in _ATTR.finditer(body):
        if match.group(1) is not None:
            attrs[match.group(1)] = match.group(2)
        else:
            attrs[match.group(3)] = match.group(4)
    style = attrs.get("style")
    if style:
        for item in _STYLE_ITEM.finditer(style):
            attrs.setdefault(item.group(1).strip(), item.group(2).strip())
    return attrs


def stats(
    path: Path,
) -> tuple[Counter[tuple[str, str]], Counter[tuple[str, str]], Counter[str]]:
    """返回 `(按 stroke 分类, 按 fill 分类, 按路径形状分类)` 三个计数器。"""
    text = path.read_text(encoding="utf-8")
    strokes: Counter[tuple[str, str]] = Counter()
    fills: Counter[tuple[str, str]] = Counter()
    shapes: Counter[str] = Counter()
    for match in _ELEMENT.finditer(text):
        attrs = _attributes(match.group(2))
        width = attrs.get("stroke-width")
        try:
            width_text = f"{float(width):.2f}" if width is not None else "—"
        except ValueError:
            width_text = str(width)
        stroke = normalise_colour(attrs.get("stroke"))
        if stroke != "none":
            strokes[(stroke, width_text)] += 1
        fill = normalise_colour(attrs.get("fill"))
        if fill != "none":
            fills[(fill, "—")] += 1
        # 元素表示因渲染器而异：svglite 把圆点写成 `<circle>`，skia 写成
        # `<path d="…">`。只数元素名会把「表示不同」误判成「少画了」——按 `d` 里
        # 的圆弧命令数分类才能跨渲染器比较（SIL-839 在这上面栽过两次）。
        datum = attrs.get("d")
        if datum:
            arcs = datum.count("a") + datum.count("A")
            if arcs >= 2:
                shapes["circle（≥2 段弧）"] += 1
            elif arcs == 1:
                shapes["arc（1 段弧）"] += 1
            else:
                shapes["other path"] += 1
        elif match.group(1) == "circle":
            shapes["circle（<circle>）"] += 1
    return strokes, fills, shapes


def main(argv: list[str]) -> int:
    paths = [Path(item) for item in argv[1:]]
    if not paths:
        print(__doc__)
        return 2
    for path in paths:
        if not path.is_file():
            print(f"找不到 {path}", file=sys.stderr)
            return 2
        strokes, fills, shapes = stats(path)
        print(f"== {path}")
        print("  stroke（颜色 × 线宽）:")
        for (colour, width), count in sorted(strokes.items(), key=lambda item: (-item[1], item[0])):
            print(f"    {count:5d}  {colour:9s} {width}")
        print("  fill:")
        for (colour, _), count in sorted(fills.items(), key=lambda item: (-item[1], item[0])):
            print(f"    {count:5d}  {colour}")
        print("  形状（跨渲染器可比；svglite 的圆点是 `<circle>`、skia 是两段弧的 `<path>`）:")
        for shape, count in sorted(shapes.items(), key=lambda item: (-item[1], item[0])):
            print(f"    {count:5d}  {shape}")
    if len(paths) == 2:
        left, _, left_shapes = stats(paths[0])
        right, _, right_shapes = stats(paths[1])
        keys = sorted(set(left) | set(right))
        drift = [
            (key, left.get(key, 0), right.get(key, 0))
            for key in keys
            if left.get(key, 0) != right.get(key, 0)
        ]
        print("== 差异（stroke）:")
        if not drift:
            print("    无")
        for (colour, width), a, b in drift:
            print(f"    {colour:9s} {width:>5s}  {paths[0].name}={a}  {paths[1].name}={b}")
        print("== 差异（形状）:")
        shape_keys = sorted(set(left_shapes) | set(right_shapes))
        shape_drift = [
            (key, left_shapes.get(key, 0), right_shapes.get(key, 0))
            for key in shape_keys
            if left_shapes.get(key, 0) != right_shapes.get(key, 0)
        ]
        if not shape_drift:
            print("    无")
        for shape, a, b in shape_drift:
            print(f"    {shape:20s}  {paths[0].name}={a}  {paths[1].name}={b}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

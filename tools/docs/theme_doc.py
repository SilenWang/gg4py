"""生成 `docs/notes/theme.md` 的两个派生区块（M2-5：文档不再手写主题枚举）。

区块由 `ggcore.registry` 与 `ggcore.theme.resolve_theme()` 直接派生：

- `registered-themes`：注册表里每一套主题（入口名、`Theme.name`、定义的
  元素数、解析后的元素数、构造器说明），别名（`gray` → `grey`）也由「同一个
  构造器对象」推出来；
- `theme-elements`：每个元素在每一套主题下的解析值，按元素名前缀分组
  （根元素 / `axis.*` / `legend.*` / `panel.*` / `plot.*` / `strip.*` / 其它）。

区块之外的散文仍是人写的；生成器只替换两个标记之间内容，`--check` 逐字节
比对，所以改了主题数值却忘了重跑会红。

用法：
    pixi run docs:theme          # 重写两个区块
    pixi run docs:theme:check    # 只校验是否最新（`pixi run check` 里跑这个）
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from ggcore import registry  # noqa: E402
from ggcore import theme as theme_module  # noqa: E402
from ggcore.theme import (  # noqa: E402
    ELEMENT_TREE,
    ElementBlank,
    ElementGeom,
    ElementLine,
    ElementPoint,
    ElementPolygon,
    ElementRect,
    ElementText,
    Margin,
    Rel,
    resolve_theme,
)
from ggcore.units import Unit  # noqa: E402

DOC_PATH = ROOT / "docs" / "notes" / "theme.md"

THEMES_BEGIN = "<!-- BEGIN GENERATED: registered-themes -->"
THEMES_END = "<!-- END GENERATED: registered-themes -->"
ELEMENTS_BEGIN = "<!-- BEGIN GENERATED: theme-elements -->"
ELEMENTS_END = "<!-- END GENERATED: theme-elements -->"

_ROOT_NAMES = frozenset(
    {"line", "rect", "text", "point", "polygon", "geom", "title", "spacing", "margins"}
)

_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("根元素", tuple(sorted(_ROOT_NAMES))),
    ("`axis.*`", ("axis.",)),
    ("`legend.*`", ("legend.",)),
    ("`panel.*`", ("panel.",)),
    ("`plot.*`", ("plot.",)),
    ("`strip.*`", ("strip.",)),
)


def _num(value: float) -> str:
    text = f"{float(value):.6g}"
    return text if text not in ("-0", "-0.0") else "0"


_UNIT_SUFFIX = {
    "points": "pt",
    "lines": "lines",
    "cm": "cm",
    "mm": "mm",
    "npc": "npc",
    "null": "null",
    "native": "native",
    "inches": "in",
}


def _unit(value: Unit) -> str:
    parts = []
    for element in value.elements:
        suffix = _UNIT_SUFFIX.get(element.kind, element.kind)
        parts.append(f"{_num(element.amount)}{suffix}")
    return "+".join(parts)


def _margin(value: Margin) -> str:
    sides = ["auto" if side is None else _unit(side) for side in value.as_tuple()]
    if all(side == "auto" for side in sides):
        return "m(auto)"
    return f"m({','.join(sides)})"


def _colour(value: Any) -> str:
    return "NA" if value is None else str(value)


def _text(value: ElementText) -> str:
    parts = ["text"]
    if value.family:
        parts.append(f"family={value.family!r}")
    if value.face is not None:
        parts.append(f"face={value.face}")
    if value.italic is not None:
        parts.append(f"italic={value.italic}")
    if value.fontweight is not None:
        parts.append(f"weight={value.fontweight}")
    if value.fontwidth is not None:
        parts.append(f"width={value.fontwidth}")
    if value.size is not None:
        parts.append(f"{_num(value.size)}pt")
    if value.colour is not None:
        parts.append(_colour(value.colour))
    for label, item in (("h", value.hjust), ("v", value.vjust), ("a", value.angle)):
        if item is not None:
            parts.append(f"{label}{_num(item)}")
    if value.lineheight is not None:
        parts.append(f"lh{_num(value.lineheight)}")
    if value.margin is not None:
        parts.append(_margin(value.margin))
    if value.debug:
        parts.append("debug")
    return " ".join(parts)


def _line(value: ElementLine) -> str:
    parts = ["line", _colour(value.colour)]
    if value.linewidth is not None:
        parts.append(f"{_num(value.linewidth)}mm")
    if value.linetype is not None:
        parts.append(f"lty{value.linetype}")
    if value.lineend is not None or value.linejoin is not None:
        parts.append(f"{value.lineend or '?'}/{value.linejoin or '?'}")
    if value.arrow:
        parts.append(f"arrow={_colour(value.arrow_fill)}")
    return " ".join(parts)


def _rect(value: ElementRect | ElementPolygon) -> str:
    parts = [
        "rect" if isinstance(value, ElementRect) else "polygon",
        f"fill={_colour(value.fill)}",
        f"colour={_colour(value.colour)}",
    ]
    if value.linewidth is not None:
        parts.append(f"{_num(value.linewidth)}mm")
    if value.linetype is not None:
        parts.append(f"lty{value.linetype}")
    if value.linejoin is not None:
        parts.append(value.linejoin)
    return " ".join(parts)


def _point(value: ElementPoint) -> str:
    parts = ["point", _colour(value.colour)]
    if value.shape is not None:
        parts.append(f"p{value.shape}")
    if value.size is not None:
        parts.append(f"{_num(value.size)}mm")
    parts.append(f"fill={_colour(value.fill)}")
    if value.stroke is not None:
        parts.append(f"stroke={_num(value.stroke)}")
    return " ".join(parts)


def _geom(value: ElementGeom) -> str:
    parts = [
        "geom",
        f"ink={_colour(value.ink)}",
        f"paper={_colour(value.paper)}",
        f"accent={_colour(value.accent)}",
    ]
    for label, item in (
        ("lw", value.linewidth),
        ("bw", value.borderwidth),
        ("fs", value.fontsize),
        ("ps", value.pointsize),
    ):
        if item is not None:
            parts.append(f"{label}={_num(item)}")
    if value.linetype is not None:
        parts.append(f"lty{value.linetype}")
    if value.bordertype is not None:
        parts.append(f"blty{value.bordertype}")
    if value.family:
        parts.append(f"family={value.family!r}")
    if value.pointshape is not None:
        parts.append(f"p{value.pointshape}")
    return " ".join(parts)


def render_value(value: Any) -> str:
    """解析值 → 表格单元格（紧凑、单行、可 diff）。"""
    if value is None:
        return "—"
    if isinstance(value, ElementBlank):
        return "blank"
    if isinstance(value, Rel):
        return f"rel({_num(value.mult)})"
    if isinstance(value, Unit):
        return _unit(value)
    if isinstance(value, Margin):
        return _margin(value)
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        return _num(value)
    if isinstance(value, str):
        return repr(value) if not value.startswith("#") else value
    if isinstance(value, ElementText):
        return _text(value)
    if isinstance(value, ElementLine):
        return _line(value)
    if isinstance(value, ElementRect):
        return _rect(value)
    if isinstance(value, ElementPolygon):
        return _rect(value)
    if isinstance(value, ElementPoint):
        return _point(value)
    if isinstance(value, ElementGeom):
        return _geom(value)
    raise TypeError(f"render_value() 不认识 {type(value).__name__}")


def _theme_entries() -> list[tuple[str, Any]]:
    entries = []
    for name in registry.registered("theme"):
        constructor = getattr(registry, f"theme_{name}")
        entries.append((name, constructor))
    return entries


def _summary(name: str, constructor: Any) -> str:
    """构造器说明的第一行；注册表入口是包装函数，优先取 `ggcore.theme` 的原件。"""
    original = getattr(theme_module, f"theme_{name}", None)
    source = original if original is not None else constructor
    doc = (getattr(source, "__doc__", None) or "").strip().splitlines()
    return doc[0].strip() if doc else ""


def render_registered_themes() -> list[str]:
    entries = _theme_entries()
    by_object: dict[int, list[str]] = defaultdict(list)
    for name, constructor in entries:
        by_object[id(constructor)].append(name)

    lines = [
        "| 入口 | `Theme.name` | 完整主题 | 定义元素 | 解析元素 | 说明 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, constructor in entries:
        theme = constructor()
        resolved = resolve_theme(theme)
        summary = _summary(name, constructor).replace("|", "\\|")
        lines.append(
            f"| `theme_{name}()` | `{theme.name}` | {'✓' if theme.complete else '✗'} "
            f"| {len(theme.elements)} | {len(resolved.elements)} | {summary} |"
        )

    aliases = [names for names in by_object.values() if len(names) > 1]
    if aliases:
        lines.append("")
        for names in aliases:
            head, *rest = names
            links = "、".join(f"`theme_{name}()`" for name in rest)
            lines.append(f"{links} 是 `theme_{head}()` 的别名（同一个构造器对象）。")
    return lines


def render_elements() -> list[str]:
    entries = _theme_entries()
    names = [name for name, _ in entries]
    resolvers = {name: resolve_theme(constructor()) for name, constructor in entries}
    all_names = set(ELEMENT_TREE)

    grouped: list[tuple[str, list[str]]] = []
    used: set[str] = set()
    for label, rule in _GROUPS:
        if isinstance(rule, tuple) and rule and rule[0].endswith("."):
            matched = sorted(name for name in all_names if name.startswith(rule[0]))
        else:
            matched = sorted(name for name in rule if name in all_names)
        grouped.append((label, matched))
        used.update(matched)
    grouped.append(("其它", sorted(all_names - used)))

    lines: list[str] = []
    header = "| 元素 | " + " | ".join(f"`{name}`" for name in names) + " |"
    divider = "| --- | " + " | ".join("---" for _ in names) + " |"
    for label, matched in grouped:
        if not matched:
            continue
        lines.append(f"#### {label}")
        lines.append("")
        lines.append(header)
        lines.append(divider)
        for element_name in matched:
            cells = [render_value(resolvers[name].elements[element_name]) for name in names]
            lines.append(f"| `{element_name}` | " + " | ".join(cells) + " |")
        lines.append("")
    return lines


def _replace_region(text: str, begin: str, end: str, body: list[str]) -> str:
    start = text.index(begin) + len(begin)
    stop = text.index(end)
    block = "\n" + "\n".join(body) + "\n"
    return text[:start] + block + text[stop:]


def render(text: str) -> str:
    text = _replace_region(text, THEMES_BEGIN, THEMES_END, render_registered_themes())
    return _replace_region(text, ELEMENTS_BEGIN, ELEMENTS_END, render_elements())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = parser.parse_args(argv)

    original = DOC_PATH.read_text(encoding="utf-8")
    updated = render(original)
    if args.check:
        if updated != original:
            print(
                f"{DOC_PATH.relative_to(ROOT)} 已过期：跑 `pixi run docs:theme` 重新生成立表区块。",
                file=sys.stderr,
            )
            return 1
        print(f"{DOC_PATH.relative_to(ROOT)} 是最新的")
        return 0

    if updated == original:
        print(f"{DOC_PATH.relative_to(ROOT)} 无变化")
        return 0
    DOC_PATH.write_text(updated, encoding="utf-8")
    print(f"wrote {DOC_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

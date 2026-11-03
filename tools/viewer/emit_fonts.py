#!/usr/bin/env python
"""把受管字体接给浏览器查看器（M2-S1）：`rules.json` → @font-face + TS 常量。

查看器以前只写 `font-family: "Noto Sans CJK SC", "DejaVu Sans", sans-serif`，
真正画字的是**宿主** fontconfig（`tools/viewer/playwright_env.py` 才把
`FONTCONFIG_FILE` 指进 pixi 环境）。这有两个问题：字体族名与回退顺序是第二份
声明，而且用户机器上装的什么字体就会画成什么。

现在：

* `web/viewer/fonts.css` 按 `ggcore.metrics.faces.FAMILY_FACES` 逐字面写
  `@font-face`，`src` 指向 `fonts/<文件名>`；
* `web/viewer/fonts/` 是受管字体目录的副本（不入库，`viewer:build` 每次刷新）；
* `web/viewer/src/fonts.generated.ts` 给出「文件 → 字族」与默认栈，
  `render.ts` 的 `font-family` 只由它拼，**不再带 `sans-serif` 兜底**。

    pixi run viewer:build        # 先跑本脚本，再 tsc（见 pixi.toml）
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from ggcore.metrics.catalog import FontCatalog  # noqa: E402
from ggcore.metrics.faces import FAMILY_FACES  # noqa: E402
from ggcore.metrics.rules import DEFAULT_FONT_STACK, FONT_FAMILIES  # noqa: E402

VIEWER = REPO / "web" / "viewer"
CSS_PATH = VIEWER / "fonts.css"
TS_PATH = VIEWER / "src" / "fonts.generated.ts"
FONT_DIR = VIEWER / "fonts"


def faces() -> list[tuple[str, str, int, bool, tuple[int, int] | None]]:
    """(字族, 文件, weight, italic, 可变轴)，按字族声明顺序去重。"""
    out: list[tuple[str, str, int, bool, tuple[int, int] | None]] = []
    seen: set[tuple[str, int, bool]] = set()
    for group in FAMILY_FACES.values():
        for face in group:
            key = (face.filename, face.weight, face.italic)
            if key in seen:
                continue
            seen.add(key)
            out.append((face.family, face.filename, face.weight, face.italic, face.weight_axis))
    return out


def css() -> str:
    lines = [
        "/* 由 tools/viewer/emit_fonts.py 从 src/ggcore/metrics/data/rules.json 生成。",
        "   不要在别处再写一份字体回退顺序（X5 的「规则只有一份声明」）。 */",
    ]
    for family, filename, weight, italic, axis in faces():
        weight_spec = f"{axis[0]} {axis[1]}" if axis else str(weight)
        lines.append(
            "@font-face {"
            f' font-family: "{family}";'
            f' src: url("fonts/{filename}") format("truetype");'
            f" font-weight: {weight_spec};"
            f" font-style: {'italic' if italic else 'normal'};"
            " font-display: block; }"
        )
    return "\n".join(lines) + "\n"


def typescript() -> str:
    stack = list(dict.fromkeys(FONT_FAMILIES[filename] for filename in DEFAULT_FONT_STACK))
    lines = [
        "// 由 tools/viewer/emit_fonts.py 从 src/ggcore/metrics/data/rules.json 生成；",
        "// 不要手改。改字体栈请改 rules.json 并重跑 `pixi run viewer:build`。",
        "export const FONT_FAMILIES: Record<string, string> = {",
    ]
    for filename in sorted(FONT_FAMILIES):
        lines.append(f"  {json.dumps(filename)}: {json.dumps(FONT_FAMILIES[filename])},")
    lines.append("};")
    lines.append(f"export const DEFAULT_FAMILY: string = {json.dumps(stack[0])};")
    lines.append(f"export const FALLBACK_FAMILIES: readonly string[] = {json.dumps(stack)};")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="emit viewer @font-face + TS font constants")
    parser.add_argument("--no-copy", action="store_true", help="只写 css / ts，不复制字体文件")
    args = parser.parse_args(argv)

    catalog = FontCatalog()
    CSS_PATH.write_text(css(), encoding="utf-8")
    TS_PATH.write_text(typescript(), encoding="utf-8")
    copied = 0
    if not args.no_copy:
        FONT_DIR.mkdir(parents=True, exist_ok=True)
        for _, filename, _, _, _ in faces():
            target = FONT_DIR / filename
            source = catalog.path(filename)
            if not target.is_file() or target.stat().st_size != source.stat().st_size:
                shutil.copyfile(catalog.path(filename), target)
                copied += 1
    families = len(dict.fromkeys(face[0] for face in faces()))
    copied_note = (
        f", copied {copied} file(s) into {FONT_DIR.relative_to(REPO)}" if not args.no_copy else ""
    )
    print(
        f"viewer fonts: {len(faces())} faces / {families} families "
        f"-> {CSS_PATH.relative_to(REPO)}, {TS_PATH.relative_to(REPO)}" + copied_note
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

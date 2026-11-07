#!/usr/bin/env python
"""`docs:upstream-map:check`：模块 ↔ 上游对照表的双向门禁（SIL-872）。

    pixi run docs:upstream-map:check

`docs/notes/upstream-map.md` 是 `src/ggcore` 每个模块的唯一归属表。表一旦整体
漂移，读文档的人会以为做过的模块不存在、没做的模块已经做完——所以这里断言
**两个方向**，任一处对不上就非 0 退出：

1. **表里有 → 能 import**：第一列（「Python 模块」）里写出的每个 `ggcore.*` /
   `ggio.*` / `ggshape.*` / `ggskia.*` / `ggdiff.*` 名字都真的
   `importlib.import_module()` 一次。写错名字、或删了模块却留行，这里红。
2. **源码有 → 表里有**：`git ls-files src/ggcore` 的每个 `*.py` 都要在表里出现，
   `__init__.py` 折成它所在的包名。新增模块不加行，这里红。

另外校验**状态列**只能取三档（`已实现` / `部分实现` / `刻意不做`），且每行都得
有依据：三档以外的词（`计划` / `骨架` / `待做`）会让「做了什么」重新变成模糊
判断，正是上一版整表漂移的根因。表头也必须是「Python 模块」——旧的
「Python 模块（计划）」暗示整表可以先占位，门禁拒绝它回来。

不是模块的「刻意不做」格子不进表：表里写一个不存在的模块名会让第 1 条断言
直接红，这类条目的依据写在文档的单独一节里。
"""

from __future__ import annotations

import argparse
import importlib
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

DOC = ROOT / "docs" / "notes" / "upstream-map.md"

#: 表里允许出现的包前缀。ggcore 是反向检查的面；其余是包外但同样要在表里的层。
PACKAGES = ("ggcore", "ggio", "ggshape", "ggskia", "ggdiff")

#: 状态列只认这三档，顺序即「从能做到不能做」的语义顺序。
STATES = ("已实现", "部分实现", "刻意不做")

#: 表头第一列必须是这个，不允许再出现「（计划）」这类占位措辞。
MODULE_HEADER = "Python 模块"

#: 反引号里的点分模块名。`ggio` 这种单段包名也要收（它自身就是表里的一行）。
MODULE_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)`")


def table_rows(text: str) -> Iterator[tuple[list[str], list[str]]]:
    """逐张表产出 `(表头, 数据行)`；分隔行与空行跳过。"""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line.startswith("|") or i + 1 >= len(lines):
            i += 1
            continue
        if not _is_separator(lines[i + 1].strip()):
            i += 1
            continue
        header = _cells(line)
        i += 2
        while i < len(lines):
            row = lines[i].strip()
            if not row.startswith("|"):
                break
            yield header, _cells(row)
            i += 1


def _is_separator(line: str) -> bool:
    if not line.startswith("|"):
        return False
    cells = line.strip("|").split("|")
    return all(cell.strip() and set(cell.strip()) <= {"-", ":"} for cell in cells)


def _cells(line: str) -> list[str]:
    """按未转义的 `|` 切格；GFM 的 `\\|` 是格内的字面竖线。"""
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [cell.strip().replace("\\|", "|") for cell in re.split(r"(?<!\\)\|", body)]


def documented_modules(text: str) -> dict[str, str]:
    """表里写出的模块名 → 它所在行的状态格。

    表头只要以「Python 模块」开头就收（包括带「（计划）」的坏表头）——那样
    `validate_tables` 才能报出「表头回退」，而不是让整张表的模块凭空消失。
    """
    found: dict[str, str] = {}
    for header, cells in table_rows(text):
        if not header or not header[0].startswith(MODULE_HEADER):
            continue
        state_idx = header.index("状态") if "状态" in header else -1
        module_cell = cells[0] if cells else ""
        for name in MODULE_RE.findall(module_cell):
            if name.split(".", 1)[0] in PACKAGES:
                found[name] = cells[state_idx] if 0 <= state_idx < len(cells) else ""
    return found


def _planning_header(header: list[str]) -> bool:
    return any("计划" in cell for cell in header)


def source_modules() -> dict[str, str]:
    """`src/ggcore` 里的每个模块 → 文件路径（`__init__.py` 折成包名）。"""
    out = subprocess.run(
        ["git", "ls-files", "src/ggcore"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    modules: dict[str, str] = {}
    for line in out.stdout.splitlines():
        path = line.strip()
        if not path.endswith(".py"):
            continue  # 跳过 .orig / 数据文件
        parts = path[len("src/") : -len(".py")].split("/")
        if parts[-1] == "__init__":
            module = ".".join(parts[:-1])
        else:
            module = ".".join(parts)
        modules[module] = path
    return modules


def validate_tables(text: str) -> list[str]:
    """状态列 / 表头 / 依据列的结构性问题。"""
    problems: list[str] = []
    reported: set[tuple[str, ...]] = set()
    for header, cells in table_rows(text):
        if not header or not header[0].startswith(MODULE_HEADER):
            continue
        if _planning_header(header):
            key = tuple(header)
            if key not in reported:
                reported.add(key)
                problems.append(
                    f"表头出现占位措辞：{header!r}；第一列必须是 {MODULE_HEADER!r}"
                    "（不要写「（计划）」）"
                )
            continue
        if "状态" not in header:
            problems.append(f"表头缺「状态」列：{header!r}")
            continue
        state_idx = header.index("状态")
        basis_idx = header.index("依据 / 缺口") if "依据 / 缺口" in header else len(header) - 1
        if len(cells) != len(header):
            problems.append(f"列数不符（表头 {len(header)} 列）：{cells!r}")
            continue
        state = cells[state_idx]
        if state not in STATES:
            problems.append(f"`{cells[0]}` 的状态 {state!r} 不是三档之一（{' / '.join(STATES)}）")
        basis = cells[basis_idx] if basis_idx < len(cells) else ""
        if len(basis.strip()) < 4:
            problems.append(f"`{cells[0]}` 缺依据：状态 {state!r} 但没有写判定依据 / 缺口")
    return problems


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def check(doc: Path = DOC) -> list[str]:
    text = doc.read_text(encoding="utf-8")
    problems: list[str] = []

    modules = documented_modules(text)
    if not modules:
        return [f"{_rel(doc)} 里没有解析到任何模块行（表头应为「{MODULE_HEADER}」）"]

    # 1) 表里有 → 能 import
    for name in sorted(modules):
        try:
            importlib.import_module(name)
        except Exception as exc:  # 任何导入失败都算表里写错
            problems.append(f"表里有、但 import 失败：{name}（{type(exc).__name__}: {exc}）")

    # 2) 源码有 → 表里有
    source = source_modules()
    for name, path in sorted(source.items()):
        if name not in modules:
            problems.append(f"源码有、表里没有：{name}（{path}）——新增模块必须加一行")

    # 3) 表里的 ggcore.* 不应指向不存在的源码（报错更友好）
    for name in sorted(modules):
        if name.startswith("ggcore.") and name not in source:
            problems.append(f"表里有、源码没有：{name}（模块已删或名字写错）")

    # 4) 状态 / 表头 / 依据
    problems.extend(validate_tables(text))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--doc",
        type=Path,
        default=DOC,
        help="对照表路径（默认 docs/notes/upstream-map.md）",
    )
    args = parser.parse_args(argv)

    problems = check(args.doc)
    modules = documented_modules(args.doc.read_text(encoding="utf-8"))
    source = source_modules()
    by_state = {state: sum(1 for value in modules.values() if value == state) for state in STATES}

    print(
        f"upstream-map: 表里 {len(modules)} 个模块，源码 {len(source)} 个"
        f"（已实现 {by_state['已实现']} / 部分实现 {by_state['部分实现']}"
        f" / 刻意不做 {by_state['刻意不做']}）"
    )
    if problems:
        for problem in problems:
            print(f"  ✗ {problem}", file=sys.stderr)
        print(f"upstream-map: {len(problems)} 个问题", file=sys.stderr)
        return 1
    print("upstream-map: OK（双向一致）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

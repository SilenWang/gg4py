"""X1 门禁 · `ggcore` 的 import 白名单。

只做 AST 扫描，不执行被检查的代码：凡是 `src/ggcore/` 下的 `import`，其顶层
模块名必须是标准库、numpy、CBOR 编码库或 `ggcore` 自身。其余一律失败——
pandas / Arrow / 绘图库都必须留在包外，DataFrame-like 输入在边界处转成 IR。

用法：
    pixi run gate:imports
    python tools/gates/check_import_whitelist.py --root path/to/pkg
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterator
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = REPO / "src" / "ggcore"

# 自有包（包内互相导入不算越界）。
SELF = "ggcore"
# 唯一允许的第三方：numpy 是计算内核；CBOR 编码库是 IR 的序列化格式。
THIRD_PARTY = frozenset({"numpy", "cbor2"})
STDLIB = frozenset(sys.stdlib_module_names) | {"__future__"}

HINT = (
    "ggcore 只允许标准库 / numpy / CBOR；DataFrame-like 输入与渲染都在包外，"
    "IR 用 float32 缓冲进包（docs/notes/gates.md · X1）"
)


def iter_sources(root: Path) -> Iterator[Path]:
    if root.is_file():
        yield root
        return
    yield from sorted(path for path in root.rglob("*.py") if path.is_file())


def imported_roots(tree: ast.AST) -> Iterator[tuple[str, int]]:
    """产出 (顶层模块名, 行号)。包内相对导入直接跳过。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0], node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # from . import x / from .mod import y
                continue
            if node.module:
                yield node.module.split(".")[0], node.lineno


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def check(root: Path) -> list[str]:
    """返回违规列表（空列表即通过）。"""
    problems: list[str] = []
    for path in iter_sources(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            problems.append(f"{_display(path)}:{exc.lineno}: cannot parse — {exc.msg}")
            continue
        for name, lineno in imported_roots(tree):
            if name in STDLIB or name in THIRD_PARTY or name == SELF:
                continue
            problems.append(f"{_display(path)}:{lineno}: forbidden import {name!r} — {HINT}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="X1: ggcore import whitelist (AST scan).")
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help=f"package directory or single file to scan (default: {DEFAULT_ROOT})",
    )
    args = parser.parse_args(argv)

    if not args.root.exists():
        print(f"gate:imports: root not found: {args.root}", file=sys.stderr)
        return 2

    problems = check(args.root)
    if problems:
        print(f"gate:imports: FAIL — {len(problems)} violation(s)", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    print(f"gate:imports: ok — {len(list(iter_sources(args.root)))} file(s) in {args.root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

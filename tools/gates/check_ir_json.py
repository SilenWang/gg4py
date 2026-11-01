"""X1 门禁 · IR 禁止逐元素 JSON。

`src/ggcore/` 里不允许出现 JSON 序列化调用（`json.dumps` / `json.dump` /
`json.JSONEncoder` / `to_json()` 等）：bulk 数据的线格式是 float32 缓冲 +
CBOR，逐元素 JSON 在 314 份快照的规模下体积和耗时都不可接受。

模块别名同样算数：`import json as j` 之后 `j.dumps(...)` / `j.JSONEncoder`
一样拦下（`orjson` / `ujson` / `simplejson` / `rapidjson` 同理）。

同样只做 AST 扫描，不执行被检查的代码。

用法：
    pixi run gate:ir-json
    python tools/gates/check_ir_json.py --root path/to/pkg
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = REPO / "src" / "ggcore"

# 以 json 为内核的序列化库，视同 json。
JSON_MODULES = frozenset({"json", "orjson", "ujson", "simplejson", "rapidjson"})
# 这些属性/函数一出现就是“把对象转成 JSON 文本”。
WRITE_ATTRS = frozenset({"dumps", "dump", "JSONEncoder", "to_json"})
# 禁止的调用名（`from x import dumps` 之后直接调）。
BARE_CALLS = frozenset({"dumps", "to_json", "JSONEncoder"})

HINT = (
    "IR 的 bulk 数据必须是 float32 缓冲（+ CBOR），不能逐元素 JSON 序列化"
    "（docs/notes/gates.md · X1）"
)


def iter_sources(root: Path):
    if root.is_file():
        yield root
        return
    yield from sorted(path for path in root.rglob("*.py") if path.is_file())


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def _json_aliases(tree: ast.AST) -> set[str]:
    """`from json import dumps as d` 这类别名，直接调用也要拦。"""
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and not node.level:
            if (node.module or "").split(".")[0] in JSON_MODULES:
                for alias in node.names:
                    if alias.name in WRITE_ATTRS:
                        aliases.add(alias.asname or alias.name)
    return aliases


def _json_modules(tree: ast.AST) -> dict[str, str]:
    """`import json as j` / `import orjson as oj`：本地名 → JSON 库名。"""
    modules: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in JSON_MODULES:
                    modules[alias.asname or top] = top
    return modules


def violations(tree: ast.AST) -> list[tuple[int, str]]:
    """返回 (行号, 说明) 列表。"""
    found: list[tuple[int, str]] = []
    aliases = _json_aliases(tree)
    modules = _json_modules(tree)

    for node in ast.walk(tree):
        # from json import dumps / JSONEncoder
        if isinstance(node, ast.ImportFrom) and not node.level:
            if (node.module or "").split(".")[0] in JSON_MODULES:
                for alias in node.names:
                    if alias.name in WRITE_ATTRS:
                        found.append((node.lineno, f"from {node.module} import {alias.name}"))
        # json.dumps(...) / j.dumps / oj.JSONEncoder（含 import ... as 的别名）
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            literal = node.value.id if node.value.id in JSON_MODULES else None
            module = modules.get(node.value.id, literal)
            if module is not None and node.attr in WRITE_ATTRS:
                found.append((node.lineno, f"{node.value.id}.{node.attr}"))
            elif node.attr == "to_json":
                found.append((node.lineno, f".{node.attr}"))
        # from json import dumps as d 之后直接调 d(...)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in aliases | BARE_CALLS:
                found.append((node.lineno, f"{node.func.id}(...)"))
    return found


def check(root: Path) -> list[str]:
    problems: list[str] = []
    for path in iter_sources(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            problems.append(f"{_display(path)}:{exc.lineno}: cannot parse — {exc.msg}")
            continue
        for lineno, what in violations(tree):
            problems.append(f"{_display(path)}:{lineno}: per-element JSON — {what} — {HINT}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="X1: forbid per-element JSON in ggcore.")
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help=f"package directory or single file to scan (default: {DEFAULT_ROOT})",
    )
    args = parser.parse_args(argv)

    if not args.root.exists():
        print(f"gate:ir-json: root not found: {args.root}", file=sys.stderr)
        return 2

    problems = check(args.root)
    if problems:
        print(f"gate:ir-json: FAIL — {len(problems)} violation(s)", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    print(f"gate:ir-json: ok — {len(list(iter_sources(args.root)))} file(s) in {args.root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""X1 门禁 · `ggcore` 的 import 白名单。

只做 AST 扫描，不执行被检查的代码：凡是 `src/ggcore/` 下的 `import`，其顶层
模块名必须是标准库、numpy、CBOR 编码库或 `ggcore` 自身。其余一律失败——
pandas / Arrow / 绘图库都必须留在包外，DataFrame-like 输入在边界处转成 IR。

`import` 语句看得见，模块名字符串看不见，所以动态导入单独看住：
`importlib.import_module(...)` / `__import__(...)` 的参数是字符串字面量时按同
一份白名单判定，不是字面量则直接判失败（无法离线核对）。

别名也要跟：`import importlib as il`、`from importlib import import_module as load`、
赋值别名（`f = importlib.import_module`，可成链）以及字面量取属性
（`getattr(importlib, "import_module")`）都还原成同一条点分路径再判。
`.__call__` 只是「把同一个目标再交出来一次」，还原时剥掉，所以
`f.__call__("pandas")`、`getattr(f, "__call__")("pandas")` 都落回 `f` 本身。

保证范围（边界见 `docs/notes/gates.md`）：静态扫描覆盖 `import` / `import … as` /
`from … import` / 非字面量动态导入 / 赋值别名 / `getattr(<可还原>, "字面量")` /
经 `.__call__` 的调用；不覆盖 `operator.attrgetter`、`functools.partial`、
`eval` / `exec`、运行时拼接属性名等再间接一层的写法。

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
# 允许的第三方：numpy 是计算内核；CBOR 编码库是 IR 的序列化格式；
# contourpy 是等值线 / 等值带的 nums 内核（M2-6 排期定的实现，Pyodide 包索引
# 里有对应轮子，见 docs/notes/gates.md）。
THIRD_PARTY = frozenset({"numpy", "cbor2", "contourpy"})
STDLIB = frozenset(sys.stdlib_module_names) | {"__future__"}

# 动态导入：模块名在字符串里，`import` 扫描看不到，必须单独拦。
# 按「调用目标的顶层模块 + 属性名」判定，这样 `import importlib as il`、
# `import importlib.util`、`from builtins import __import__ as imp` 都是同一个东西。
DYNAMIC_IMPORT_MODULES = frozenset({"importlib", "builtins"})
DYNAMIC_IMPORT_ATTRS = frozenset({"import_module", "__import__"})

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


def local_bindings(tree: ast.AST) -> dict[str, str]:
    """本地名 → 被还原的点分路径，用来解析 `import importlib as il` 这类别名。

    赋值别名同样算：`f = importlib.import_module`、`h = getattr(importlib,
    "import_module")`、以及 `g = f` 这样的链。赋值链的长度事先不知道，按不动点
    迭代（最多“赋值条数 + 1”轮，收敛就停）。
    """
    bound: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            for alias in node.names:
                bound[alias.asname or alias.name] = f"{node.module}.{alias.name}"

    assignments: list[tuple[ast.expr, ast.expr | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            assignments.append((node.targets[0], node.value))
        elif isinstance(node, ast.AnnAssign):
            assignments.append((node.target, node.value))

    for _ in range(len(assignments) + 1):
        changed = False
        for target, value in assignments:
            if not isinstance(target, ast.Name) or value is None:
                continue
            resolved = _resolved_callee(value, bound)
            if resolved is None or bound.get(target.id) == resolved:
                continue
            bound[target.id] = resolved
            changed = True
        if not changed:
            break
    return bound


def _resolved_callee(expr: ast.expr, bound: dict[str, str]) -> str | None:
    """把表达式还原成点分路径。

    认得三种形态：裸名、属性链（`Name.attr` / `a.b.c`）、
    `getattr(<可还原>, "字面量")`。再间接一层就还原不了（例如
    `operator.attrgetter`），那是保证范围之外的已知漏口。

    还原出来的路径先过一遍 `_strip_call_wrappers`：`f.__call__(...)` 与 `f(...)` 是
    同一个目标，归约掉之后别名（`g = f.__call__`）与嵌套 getattr 都一并落回同一条
    路径。
    """
    path = _resolve_path(expr, bound)
    return None if path is None else _strip_call_wrappers(path)


def _resolve_path(expr: ast.expr, bound: dict[str, str]) -> str | None:
    if isinstance(expr, ast.Name):
        return bound.get(expr.id, expr.id)
    if isinstance(expr, ast.Attribute):
        base = _resolve_path(expr.value, bound)
        return None if base is None else f"{base}.{expr.attr}"
    return _getattr_target(expr, bound)


# 只是“把目标本身再交出来一次”的包装属性：`f.__call__` 就是 `f`。
CALL_WRAPPERS = frozenset({"__call__"})


def _strip_call_wrappers(path: str) -> str:
    """剥掉尾部的 `.__call__`（可连成 `f.__call__.__call__`），剥到不动点。"""
    while True:
        head, _, attr = path.rpartition(".")
        if not head or attr not in CALL_WRAPPERS:
            return path
        path = head


def _getattr_target(expr: ast.expr, bound: dict[str, str]) -> str | None:
    """`getattr(<可还原表达式>, "import_module")` → `<路径>.import_module`；否则 None。"""
    if not (isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name)):
        return None
    if expr.func.id != "getattr" or len(expr.args) < 2:
        return None
    attr = expr.args[1]
    if not (isinstance(attr, ast.Constant) and isinstance(attr.value, str)):
        return None
    base = _resolved_callee(expr.args[0], bound)
    if base is None:
        return None
    return f"{base}.{attr.value}"


def _is_dynamic_import(callee: str | None) -> bool:
    """`__import__` / `importlib.import_module` / `builtins.__import__`（含别名）。"""
    if callee is None:
        return False
    if callee == "__import__":  # 内置名，没有 import 语句
        return True
    head, _, attr = callee.rpartition(".")
    in_module = head.split(".")[0] in DYNAMIC_IMPORT_MODULES
    return bool(head) and in_module and attr in DYNAMIC_IMPORT_ATTRS


def dynamic_imports(tree: ast.AST) -> Iterator[tuple[int, str | None]]:
    """产出 (行号, 字面量模块名 或 None=非字面量/取不到)。"""
    bound = local_bindings(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_dynamic_import(_resolved_callee(node.func, bound)):
            continue
        first = node.args[0] if node.args else None
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            yield node.lineno, first.value
        else:
            yield node.lineno, None


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
        for lineno, target in dynamic_imports(tree):
            if target is None:
                problems.append(
                    f"{_display(path)}:{lineno}: dynamic import with a non-literal module "
                    f"name — the whitelist cannot be checked — {HINT}"
                )
                continue
            if target.split(".")[0] in STDLIB | THIRD_PARTY | {SELF}:
                continue
            problems.append(
                f"{_display(path)}:{lineno}: forbidden dynamic import {target!r} — {HINT}"
            )
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

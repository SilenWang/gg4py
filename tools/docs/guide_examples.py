#!/usr/bin/env python
"""执行 `docs/guide/*.md` 里的 Python 代码块（M3-6：文档示例必须能跑）。

用户指南不是散文加「大概这样」的伪代码：每一段 ```python 都是一个**真的程序**。
本工具把每个代码块放在新命名空间里执行一次，cwd 换成临时目录（示例里 `ggsave()`
写出的文件不会落进仓库），再要求它**真的画出一张图**：

- 代码块定义了 `build()`（浏览器编辑器的脚本形状）→ 调用它；返回
  `{"plot": ggplot(...), "size": [...]}` 或 ggplot 对象本身都认；
- 否则找模块级的 `plot` / `p`（`ggcore.plot.ggplot` 实例）；
- 都没有的代码块按「只是表达式 / 一段数据」处理，只要求不抛错。

前两条都继续走 `ggcore.plotspec.build_scene()` + `ggcore.ir.encode()`：只 import
能过、构图期才炸的示例（缺列、未知标度参数、未实现的窗口）同样判红，printed
warning 也会被收集出来。

刻意不执行的片段（讲「别这么写」的对照）在代码块前一行写
`<!-- no-run: 原因 -->`，工具会数进「跳过」并打印出来，不再静默放行。

    pixi run docs:guide          # 跑全部 docs/guide/*.md，逐块打印
    pixi run docs:guide:check    # 同上，只打汇总；挂在 `pixi run check` 里
"""

from __future__ import annotations

import argparse
import contextlib
import io
import re
import sys
import tempfile
import traceback
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

GUIDE_DIR = ROOT / "docs" / "guide"

#: 代码块前一行写这个注释表示「刻意不执行」。
_SKIP = re.compile(r"^<!--\s*no-run\s*:\s*(?P<reason>.*?)\s*-->$")
_FENCE = re.compile(r"^(?P<fence>`{3,})\s*(?P<lang>[A-Za-z0-9_+-]*)\s*$")


@dataclass
class Block:
    """一个代码块：文件、起始行（1 基）、源码、跳过的原因。"""

    path: Path
    line: int
    source: str
    skip: str | None = None
    label: str = ""

    def __str__(self) -> str:
        try:
            where = f"{self.path.relative_to(ROOT)}:{self.line}"
        except ValueError:
            where = f"{self.path}:{self.line}"
        return f"{where} ({self.label})" if self.label else where


@dataclass
class Result:
    block: Block
    ok: bool
    detail: str = ""
    skipped: bool = False
    warnings: list[str] = field(default_factory=list)


def parse_blocks(text: str, path: Path) -> tuple[list[Block], list[tuple[int, str]]]:
    """拆出 ```python 代码块，并返回被跳过的原因。

    第二个返回值是「没有原因就跳过的块」，属于格式错误（防止拿空注释糊弄门禁）。
    """
    blocks: list[Block] = []
    bad_skips: list[tuple[int, str]] = []
    pending_skip: str | None = None
    in_fence = False
    fence = ""
    lang = ""
    start = 0
    body: list[str] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip("\n")
        stripped = line.strip()
        match = _SKIP.match(stripped)
        if match and not in_fence:
            reason = match.group("reason")
            if reason:
                pending_skip = reason
            else:
                bad_skips.append((number, "no-run 注释缺原因"))
                pending_skip = "（缺原因）"
            continue
        if not in_fence:
            opening = _FENCE.match(line)
            if opening:
                in_fence = True
                fence = opening.group("fence")
                lang = opening.group("lang").lower()
                start = number + 1
                body = []
                continue
            if stripped and pending_skip is not None and not stripped.startswith("<!--"):
                # 注释与代码块之间隔了正文：这条跳过说明作废，不替下文背锅。
                pending_skip = None
            continue
        if stripped.startswith(fence) and stripped.strip("`") == "":
            if lang == "python":
                blocks.append(
                    Block(path=path, line=start, source="\n".join(body) + "\n", skip=pending_skip)
                )
            in_fence = False
            pending_skip = None
            continue
        body.append(line)
    return blocks, bad_skips


def _find_plot(namespace: dict[str, Any]) -> tuple[Any, str]:
    """执行完之后图在哪：`build()` → 模块级 `plot` / `p`。"""
    from ggcore.plot import ggplot

    builder = namespace.get("build")
    if callable(builder):
        produced = builder()
        if isinstance(produced, dict):
            return produced, "build() → dict"
        return produced, "build()"
    for name in ("plot", "p"):
        value = namespace.get(name)
        if isinstance(value, ggplot):
            return value, name
    return None, ""


def run_block(block: Block) -> Result:
    """在新命名空间 + 临时 cwd 里跑一个代码块，并检查出图。"""
    from ggcore import ir
    from ggcore.plotspec import build_scene

    namespace: dict[str, Any] = {
        "__name__": "__guide_example__",
        "__file__": str(block.path),
    }
    captured = io.StringIO()
    with tempfile.TemporaryDirectory(prefix="gg4py-guide-") as tmp:
        import os

        os.chdir(tmp)
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
                    exec(compile(block.source, str(block), "exec"), namespace)
                    target, how = _find_plot(namespace)
                    detail = ""
                    if target is not None:
                        spec = target
                        if not isinstance(target, dict):
                            spec = {"plot": target, "size": [5.0, 3.6]}
                        scene = build_scene(spec)
                        data = ir.encode(scene)
                        if not data:
                            raise AssertionError("IR 编码结果为空")
                        detail = f"{how} → {len(data)} 字节 IR"
        except BaseException:  # 文档示例的错误要原样回显给作者
            return Result(block=block, ok=False, detail=traceback.format_exc())
        finally:
            os.chdir(ROOT)
    notes = [f"{w.category.__name__}: {w.message}" for w in caught]
    return Result(block=block, ok=True, detail=detail, warnings=notes)


def collect(paths: list[Path]) -> tuple[list[Block], list[str]]:
    problems: list[str] = []
    blocks: list[Block] = []
    for path in paths:
        found, bad = parse_blocks(path.read_text(encoding="utf-8"), path)
        for number, reason in bad:
            problems.append(f"{path.relative_to(ROOT)}:{number}: {reason}")
        blocks.extend(found)
    return blocks, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="执行 docs/guide/*.md 里的 Python 代码块")
    parser.add_argument("paths", nargs="*", help="只跑这些文件（缺省：docs/guide/*.md）")
    parser.add_argument("--quiet", action="store_true", help="只打汇总与失败块")
    args = parser.parse_args(argv)

    paths = [Path(p) for p in args.paths] or sorted(GUIDE_DIR.glob("*.md"))
    if not paths:
        print(f"没有找到任何文档：{GUIDE_DIR}", file=sys.stderr)
        return 1

    blocks, problems = collect(paths)
    results: list[Result] = []
    for block in blocks:
        if block.skip:
            results.append(Result(block=block, ok=True, skipped=True, detail=block.skip))
            continue
        result = run_block(block)
        results.append(result)
        if not args.quiet or not result.ok:
            mark = "ok  " if result.ok else "FAIL"
            print(f"[{mark}] {block}  {result.detail.splitlines()[0] if result.detail else ''}")

    executed = sum(1 for r in results if not r.skipped)
    skipped = sum(1 for r in results if r.skipped)
    failures = [r for r in results if not r.ok]
    warned = [r for r in results if r.warnings]

    for failure in failures:
        print(f"\n--- {failure.block} ---\n{failure.detail}", file=sys.stderr)
    if not args.quiet:
        for item in warned:
            print(f"\n--- {item.block} 的 warning ---", file=sys.stderr)
            for note in item.warnings:
                print(f"  {note}", file=sys.stderr)

    summary = (
        f"\n{len(paths)} 份文档 / {executed} 个示例执行成功 / {skipped} 个按注释跳过"
        f" / {len(failures)} 个失败 / {len(problems)} 个格式问题"
    )
    if warned:
        summary += f" / {len(warned)} 个示例带 warning（不判红）"
    print(summary)
    for problem in problems:
        print(f"  ! {problem}", file=sys.stderr)
    return 0 if not failures and not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())

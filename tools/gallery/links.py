#!/usr/bin/env python
"""文档 / gallery 链接检查（SIL-828 / M3-7）：示例图与 r-graph-gallery 核对页里的每条链接。

    pixi run docs:links                    # 外链 HEAD/GET 判 200，本地目标判存在
    pixi run docs:links -- --offline       # 只查本地目标（无网 / CI 里用）

任务名是 `docs:links` 而不是 `gallery:check`：后者已归 viewer 的
`tools/viewer/gallery_check.py`（查 `gallery.html` 的卡片链接），两者不是同一份资产。

「gallery」在本仓有两处，脚本各查各的：

| 面 | 来源 | 判据 |
| --- | --- | --- |
| 示例图画廊 | `docs/examples.md`、`README*.md` | 外链 200、本地目标存在、任务存在、资产齐全 |
| 35 图核对页 | `docs/notes/gallery-audit.md` | 文中的 `pixi run …` 任务存在 |

- 示例图画廊：本地目标指 `examples/…`（`plot.py` + `<name>.png` + `<name>.svg`）；
  「任务存在」指文档里写的 `pixi run examples:<name>` 在 `pixi.toml` 里真有；
- 35 图核对页没有外链，图号与三态由 `pixi run audit:gallery` 复核，这里只查命令。

外链检查走 GET（有些站点对 HEAD 返回 405 / 403），带重试：网络抖动会让
r-graph-gallery 偶发 TLS 失败，一次成败不足以判一条链接失效。`--offline` 把外链记成
`skip`，退出码只看本地项。**不挂进 `pixi run check`**：CI 不该因为第三方站点抽风变红；
判据以本脚本的全量输出为准，PR 里贴结果。
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: 「gallery」三个面的文档；顺序就是报告里的顺序。
GALLERY_DOCS = (
    "docs/examples.md",
    "docs/notes/gallery-audit.md",
    "README.md",
    "README.zh-CN.md",
)

EXAMPLES_DIR = "examples"
PIXI_FILE = "pixi.toml"

#: `[文字](目标)` / `![alt](目标)`；目标里不含空白与右括号。
_MD_LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
#: `<https://…>` 自动链接。
_AUTOLINK = re.compile(r"<((?:https?)://[^>\s]+)>")
#: 文档里的 `pixi run <task>`（`-e refs` 这类带参数的写法单独处理，见 `_command_links`）。
_PIXI_RUN = re.compile(r"pixi run (?!-)([a-z][a-z0-9:_\-]*[a-z0-9])")
_USER_AGENT = "gg4py-gallery-check/1.0 (+https://github.com/SilenWang/gg4py)"


@dataclass(frozen=True)
class Item:
    """一条待查的目标。"""

    source: str
    line: int
    target: str
    kind: str  # external / local / command
    detail: str = ""


@dataclass
class Result:
    item: Item
    status: str  # ok / fail / skip
    note: str


# ---------------------------------------------------------------------------
# 收集
# ---------------------------------------------------------------------------


def _rel(path: Path) -> str:
    """仓库内的路径写相对路径；测试里的临时文件就原样写。"""
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def _md_links(path: Path) -> list[Item]:
    items: list[Item] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        for match in _MD_LINK.finditer(line):
            target = match.group(1)
            if target.startswith("#") or target.startswith("mailto:"):
                continue
            kind = "external" if target.startswith(("http://", "https://")) else "local"
            items.append(Item(_rel(path), number, target, kind))
        for match in _AUTOLINK.finditer(line):
            items.append(Item(_rel(path), number, match.group(1), "external"))
    return items


def _load_tasks() -> dict[str, object]:
    """`[tasks]` + 每个 `[feature.<name>.tasks]`：`pixi run` 在任一环境里能找到就算有。"""
    data = tomllib.loads((REPO / PIXI_FILE).read_text(encoding="utf-8"))
    tasks = dict(data.get("tasks", {}))
    for feature in data.get("feature", {}).values():
        tasks.update(feature.get("tasks", {}))
    return tasks


def _command_links(paths: Iterable[Path], tasks: dict[str, object]) -> list[Result]:
    """文档 / 示例脚本里写的 `pixi run <task>` 必须真有这个任务。"""
    results: list[Result] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            for match in _PIXI_RUN.finditer(line):
                task = match.group(1)
                # `pixi run examples:<name>` 是占位写法，不是具体任务名。
                rest = line[match.end() :]
                if rest.startswith(("<", ":<")):
                    continue
                item = Item(_rel(path), number, f"pixi run {task}", "command")
                if task in tasks:
                    results.append(Result(item, "ok", "任务存在"))
                else:
                    results.append(Result(item, "fail", f"`{PIXI_FILE}` 里没有这个任务"))
    return results


def _example_dirs() -> list[Path]:
    root = REPO / EXAMPLES_DIR
    return sorted(path for path in root.iterdir() if path.is_dir()) if root.is_dir() else []


def _example_assets() -> list[Result]:
    """每个 `examples/<name>/` 必须有 plot.py + `<name>.png` + `<name>.svg`。"""
    results: list[Result] = []
    for directory in _example_dirs():
        name = directory.name
        for filename in ("plot.py", f"{name}.png", f"{name}.svg"):
            path = directory / filename
            item = Item(_rel(path), 0, filename, "local")
            results.append(
                Result(
                    item, "ok" if path.is_file() else "fail", "存在" if path.is_file() else "缺失"
                )
            )
    return results


# ---------------------------------------------------------------------------
# 判据
# ---------------------------------------------------------------------------


def _check_local(item: Item) -> Result:
    target = item.target.split("#", 1)[0]
    path = (REPO / item.source).parent / urllib.parse.unquote(target)
    if path.exists():
        suffix = "目录" if path.is_dir() else "文件"
        return Result(item, "ok", suffix)
    return Result(
        item, "fail", f"找不到 {path.relative_to(REPO) if path.is_relative_to(REPO) else path}"
    )


def _fetch(url: str, timeout: float) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read(64)
        return response.status, response.geturl()


def _check_external(item: Item, *, timeout: float, retries: int) -> Result:
    last = ""
    for attempt in range(retries + 1):
        try:
            status, final = _fetch(item.target, timeout)
        except urllib.error.HTTPError as exc:  # 4xx / 5xx
            last = f"HTTP {exc.code}"
            if exc.code < 500:  # 4xx 不是抖动，重试没意义
                break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            reason = getattr(exc, "reason", exc)
            last = f"{type(exc).__name__}: {reason}"
        else:
            if 200 <= status < 300:
                where = "" if final == item.target else f" → {final}"
                return Result(item, "ok", f"{status}{where}")
            last = f"HTTP {status}"
        if attempt < retries:
            time.sleep(1.0 + attempt)
    return Result(item, "fail", last or "无响应")


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------


def _print(results: list[Result]) -> None:
    width = max((len(result.item.target) for result in results), default=10)
    width = min(width, 72)
    for result in results:
        glyph = {"ok": "OK  ", "fail": "FAIL", "skip": "SKIP"}[result.status]
        target = result.item.target
        if len(target) > width:
            target = target[: width - 1] + "…"
        where = (
            f"{result.item.source}:{result.item.line}" if result.item.line else result.item.source
        )
        print(f"{glyph}  {where:<38}  {target:<{width}}  {result.note}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--offline", action="store_true", help="不查外链（记 skip），只看本地目标")
    parser.add_argument("--timeout", type=float, default=20.0, help="单条外链超时（秒，默认 20）")
    parser.add_argument("--retries", type=int, default=2, help="外链重试次数（默认 2）")
    args = parser.parse_args(argv)

    docs = [REPO / name for name in GALLERY_DOCS]
    missing = [_rel(path) for path in docs if not path.is_file()]
    if missing:
        print(f"docs:links: 缺少文档 {', '.join(missing)}", file=sys.stderr)
        return 2

    tasks = _load_tasks()
    links: list[Item] = []
    for path in docs:
        links.extend(_md_links(path))

    results: list[Result] = []
    for item in links:
        if item.kind == "external":
            results.append(
                Result(item, "skip", "offline")
                if args.offline
                else _check_external(item, timeout=args.timeout, retries=args.retries)
            )
        else:
            results.append(_check_local(item))

    # 文档里写的 `pixi run …`：README / 示例页 / 35 图核对页，外加各示例脚本的 docstring。
    command_files = [*docs, *sorted(directory / "plot.py" for directory in _example_dirs())]
    results.extend(_command_links(command_files, tasks))
    results.extend(_example_assets())

    _print(results)

    external = [result for result in results if result.item.kind == "external"]
    local = [result for result in results if result.item.kind == "local"]
    commands = [result for result in results if result.item.kind == "command"]
    failed = [result for result in results if result.status == "fail"]
    live = [result for result in external if result.status == "ok"]
    external_note = f"skip {len(external)}" if args.offline else f"{len(live)}/{len(external)} 200"
    ok_local = sum(result.status == "ok" for result in local)
    ok_commands = sum(result.status == "ok" for result in commands)
    print()
    print(
        f"docs:links: 外链 {external_note} · 本地 {ok_local}/{len(local)}"
        f" · 命令 {ok_commands}/{len(commands)} · 失败 {len(failed)}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

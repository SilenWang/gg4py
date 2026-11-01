"""X2 入口 · 上游 ggplot2 `R/` 的周 diff。

基线是钉死在 `docs/notes/upstream.md` 里的 commit（当前 4.0.3）。脚本列出
`R/` 下相对基线新增/修改/删除的文件，并按接口面（geom/stat/scale/coord/...）
归类，方便判断哪些变更需要跟进。

两种取数方式：
- `--repo-dir PATH`：用本地 clone（离线可用，`git log baseline..ref -- R/`）
- 默认：GitHub compare API，token 取 `GITHUB_TOKEN` / `GH_TOKEN`（未认证也可，
  只是有速率限制）

用法：
    pixi run upstream:diff
    pixi run upstream:diff -- --ref main --output docs/notes/upstream-diff.md
    pixi run upstream:diff -- --repo-dir ../ggplot2
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UPSTREAM_NOTE = REPO / "docs" / "notes" / "upstream.md"
API = "https://api.github.com"

# upstream.md 里的钉死行形如：`- commit: cc1444c10edb87650fbe0cb31d56f0da1a255634`
PIN_RE = re.compile(r"^\s*-\s*commit:\s*([0-9a-f]{40})\b", re.M)

# 把 R/ 下的文件名归到语法分层，报表按层分组。
AREAS: tuple[tuple[str, str], ...] = (
    ("geom", "geom-"),
    ("stat", "stat-"),
    ("scale", "scale-"),
    ("coord", "coord-"),
    ("facet", "facet-"),
    ("guide", "guide"),
    ("annotation", "annotation"),
    ("theme", "theme"),
    ("position", "position"),
)


def read_pin(note: Path = UPSTREAM_NOTE) -> tuple[str, str]:
    """返回 (上游仓库, 基线 commit)，都从 docs/notes/upstream.md 读。"""
    text = note.read_text(encoding="utf-8")
    match = PIN_RE.search(text)
    if not match:
        raise SystemExit(f"upstream:diff: no pinned commit found in {note}")
    repo_match = re.search(r"^\s*-\s*repo:\s*(\S+)", text, re.M)
    repo = repo_match.group(1) if repo_match else "tidyverse/ggplot2"
    return repo, match.group(1)


def area_of(path: str) -> str:
    name = Path(path).name
    for area, prefix in AREAS:
        if name.startswith(prefix):
            return area
    return "core"


def diff_via_git(repo_dir: Path, baseline: str, ref: str) -> list[dict[str, str]]:
    proc = subprocess.run(
        ["git", "-C", str(repo_dir), "diff", "--name-status", f"{baseline}..{ref}", "--", "R/"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"upstream:diff: git diff failed: {proc.stderr.strip()}")
    files = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        status, _, path = line.partition("\t")
        files.append(
            {"filename": path, "status": status.strip(), "additions": "?", "deletions": "?"}
        )
    return files


def _fetch_compare(repo: str, baseline: str, ref: str) -> dict:
    """调 compare API，带重试：大 payload 在这台机器上偶尔会被中途掐断。"""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    url = f"{API}/repos/{repo}/compare/{baseline}...{ref}"
    last_error = ""
    for attempt in range(1, 4):
        request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:  # pragma: no cover - network
            last_error = f"HTTP {exc.code}"
            if exc.code in {401, 403, 404}:  # 认证/仓库不存在：重试没意义
                break
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < 3:
            time.sleep(2 * attempt)
    raise SystemExit(
        f"upstream:diff: compare API failed for {url} ({last_error}).\n"
        "  网络不稳时用离线路径：pixi run upstream:diff -- --repo-dir <local ggplot2 clone>"
    )


def diff_via_api(repo: str, baseline: str, ref: str) -> list[dict[str, str]]:
    payload = _fetch_compare(repo, baseline, ref)

    status_names = {"added": "A", "modified": "M", "removed": "D", "renamed": "R"}
    files = []
    for entry in payload.get("files", []):
        name = entry.get("filename", "")
        if not name.startswith("R/"):
            continue
        files.append(
            {
                "filename": name,
                "status": status_names.get(entry.get("status", ""), "?"),
                "additions": str(entry.get("additions", "?")),
                "deletions": str(entry.get("deletions", "?")),
            }
        )
    return files


def render_report(repo: str, baseline: str, ref: str, files: list[dict[str, str]]) -> str:
    lines = [
        f"# 上游 R/ diff · {repo}@{baseline[:7]}..{ref}",
        "",
        f"- 基线 commit：`{baseline}`",
        f"- 对比 ref：`{ref}`",
        f"- 变更文件：{len(files)}",
        "",
    ]
    if not files:
        lines.append("没有变化。")
        return "\n".join(lines) + "\n"

    grouped: dict[str, list[dict[str, str]]] = {}
    for entry in files:
        grouped.setdefault(area_of(entry["filename"]), []).append(entry)

    for area in sorted(grouped):
        lines.append(f"## {area} ({len(grouped[area])})")
        lines.append("")
        lines.append("| 状态 | 文件 | +/− |")
        lines.append("| --- | --- | --- |")
        for entry in sorted(grouped[area], key=lambda item: item["filename"]):
            lines.append(
                f"| {entry['status']} | `{entry['filename']}` | "
                f"+{entry['additions']}/−{entry['deletions']} |"
            )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="X2: weekly diff of upstream ggplot2 R/.")
    parser.add_argument("--ref", default="main", help="upstream ref to compare to (default: main)")
    parser.add_argument("--repo-dir", type=Path, default=None, help="local ggplot2 clone (offline)")
    parser.add_argument("--note", type=Path, default=UPSTREAM_NOTE, help="file holding the pin")
    parser.add_argument(
        "--output", type=Path, default=None, help="write markdown here instead of stdout"
    )
    args = parser.parse_args(argv)

    repo, baseline = read_pin(args.note)
    if args.repo_dir:
        files = diff_via_git(args.repo_dir, baseline, args.ref)
    else:
        files = diff_via_api(repo, baseline, args.ref)

    report = render_report(repo, baseline, args.ref, files)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(f"upstream:diff: {len(files)} changed file(s) -> {args.output}")
    else:
        print(report, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())

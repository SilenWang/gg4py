#!/usr/bin/env python
"""上游 SVG 快照纳管（SIL-745 / M2-10）。

    pixi run snapshots:fetch     # 按 pin 拉源码包 → 逐个校验 sha256 → .upstream-gg/
    pixi run snapshots:check     # 不动网络：清单 + 处置齐全 + 已纳管 case 与快照同字节
    pixi run snapshots:report    # 输出「总数 / 已纳管 / 通过 / 已知缺口」四列（机读/人读）

## 三个文件

| 文件 | 谁写 | 内容 |
| --- | --- | --- |
| `tools/upstream/snapshot-manifest.json` | `--refresh`（联网） | pin + 路径 / sha256 / 字节数 |
| `tools/upstream/snapshots.toml` | 人 | 每一条的处置：纳管成哪个 case，或哪个 group 的缺口 |
| `docs/notes/snapshot-inventory.md` | 本工具 | 每条快照的处置清单（生成物） |

## 处置规则

- `[snapshots."<path>"] case = "<docs/cases 下的目录名>"`：已复刻，`expected.svg`
  必须与上游快照**逐字节相同**（`snapshots:check` 直接比 sha256）。
- 否则落到 `[groups."<第一段目录名>"]`：`issue` + `reason`。缺一即判红——这就是
  「314 份快照全绿或缺口有明确归口」的机器实现。

## 为什么清单入库、SVG 不入库

清单只有路径 + 摘要（几十 KB），换来「换了 pin 或快照漂移」能被 CI 抓到；SVG 本体
按需拉取（`snapshots:fetch`），处置为 case 的那一份已经作为该 case 的 `expected.svg`
入库——与 `docs/notes/snapshot-policy.md` 的口径一致。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tarfile
import tomllib
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = ROOT / "tools" / "upstream"
MANIFEST = UPSTREAM / "snapshot-manifest.json"
DISPOSITIONS = UPSTREAM / "snapshots.toml"
INVENTORY = ROOT / "docs" / "notes" / "snapshot-inventory.md"
CASES = ROOT / "docs" / "cases"
#: 按需拉取的上游源码（不入库）。
CACHE = ROOT / ".upstream-gg"


def _pin() -> dict[str, str]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["pin"]


def _tarball_url(pin: dict[str, str]) -> str:
    return f"https://github.com/{pin['repo']}/archive/{pin['commit']}.tar.gz"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(*, force: bool = False) -> Path:
    """下载并解压 pin 的源码包，返回解压目录（`_snaps` 的祖先）。"""
    pin = _pin()
    archive = CACHE / f"{pin['commit']}.tar.gz"
    tree = CACHE / f"{pin['repo'].split('/')[-1]}-{pin['commit']}"
    if force or not archive.is_file():
        CACHE.mkdir(parents=True, exist_ok=True)
        print(f"download {_tarball_url(pin)}")
        with urllib.request.urlopen(_tarball_url(pin)) as response:
            archive.write_bytes(response.read())
    if force or not tree.is_dir():
        with tarfile.open(archive, "r:gz") as bundle:
            bundle.extractall(CACHE, filter="data")
    return tree


def list_snapshots(tree: Path) -> list[dict[str, Any]]:
    root = tree / "tests" / "testthat" / "_snaps"
    rows = []
    for path in sorted(root.rglob("*.svg")):
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "category": path.relative_to(root).parts[0],
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    return rows


def refresh() -> int:
    tree = fetch(force=True)
    pin = _pin()
    rows = list_snapshots(tree)
    MANIFEST.write_text(
        json.dumps({"pin": pin, "snapshots": rows}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {MANIFEST.relative_to(ROOT)}: {len(rows)} snapshots")
    return 0


def load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def load_dispositions() -> dict[str, Any]:
    return tomllib.loads(DISPOSITIONS.read_text(encoding="utf-8"))


def resolve(manifest: dict[str, Any], dispositions: dict[str, Any]) -> list[dict[str, Any]]:
    """每条快照 → {path, category, case|None, issue, reason}。"""
    groups = dispositions.get("groups", {})
    overrides = dispositions.get("snapshots", {})
    rows: list[dict[str, Any]] = []
    for entry in manifest["snapshots"]:
        path = entry["path"]
        override = overrides.get(path, {})
        case = override.get("case")
        if case:
            rows.append({**entry, "case": case, "issue": "", "reason": ""})
            continue
        group = groups.get(entry["category"])
        if group is None:
            rows.append(
                {
                    **entry,
                    "case": None,
                    "issue": "",
                    "reason": "",
                    "error": f"分类 {entry['category']!r} 既没有 case，也没有 group 归口",
                }
            )
            continue
        rows.append(
            {
                **entry,
                "case": None,
                "issue": group.get("issue", ""),
                "reason": override.get("reason", group.get("reason", "")),
            }
        )
    return rows


def _expected_diff(case: str, sha256: str) -> str | None:
    expected = CASES / case / "expected.svg"
    if not expected.is_file():
        return f"docs/cases/{case}/expected.svg 不存在"
    digest = _sha256(expected)
    if digest != sha256:
        return f"docs/cases/{case}/expected.svg 与上游快照不同（{digest[:12]} != {sha256[:12]}）"
    return None


def check() -> tuple[list[str], dict[str, Any]]:
    manifest = load_manifest()
    rows = resolve(manifest, load_dispositions())
    problems: list[str] = []
    for row in rows:
        if row.get("error"):
            problems.append(f"{row['path']}: {row['error']}")
            continue
        if row["case"]:
            diff = _expected_diff(row["case"], row["sha256"])
            if diff:
                problems.append(f"{row['path']}: {diff}")
            if not (CASES / row["case"] / "meta.toml").is_file():
                problems.append(f"{row['path']}: docs/cases/{row['case']}/meta.toml 不存在")
            continue
        if not row["issue"]:
            problems.append(f"{row['path']}: 缺口没有 issue 归口")
        if not row["reason"].strip():
            problems.append(f"{row['path']}: 缺口没有原因")
    summary = {
        "total": len(rows),
        "imported": sum(1 for row in rows if row["case"]),
        "gaps": sum(1 for row in rows if not row["case"]),
    }
    return problems, summary


def render_inventory(rows: list[dict[str, Any]], pin: dict[str, str]) -> str:
    imported = [row for row in rows if row["case"]]
    lines = [
        "# 上游 SVG 快照清单（v4.0.3）",
        "",
        "<!-- 生成物：`pixi run snapshots:report`。处置写 `tools/upstream/snapshots.toml`。 -->",
        "",
        f"- 参考实现：`{pin['repo']}` `{pin['tag']}` @ `{pin['commit']}`",
        f"- 快照总数：**{len(rows)}**（上游 `tests/testthat/_snaps/**/*.svg`）",
        f"- 已纳管：**{len(imported)}**（`expected.svg` 与上游快照逐字节相同）",
        f"- 已知缺口：**{len(rows) - len(imported)}**（全部按分类归口，见下表）",
        "",
        "## 已纳管（能自动跑）",
        "",
    ]
    if imported:
        lines.extend(["| 快照 | case |", "| --- | --- |"])
        lines.extend(f"| `{row['path']}` | `{row['case']}` |" for row in imported)
    else:
        lines.append("无。")
    lines.extend(["", "## 已知缺口", ""])
    groups: dict[tuple[str, str], list[str]] = {}
    for row in rows:
        if row["case"]:
            continue
        key = (row["issue"] or "（未归口）", row["reason"] or "（未写原因）")
        groups.setdefault(key, []).append(row["path"])
    for (issue, reason), paths in sorted(groups.items()):
        lines.extend(
            [
                f"### {issue} — {len(paths)} 条",
                "",
                reason,
                "",
                "<details><summary>快照</summary>",
                "",
                *[f"- `{path}`" for path in paths],
                "",
                "</details>",
                "",
            ]
        )
    return "\n".join(lines)


def status() -> dict[str, Any]:
    """给 `cases:matrix` 报告用的四列：总数 / 已纳管 / 通过 / 已知缺口。"""
    manifest = load_manifest()
    rows = resolve(manifest, load_dispositions())
    results = _case_results()
    imported = [row for row in rows if row["case"]]
    passed = sum(1 for row in imported if results.get(row["case"]) == "pass")
    failed = [row["case"] for row in imported if results.get(row["case"]) not in (None, "pass")]
    return {
        "total": len(rows),
        "imported": len(imported),
        "passed": passed,
        "failed": failed,
        "gaps": len(rows) - len(imported),
        "by_category": dict(Counter(row["category"] for row in rows)),
    }


def _case_results() -> dict[str, str]:
    """`cases:matrix` 上一次运行的结果（`--json` 产物），没有就当未知。"""
    path = ROOT / ".cases-matrix" / "report.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {item["case"]: item["status"] for item in payload.get("cases", [])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--fetch", action="store_true", help="按 pin 下载源码包并校验 sha256")
    group.add_argument("--refresh", action="store_true", help="重新生成清单（联网，换 pin 时）")
    group.add_argument(
        "--report", action="store_true", help="重写 docs/notes/snapshot-inventory.md"
    )
    group.add_argument("--json", action="store_true", help="打印 status() 的 JSON")
    args = parser.parse_args(argv)

    if args.refresh:
        return refresh()
    if args.fetch:
        tree = fetch(force=False)
        manifest = load_manifest()
        rows = list_snapshots(tree)
        actual = {row["path"]: row["sha256"] for row in rows}
        problems = [
            f"{entry['path']}: sha256 不匹配"
            for entry in manifest["snapshots"]
            if actual.get(entry["path"]) != entry["sha256"]
        ]
        if problems:
            print("\n".join(problems), file=sys.stderr)
            return 1
        print(f"fetched {len(rows)} snapshots; all sha256 match the manifest")
        return 0
    if args.json:
        print(json.dumps(status(), indent=2))
        return 0

    problems, summary = check()
    rows = resolve(load_manifest(), load_dispositions())
    if args.report:
        INVENTORY.write_text(render_inventory(rows, _pin()), encoding="utf-8")
        print(f"wrote {INVENTORY.relative_to(ROOT)}")
    print(
        f"snapshots total={summary['total']} imported={summary['imported']} gaps={summary['gaps']}"
    )
    if problems:
        for problem in problems:
            print(f"FAIL {problem}", file=sys.stderr)
        return 1
    print("upstream snapshots OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

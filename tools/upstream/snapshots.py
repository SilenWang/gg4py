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

同一个口径还出现在 `docs/cases/matrix.md` 的「上游快照（v4.0.3）」一节
（`cases:matrix` 生成）。四处数字都由 `ledger()` 算一次。

## 处置规则

- `[snapshots."<path>"] case = "<docs/cases 下的目录名>"`：已复刻，`expected.svg`
  必须与上游快照**逐字节相同**（`snapshots:check` 直接比 sha256）。
- 否则落到 `[groups."<第一段目录名>"]`：`issue` + `reason`。缺一即判红——这就是
  「314 份快照全绿或缺口有明确归口」的机器实现。
- 每个 group 还要写 `owner = "m2-closeout" | "m3"`（SIL-786）：`m2-closeout` 是
  「M2 已宣称但没做到对等」的缺口，必须在 M3 开工前归零；`m3` 是真 M3 新能力
  （空间 / 版面组合 / annotate），移交 M3 但不许无主留在台账里。缺 owner 判红。

`--report` 写出的清单里带一张按簇的 burndown 表（上游 / 已纳管 / 缺口）；
`--check-report` 守两件事：清单与处置清单同源（新鲜度），以及三处台账口径一致
（表头按 owner 的合计 = burndown 逐簇相加 = `snapshots.toml` 的 group owner =
`docs/cases/matrix.md` 的同一张数）。口径只由 `ledger()` 算一次，三个文件都从它派生。

owner 是**按簇**声明的：一个簇的缺口只能有一个 owner。单条 `[snapshots]` 的
`owner` 覆盖仍然支持，但它必须与所属簇的 `[groups]` owner 一致，否则
`snapshots:check` / `--check-report` 判红——「最后一条缺口移交 m3 却只改单条」正是
SIL-822 记录的漂移来源（`coord-polar` 的 group owner 停在 `m2-closeout`）。

## 为什么清单入库、SVG 不入库

清单只有路径 + 摘要（几十 KB），换来「换了 pin 或快照漂移」能被 CI 抓到；SVG 本体
按需拉取（`snapshots:fetch`），处置为 case 的那一份已经作为该 case 的 `expected.svg`
入库——与 `docs/notes/snapshot-policy.md` 的口径一致。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
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
#: 案例矩阵里也有一张同一口径的静态表（`pixi run cases:matrix` 生成）。
MATRIX = ROOT / "docs" / "cases" / "matrix.md"
CASES = ROOT / "docs" / "cases"
#: 按需拉取的上游源码（不入库）。
CACHE = ROOT / ".upstream-gg"
#: 缺口归属：M2 收口（SIL-786）或移交 M3。
OWNERS = ("m2-closeout", "m3")


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
    """每条快照 → {path, cluster, case|None, issue, reason, owner, cluster_owner}。

    `owner` 是这一条缺口实际计入的里程碑（单条覆盖优先），`cluster_owner` 是
    `[groups]` 上按簇声明的 owner——两者不一致就是台账漂移，`check()` 判红。
    """
    groups = dispositions.get("groups", {})
    overrides = dispositions.get("snapshots", {})
    rows: list[dict[str, Any]] = []
    for entry in manifest["snapshots"]:
        path = entry["path"]
        override = overrides.get(path, {})
        group = groups.get(entry["category"], {})
        owner = override.get("owner") or group.get("owner", "")
        case = override.get("case")
        row = {
            **entry,
            "cluster": entry["category"],
            "cluster_owner": group.get("owner", ""),
            "case": case,
            "issue": "",
            "reason": "",
            "owner": owner,
        }
        if case:
            rows.append(row)
            continue
        if entry["category"] not in groups:
            row["owner"] = ""
            row["error"] = f"分类 {entry['category']!r} 既没有 case，也没有 group 归口"
            rows.append(row)
            continue
        row["issue"] = group.get("issue", "")
        row["reason"] = override.get("reason", group.get("reason", ""))
        rows.append(row)
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
        if row["owner"] not in OWNERS:
            problems.append(
                f"{row['path']}: 缺口 owner 必须是 {' / '.join(OWNERS)}，收到 {row['owner']!r}"
            )
    problems.extend(_owner_problems(rows))
    summary = {
        "total": len(rows),
        "imported": sum(1 for row in rows if row["case"]),
        "gaps": sum(1 for row in rows if not row["case"]),
    }
    return problems, summary


def _owner_problems(rows: list[dict[str, Any]]) -> list[str]:
    """owner 是按簇的声明：一个簇的缺口只能有一个 owner，且必须写在 `[groups]` 上。"""
    groups = load_dispositions().get("groups", {})
    owners: dict[str, set[str]] = {}
    for row in rows:
        if not row["case"]:
            owners.setdefault(row["cluster"], set()).add(row["owner"])
    problems: list[str] = []
    for cluster, found in sorted(owners.items()):
        if len(found) > 1:
            problems.append(
                f"簇 {cluster!r} 的缺口 owner 不一致（{' / '.join(sorted(found))}）"
                "：单条 owner 必须与 [groups] 的 owner 一致，要移交就改簇"
            )
            continue
        declared = groups.get(cluster, {}).get("owner", "")
        only = next(iter(found))
        if declared != only:
            problems.append(
                f"簇 {cluster!r} 的缺口 owner 是 {only!r}，但 [groups] 里写的是 {declared!r}"
                "（移交时连 group owner 一起改，别只改单条）"
            )
    return problems


def ledger(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """台账的唯一口径：总数 / 已纳管 / 缺口 / 缺口按 owner 的分布。

    `snapshot-inventory.md`、`matrix.md` 与 `--check-report` 都从这里取数，
    三处不允许各算一遍。
    """
    gaps = [row for row in rows if not row["case"]]
    by_owner = dict.fromkeys(OWNERS, 0)
    by_owner.update(Counter(row["owner"] for row in gaps))
    return {
        "total": len(rows),
        "imported": len(rows) - len(gaps),
        "gaps": len(gaps),
        "by_owner": by_owner,
    }


def render_inventory(rows: list[dict[str, Any]], pin: dict[str, str]) -> str:
    imported = [row for row in rows if row["case"]]
    gaps = [row for row in rows if not row["case"]]
    summary = ledger(rows)
    by_owner = summary["by_owner"]
    clusters: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = clusters.setdefault(
            row["cluster"],
            {"declared": row["cluster_owner"], "total": 0, "imported": 0, "owners": Counter()},
        )
        item["total"] += 1
        if row["case"]:
            item["imported"] += 1
        else:
            item["owners"][row["owner"]] += 1
    lines = [
        "# 上游 SVG 快照清单（v4.0.3）",
        "",
        "<!-- 生成物：`pixi run snapshots:report`。处置写 `tools/upstream/snapshots.toml`。 -->",
        "",
        f"- 参考实现：`{pin['repo']}` `{pin['tag']}` @ `{pin['commit']}`",
        f"- 快照总数：**{summary['total']}**（上游 `tests/testthat/_snaps/**/*.svg`）",
        f"- 已纳管：**{summary['imported']}**（`expected.svg` 与上游快照逐字节相同）",
        f"- 已知缺口：**{summary['gaps']}**（全部按分类归口，见下表）",
        f"- 缺口归属：`m2-closeout` **{by_owner['m2-closeout']}** 条（M3 开工前归零）"
        f" / `m3` **{by_owner['m3']}** 条（移交 M3）",
        "",
        "## 按簇 burndown",
        "",
        "| 簇 | owner | 上游 | 已纳管 | 缺口 |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    # owner 列：有缺口的簇写**缺口实际归属**（一个簇只允许一个 owner，由 `check()` 守）；
    # 全已纳管的簇沿用 `[groups]` 上的声明值，仅作归属说明。两处都由 `resolve()`
    # 的同一条数据派生，所以「表头 = 逐簇相加」不是人工维护的巧合。
    table = []
    for name, item in clusters.items():
        gap_total = sum(item["owners"].values())
        if item["owners"]:
            owner_text = " / ".join(sorted(item["owners"]))
        else:
            owner_text = item["declared"] or "—"
        table.append((name, owner_text, item["total"], item["imported"], gap_total))
    for name, owner_text, total, imported_count, gap_total in sorted(
        table, key=lambda item: (-item[4], item[0])
    ):
        lines.append(f"| `{name}` | {owner_text} | {total} | {imported_count} | {gap_total} |")
    lines.extend(
        [
            f"| **合计** | — | {summary['total']} | {summary['imported']} | {summary['gaps']} |",
            "",
            "口径：`m2-closeout` 的簇是「M2 已宣称但没做到对等」的缺口，必须在 M3 开工前清零"
            "（与上游逐字节相同，或落在 2% / 1% 档）；`m3` 的簇移交空间能力 / 版面组合 / "
            "`annotate()`，不在本台账里重复计。",
        ]
    )
    lines.extend(
        [
            "",
            "## 已纳管（能自动跑）",
            "",
        ]
    )
    if imported:
        lines.extend(["| 快照 | case |", "| --- | --- |"])
        lines.extend(f"| `{row['path']}` | `{row['case']}` |" for row in imported)
    else:
        lines.append("无。")
    lines.extend(["", "## 已知缺口", ""])
    groups: dict[tuple[str, str, str, str], list[str]] = {}
    for row in gaps:
        key = (
            row["cluster"],
            row["owner"],
            row["issue"] or "（未归口）",
            row["reason"] or "（未写原因）",
        )
        groups.setdefault(key, []).append(row["path"])
    for (cluster, owner, issue, reason), paths in sorted(groups.items()):
        lines.extend(
            [
                f"### `{cluster}` — {len(paths)} 条 · {issue} · {owner}",
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


def check_report() -> list[str]:
    """三处台账口径一致 + 清单新鲜度（CI 守点，`pixi run snapshots:report:check`）。

    守的不只是「文件没重生成」，而是 SIL-822 那次漂移本身：表头按 owner 的合计、
    burndown 逐簇相加、`snapshots.toml` 的 group owner、`matrix.md` 的同一张数，
    任何一处对不上都判红。
    """
    rows = resolve(load_manifest(), load_dispositions())
    problems: list[str] = []
    if not INVENTORY.is_file():
        problems.append(f"{INVENTORY.relative_to(ROOT)} 不存在")
    else:
        text = INVENTORY.read_text(encoding="utf-8")
        problems.extend(inventory_drift(text, rows))
        if text != render_inventory(rows, _pin()):
            problems.append(
                f"{INVENTORY.relative_to(ROOT)} 与 snapshots.toml 不同源"
                "（跑 `pixi run snapshots:report` 重新生成）"
            )
    if MATRIX.is_file():
        problems.extend(matrix_drift(MATRIX.read_text(encoding="utf-8"), rows))
    else:
        problems.append(f"{MATRIX.relative_to(ROOT)} 不存在")
    return problems


def _section(text: str, start: str, end: str) -> str:
    begin = text.find(start)
    if begin < 0:
        return ""
    begin += len(start)
    stop = text.find(end, begin)
    return text[begin:] if stop < 0 else text[begin:stop]


#: burndown 表的一行：`| 簇 | owner | 上游 | 已纳管 | 缺口 |`（合计行没有反引号）。
_INVENTORY_ROW = re.compile(
    r"^\| `(?P<cluster>[^`]+)` \| (?P<owner>[^|]+?) \| "
    r"(?P<total>\d+) \| (?P<imported>\d+) \| (?P<gaps>\d+) \|$",
    re.MULTILINE,
)
#: `matrix.md` 的上游快照表：总数 / 已纳管 / 缺口 / m2-closeout / m3。
_MATRIX_ROW = re.compile(r"^\| (\d+) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \|$", re.MULTILINE)


def inventory_drift(text: str, rows: list[dict[str, Any]]) -> list[str]:
    """清单自身的三处口径：表头合计、逐簇相加、`snapshots.toml` 的 group owner。"""
    problems: list[str] = []
    summary = ledger(rows)
    expected: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = expected.setdefault(
            row["cluster"],
            {"declared": row["cluster_owner"], "total": 0, "imported": 0, "owners": Counter()},
        )
        item["total"] += 1
        if row["case"]:
            item["imported"] += 1
        else:
            item["owners"][row["owner"]] += 1

    header = re.search(
        r"缺口归属：.*?`m2-closeout` \*\*(\d+)\*\*.*?`m3` \*\*(\d+)\*\*",
        text,
    )
    if header is None:
        problems.append("清单里找不到「缺口归属」表头，无法核对口径")
    table = [
        (
            match["cluster"],
            match["owner"].strip(),
            *(int(match[key]) for key in ("total", "imported", "gaps")),
        )
        for match in _INVENTORY_ROW.finditer(_section(text, "## 按簇 burndown", "## 已纳管"))
    ]
    if not table:
        problems.append("清单里找不到「按簇 burndown」表，无法核对口径")
        return problems

    seen = {name for name, *_ in table}
    for name in sorted(set(expected) - seen):
        problems.append(f"burndown 表缺了簇 `{name}`")
    for name, owner, total, imported, gaps in table:
        item = expected.get(name)
        if item is None:
            problems.append(f"burndown 表里的 `{name}` 不在台账里")
            continue
        want = (item["total"], item["imported"], sum(item["owners"].values()))
        if (total, imported, gaps) != want:
            problems.append(
                f"`{name}` 一行是 {total}/{imported}/{gaps}（上游 / 已纳管 / 缺口），"
                f"台账算出来是 {want[0]}/{want[1]}/{want[2]}"
            )
        want_owner = (
            " / ".join(sorted(item["owners"])) if item["owners"] else item["declared"] or "—"
        )
        if owner != want_owner:
            problems.append(
                f"`{name}` 的 burndown owner 写的是 {owner!r}，台账解析出来是 {want_owner!r}"
            )

    table_m2 = sum(gaps for _, owner, _, _, gaps in table if owner == "m2-closeout")
    table_m3 = sum(gaps for _, owner, _, _, gaps in table if owner == "m3")
    if header is not None:
        head_m2, head_m3 = int(header.group(1)), int(header.group(2))
        if (head_m2, head_m3) != (table_m2, table_m3):
            problems.append(
                f"表头写 `m2-closeout` {head_m2} / `m3` {head_m3}，"
                f"但 burndown 逐簇相加是 {table_m2} / {table_m3}"
            )
        counts = summary["by_owner"]
        if (head_m2, head_m3) != (counts["m2-closeout"], counts["m3"]):
            problems.append(
                f"表头写 `m2-closeout` {head_m2} / `m3` {head_m3}，"
                f"但按 snapshots.toml 逐条解析是 {counts['m2-closeout']} / {counts['m3']}"
            )

    groups = load_dispositions().get("groups", {})
    for name, item in sorted(expected.items()):
        if not item["owners"]:
            continue
        declared = groups.get(name, {}).get("owner", "")
        found = " / ".join(sorted(item["owners"]))
        if declared != found:
            problems.append(
                f'`{name}` 的缺口归 {found!r}，但 `[groups."{name}"]` 的 owner 是 '
                f"{declared!r}（owner 按簇声明：移交时连 group owner 一起改）"
            )
    return problems


def matrix_drift(text: str, rows: list[dict[str, Any]]) -> list[str]:
    """`docs/cases/matrix.md` 的上游快照表是否与台账同一口径。"""
    summary = ledger(rows)
    want = (
        summary["total"],
        summary["imported"],
        summary["gaps"],
        summary["by_owner"]["m2-closeout"],
        summary["by_owner"]["m3"],
    )
    begin = text.find("## 上游快照（v4.0.3）")
    if begin < 0:
        return [
            "docs/cases/matrix.md 缺少「上游快照（v4.0.3）」一节"
            "（跑 `pixi run cases:matrix --no-run` 重新生成）"
        ]
    stop = text.find("\n## ", begin + 1)
    section = text[begin:] if stop < 0 else text[begin:stop]
    match = _MATRIX_ROW.search(section)
    if match is None:
        return ["docs/cases/matrix.md 的「上游快照（v4.0.3）」一节里找不到数字行"]
    got = tuple(int(value) for value in match.groups())
    if got != want:
        return [
            f"docs/cases/matrix.md 的上游快照表是 {got}"
            f"（总数 / 已纳管 / 缺口 / m2-closeout / m3），台账算出来是 {want}"
        ]
    return []


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
    group.add_argument(
        "--check-report",
        action="store_true",
        help="只校验 docs/notes/snapshot-inventory.md 是否最新（CI 用）",
    )
    group.add_argument("--json", action="store_true", help="打印 status() 的 JSON")
    args = parser.parse_args(argv)

    if args.check_report:
        problems = check_report()
        for problem in problems:
            print(f"FAIL {problem}", file=sys.stderr)
        return 1 if problems else 0
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

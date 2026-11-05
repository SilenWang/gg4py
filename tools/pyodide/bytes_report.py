#!/usr/bin/env python
"""SIL-830 · 首屏字节账：`web/runtime/vendor/manifest.json` 的审计与回归护栏。

    pixi run pyodide:bytes          # 打印首屏 / 总量、逐文件的原始与线上字节
    pixi run pyodide:bytes:check    # 挂在 `pixi run check` 里：预算与压缩覆盖

为什么单开一个任务：首访预算是**字节**的预算（9 Mbps 下 9.49 MB 就是 8.4 s），而
字节最容易在无人察觉的情况下变胖——加一个资产、换一个构建、少压一个文件，数字都
不会自己报警。这里把「首屏要哪些文件」和「它们必须被预压缩」写成断言，跟
`api:coverage:check` / `snapshots:check` 一个路子。

判据：

* 首屏文件（`BOOT_FILES`）每个都必须是 `br`（或小到不值得压，< 32 KiB）；
* 首屏线上字节 ≤ `BOOT_BUDGET_BYTES`（当前 6.49 MB，留 0.5 MB 余量）；
* `manifest.total_bytes` 里每个 > 64 KiB 的文件都要么是 `br`、要么是已知的
  「压不动」（wheel 是 zip、stdlib 是 zip 的兄弟），名单显式列出来——新增一个大
  文件时必须在这里写一句理由，跟阈值分档的规矩一致。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
VENDOR = REPO / "web" / "runtime" / "vendor"
MANIFEST = VENDOR / "manifest.json"

#: 首屏（boot 到「运行时可用」）要的文件：运行时核心 + 源码包。
BOOT_FILES = (
    "pyodide/pyodide.mjs",
    "pyodide/pyodide.asm.mjs",
    "pyodide/pyodide.asm.wasm",
    "pyodide/python_stdlib.zip",
    "pyodide/pyodide-lock.json",
    "gg4py.tar",
)
#: 首屏线上字节预算（SIL-830 实测 6,493,469；留 0.5 MB 给运行时的小版本漂移）。
BOOT_BUDGET_BYTES = 7_000_000
#: 小于这个尺寸不值得压（多一个请求、省不到几百字节）。
MIN_COMPRESS_BYTES = 32 * 1024
#: 压不动的已知文件：wheel 本身就是 zip（再套 brotli 赚不到 2%，见 stage_assets.py）。
#: 名单是显式的：新增一个大文件而不进名单，`:check` 会红——逼着写一句理由。
KNOWN_UNCOMPRESSED = ("pyodide/pyodide.js",)


def _known_uncompressed(name: str) -> bool:
    return name.endswith(".whl") or name.startswith(KNOWN_UNCOMPRESSED)


def load_manifest(path: Path = MANIFEST) -> dict:
    if not path.is_file():
        raise SystemExit(f"{path} 不存在 —— 先跑 `pixi run pyodide:assets`")
    return json.loads(path.read_text(encoding="utf-8"))


def entries(manifest: dict) -> dict[str, dict]:
    """文件名 → 记账（`files` 里是逐个运行时文件，源码包单独一项）。"""
    table = {entry["file"]: entry for entry in manifest["files"]}
    archive = manifest["archive"]
    table[archive["file"]] = archive
    return table


def audit(manifest: dict) -> tuple[list[str], dict]:
    problems: list[str] = []
    table = entries(manifest)
    boot = [(name, table[name]) for name in BOOT_FILES if name in table]
    missing = [name for name in BOOT_FILES if name not in table]
    if missing:
        problems.append(f"首屏文件不在 manifest 里：{missing}")

    for name, entry in boot:
        if entry["bytes"] < MIN_COMPRESS_BYTES:
            continue
        if entry.get("encoding") != "br":
            problems.append(f"首屏文件没有预压缩：{name}（{entry['bytes']:,d} B）")

    for name, entry in table.items():
        if entry["bytes"] < MIN_COMPRESS_BYTES or entry.get("encoding") == "br":
            continue
        if _known_uncompressed(name):
            continue
        problems.append(
            f"{name}（{entry['bytes']:,d} B）没压也不在 KNOWN_UNCOMPRESSED 名单里："
            "要么让它压，要么在这里写一句为什么压不动"
        )

    boot_wire = sum(entry["wire_bytes"] for _, entry in boot)
    if boot_wire > BOOT_BUDGET_BYTES:
        problems.append(
            f"首屏线上字节 {boot_wire:,d} B 超过预算 {BOOT_BUDGET_BYTES:,d} B"
            "（预算按 Fast 4G 9 Mbps 推：每 MB ≈ 0.9 s）"
        )
    totals = {
        "boot_bytes": sum(entry["bytes"] for _, entry in boot),
        "boot_wire_bytes": boot_wire,
        "total_bytes": manifest["total_bytes"],
        "wire_bytes": manifest["wire_bytes"],
        "budget": BOOT_BUDGET_BYTES,
        "files": len(table),
    }
    return problems, totals


def print_table(manifest: dict) -> None:
    table = entries(manifest)
    print(f"{'原始字节':>12} {'线上字节':>12} {'编码':>4}  文件")
    for name in BOOT_FILES:
        entry = table.get(name)
        if entry is None:
            print(f"{'-':>12} {'-':>12} {'-':>4}  {name}（缺）")
            continue
        print(
            f"{entry['bytes']:>12,d} {entry['wire_bytes']:>12,d} "
            f"{entry.get('encoding') or '-':>4}  {name}"
        )
    print(f"{'-' * 12} {'-' * 12} {'-' * 4}  (首屏合计见下)")
    problems, totals = audit(manifest)
    print()
    print(f"首屏原始 : {totals['boot_bytes']:>12,d} B")
    print(f"首屏线上 : {totals['boot_wire_bytes']:>12,d} B（预算 {totals['budget']:,d}）")
    print(f"全部原始 : {totals['total_bytes']:>12,d} B")
    print(f"全部线上 : {totals['wire_bytes']:>12,d} B")
    print(f"文件数   : {totals['files']:>12,d}")
    print(f"brotli   : {manifest.get('encoding', {})}")
    for problem in problems:
        print(f"  - {problem}")
    print("result    : " + ("FAIL" if problems else "ok"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="首屏字节账（manifest 审计）。")
    parser.add_argument("--check", action="store_true", help="只判红绿，不打印明细")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    args = parser.parse_args(argv)

    manifest = load_manifest(args.manifest)
    if args.check:
        problems, totals = audit(manifest)
        for problem in problems:
            print(f"  - {problem}")
        print(
            f"pyodide:bytes:check {'FAIL' if problems else 'ok'} — "
            f"首屏线上 {totals['boot_wire_bytes']:,d} / {totals['budget']:,d} B"
        )
        return 0 if not problems else 1
    print_table(manifest)
    problems, _totals = audit(manifest)
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())

"""M0-10 门禁 · 同一份 plot → IR，CPython 与 Pyodide 逐字节一致。

两边跑的是同一个入口 `tools/gates/pyodide/run_ir.py`、同一份 `plot.json`：

    CPython : cbor2（C 扩展）         → .gate-pyodide/cpython.ir
    Pyodide : ggcore.ir._cbor（纯 Python）→ .gate-pyodide/pyodide.ir

两个 CBOR 实现不同，字节必须相同——这才是「内核能进浏览器」的证据。门禁只跑
node（不需要浏览器），见 `docs/notes/pyodide.md`。

用法：
    pixi run gate:pyodide                  # 正片：差异为空才绿
    pixi run gate:pyodide:selftest         # 负向自测：故意差 1 字节，门禁必须红

退出码：0 = 判定通过；1 = 判定失败（有差异 / 该红没红）；2 = 环境不完整。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HARNESS = REPO / "tools" / "gates" / "pyodide"
RUNNER = HARNESS / "run_ir.py"
NODE_RUNNER = HARNESS / "run_ir.mjs"
SRC = REPO / "src"
ASSETS = REPO / "docs" / "spike" / "e1_coldstart" / "static" / "pyodide"
DEFAULT_OUT = REPO / ".gate-pyodide"

#: 负向自测翻转的字节位置；node 侧按文件长度取模，小文件也安全。
DEFAULT_INJECT_OFFSET = 512


def first_diff(left: bytes, right: bytes) -> int | None:
    """第一个不同的字节下标；长度不同时取较短那侧的长度。"""
    for index, (a, b) in enumerate(zip(left, right, strict=False)):
        if a != b:
            return index
    return None if len(left) == len(right) else min(len(left), len(right))


def window(data: bytes, offset: int, radius: int = 12) -> str:
    start = max(0, offset - radius)
    chunk = data[start : offset + radius]
    return f"@{start:04x} {chunk.hex(' ')}"


def run_cpython(out_dir: Path) -> tuple[bytes, bytes, dict]:
    """返回 (plot 产出的 IR, 边角取值 IR, 元数据)。"""
    out = out_dir / "cpython.ir"
    meta_path = out_dir / "cpython.json"
    env = dict(os.environ)
    paths = [str(SRC)] + [part for part in env.get("PYTHONPATH", "").split(os.pathsep) if part]
    env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(paths))
    subprocess.run(
        [sys.executable, str(RUNNER), "--out", str(out), "--meta", str(meta_path)],
        check=True,
        env=env,
        cwd=REPO,
    )
    return (
        out.read_bytes(),
        out.with_name(out.name + ".edge").read_bytes(),
        json.loads(meta_path.read_text(encoding="utf-8")),
    )


def run_pyodide(out_dir: Path, inject_offset: int | None) -> tuple[bytes, bytes, dict]:
    node = shutil.which("node")
    if node is None:
        raise SystemExit("gate:pyodide: `node` 不在 PATH 上（应该由 pixi 提供 nodejs）")
    out = out_dir / "pyodide.ir"
    meta_path = out_dir / "pyodide.json"
    command = [
        node,
        str(NODE_RUNNER),
        "--out",
        str(out),
        "--meta",
        str(meta_path),
    ]
    if inject_offset is not None:
        command += ["--inject-diff", str(inject_offset)]
    subprocess.run(command, check=True, cwd=REPO)
    return (
        out.read_bytes(),
        out.with_name(out.name + ".edge").read_bytes(),
        json.loads(meta_path.read_text(encoding="utf-8")),
    )


def require_assets() -> None:
    if not (ASSETS / "pyodide.mjs").is_file() or not any(ASSETS.glob("numpy-*.whl")):
        raise SystemExit(
            "gate:pyodide: Pyodide 资产不完整 —— 先跑 `pixi run spike:e1:assets`"
            "（`pixi run gate:pyodide` 已把它列为 depends-on）"
        )


def describe(meta: dict) -> str:
    parts = [
        meta["runtime"],
        f"python {meta['python']}",
        f"numpy {meta['numpy']}",
        f"cbor {meta['cbor_backend']}",
    ]
    if meta.get("pyodide"):
        parts.append(f"pyodide {meta['pyodide']}")
    if meta.get("total_ms") is not None:
        parts.append(f"boot {meta['boot_ms']} ms + numpy {meta['numpy_load_ms']} ms")
    return ", ".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="X? Pyodide smoke: plot -> IR byte equality.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--inject-diff",
        type=int,
        default=None,
        help="负向自测：让 Pyodide 侧产出的第 N 个字节翻一位",
    )
    parser.add_argument(
        "--expect-diff",
        action="store_true",
        help="负向自测的判定口径：这次必须比对失败（门禁红）才算通过",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Pyodide 侧跑几次（每次都要过），并报告加载耗时中位数（M3-9 基线）",
    )
    args = parser.parse_args(argv)
    if args.expect_diff and args.inject_diff is None:
        args.inject_diff = DEFAULT_INJECT_OFFSET

    require_assets()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    cpython_bytes, cpython_edge, cpython_meta = run_cpython(out_dir)
    if cpython_meta["cbor_backend"] != "cbor2":
        # 两边必须真的用了不同的 CBOR 实现；否则“一致”只是同一个实现跑了两遍。
        print(
            "gate:pyodide: CPython 侧没有用上 cbor2 —— 比较失去意义"
            f"（backend={cpython_meta['cbor_backend']}）",
            file=sys.stderr,
        )
        return 2
    print(f"  cpython : {describe(cpython_meta)}")

    runs: list[dict] = []
    bad_run: int | None = None
    bad_edge_run: int | None = None
    for attempt in range(max(1, args.repeat)):
        pyodide_bytes, pyodide_edge, pyodide_meta = run_pyodide(out_dir, args.inject_diff)
        runs.append(pyodide_meta)
        if pyodide_meta["cbor_backend"] == "cbor2":
            print(
                "gate:pyodide: Pyodide 侧居然用上了 cbor2，负向前提变了，请复核",
                file=sys.stderr,
            )
            return 2
        if attempt == 0:
            print(f"  pyodide : {describe(pyodide_meta)}")
        offset = first_diff(cpython_bytes, pyodide_bytes)
        if offset is not None:
            bad_run = attempt
            print(f"  diff    : run {attempt + 1} first differs at byte {offset}")
            print(f"    cpython: {window(cpython_bytes, offset)}")
            print(f"    pyodide: {window(pyodide_bytes, offset)}")
            break
        # 边角取值矩阵（NaN 位型 / ±Inf / -0.0 / 64 位 int 上界，SIL-646）同样要比：
        # 一份「正常」scene 的字节相同，证明不了这些边角两边写得一样。
        edge_offset = first_diff(cpython_edge, pyodide_edge)
        if edge_offset is not None:
            bad_edge_run = attempt
            print(f"  edge    : run {attempt + 1} first differs at byte {edge_offset}")
            print(f"    cpython: {window(cpython_edge, edge_offset)}")
            print(f"    pyodide: {window(pyodide_edge, edge_offset)}")
            break

    sizes = sorted({meta["ir_bytes"] for meta in runs})
    edge_sizes = sorted({meta["edge_bytes"] for meta in runs})
    identical = (
        bad_run is None
        and bad_edge_run is None
        and sizes == [len(cpython_bytes)]
        and edge_sizes == [len(cpython_edge)]
    )
    print(
        f"  ir      : {len(cpython_bytes)} B (cpython) / {sizes[0]} B (pyodide), "
        f"sha256 {hashlib.sha256(cpython_bytes).hexdigest()[:16]}…"
    )
    print(
        f"  edge ir : {len(cpython_edge)} B (cpython) / {edge_sizes[0]} B (pyodide), "
        f"sha256 {hashlib.sha256(cpython_edge).hexdigest()[:16]}… "
        f"(NaN / ±Inf / -0.0 缓冲 + int {2**64 - 1} 参数)"
    )
    if identical:
        print("  diff    : none")

    if len(runs) > 1:
        median = statistics.median
        print(
            "  timing  : "
            f"median boot {median(m['boot_ms'] for m in runs):.0f} ms, "
            f"numpy {median(m['numpy_load_ms'] for m in runs):.0f} ms, "
            f"script {median(m['run_ms'] for m in runs):.0f} ms, "
            f"total {median(m['total_ms'] for m in runs):.0f} ms "
            f"({len(runs)} runs)"
        )

    if args.expect_diff:
        if identical:
            print(
                "gate:pyodide:selftest FAIL — 注入的 1 字节差异没有被发现，门禁是瞎的",
                file=sys.stderr,
            )
            return 1
        print("gate:pyodide:selftest ok — 注入的 1 字节差异被判定为红（负向对照成立）")
        return 0

    if identical:
        print("gate:pyodide: ok — CPython 与 Pyodide 的 IR 字节完全一致")
        return 0

    print(
        "gate:pyodide: FAIL — CPython 与 Pyodide 的 IR 字节不一致"
        f"（第一个差异在 byte {offset}，见 .gate-pyodide/）",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())

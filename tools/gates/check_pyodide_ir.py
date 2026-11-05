"""M0-10 / SIL-824 门禁 · 同一份代码，CPython 与 Pyodide 逐字节一致。

两个相位，各跑一遍两端：

1. **冒烟**（M0-10）：同一份 plot → IR，CPython 走 cbor2、Pyodide 走
   `ggcore.ir._cbor`，字节必须相同；另有边角取值 scene（NaN 位型 / ±Inf / -0.0 /
   64 位 int 上界）与等值线（contourpy）产物。
2. **全量 case**（SIL-824）：`docs/cases/*/plot.py` 全部在两端各跑一遍
   `build_scene()` + `encode()`，逐条比 IR 的 sha256 与字节数——这是「ggcore
   全量在 Pyodide 跑通」的证据，不再是 plot→IR 冒烟。

    CPython : cbor2（C 扩展）            → .gate-pyodide/cpython-cases.json
    Pyodide : ggcore.ir._cbor（纯 Python）→ .gate-pyodide/pyodide-cases.json

两端都用 `ggcore.metrics.fallback.TableMetrics` 量文字（浏览器里没有 skia /
HarfBuzz，宽度只能来自兜底表），所以比的是同一份版式 + 同一份几何。

用例：
    pixi run gate:pyodide                  # 正片：两个相位都必须无差异
    pixi run gate:pyodide:selftest         # 负向自测：每个相位都故意差一位，门禁必须红

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
CASES_RUNNER = HARNESS / "run_cases.py"
CASES_NODE_RUNNER = HARNESS / "run_cases.mjs"
CASES = REPO / "docs" / "cases"
SRC = REPO / "src"
ASSETS = REPO / "docs" / "spike" / "e1_coldstart" / "static" / "pyodide"
DEFAULT_OUT = REPO / ".gate-pyodide"

#: 负向自测翻转的字节位置；node 侧按文件长度取模，小文件也安全。
DEFAULT_INJECT_OFFSET = 512
#: 负向自测翻转摘要的 case：任取一条，摘要改一个字符即可（不必真跑一遍全长 case）。
DEFAULT_INJECT_CASE = "geom-point-basic"


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


def run_cases_cpython(out_dir: Path) -> dict:
    """CPython 侧：全量 case → IR 摘要（不写 IR 本体，见 `run_cases.py`）。"""
    out = out_dir / "cpython-cases.json"
    env = dict(os.environ)
    paths = [str(SRC)] + [part for part in env.get("PYTHONPATH", "").split(os.pathsep) if part]
    env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(paths))
    subprocess.run(
        [sys.executable, str(CASES_RUNNER), "--out", str(out), "--cases", str(CASES)],
        check=True,
        env=env,
        cwd=REPO,
    )
    return json.loads(out.read_text(encoding="utf-8"))


def run_cases_pyodide(out_dir: Path, inject_case: str | None) -> dict:
    node = shutil.which("node")
    if node is None:
        raise SystemExit("gate:pyodide: `node` 不在 PATH 上（应该由 pixi 提供 nodejs）")
    out = out_dir / "pyodide-cases.json"
    command = [node, str(CASES_NODE_RUNNER), "--out", str(out)]
    if inject_case is not None:
        command += ["--inject-case", inject_case]
    subprocess.run(command, check=True, cwd=REPO)
    return json.loads(out.read_text(encoding="utf-8"))


def aggregate_digest(report: dict) -> str:
    """`(case, sha256)` 排序后拼起来的摘要：报告里给一行「全量一起」的指纹。"""
    digest = hashlib.sha256()
    for name in sorted(report["cases"]):
        digest.update(name.encode())
        digest.update(report["cases"][name]["sha256"].encode())
        digest.update(b"\x00")
    return digest.hexdigest()


def compare_cases(cpython: dict, pyodide: dict, *, limit: int = 20) -> tuple[bool, list[str]]:
    """逐条比两端摘要；返回 (是否完全一致, 差异说明)。"""
    problems: list[str] = []
    left = cpython["cases"]
    right = pyodide["cases"]
    for name in sorted(set(left) - set(right)):
        problems.append(f"{name}: CPython 有、Pyodide 没有")
    for name in sorted(set(right) - set(left)):
        problems.append(f"{name}: Pyodide 有、CPython 没有")
    for name in sorted(set(left) & set(right)):
        a = left[name]
        b = right[name]
        if a["sha256"] != b["sha256"] or a["bytes"] != b["bytes"]:
            problems.append(
                f"{name}: IR 不同（cpython {a['bytes']} B {a['sha256'][:16]}… / "
                f"pyodide {b['bytes']} B {b['sha256'][:16]}…）"
            )
    # 失败的 case 两端必须一致地失败：一端算出 scene、另一端抛异常，同样是差异。
    for name in sorted(set(cpython["failed"]) - set(pyodide["failed"])):
        problems.append(f"{name}: 只有 CPython 侧失败 —— {cpython['failed'][name]}")
    for name in sorted(set(pyodide["failed"]) - set(cpython["failed"])):
        problems.append(f"{name}: 只有 Pyodide 侧失败 —— {pyodide['failed'][name]}")
    if cpython["metrics"] != pyodide["metrics"]:
        problems.append(
            f"度量实现不同：{cpython['metrics']} / {pyodide['metrics']}（比的是两套版式）"
        )
    return (not problems), problems[:limit]


def require_assets() -> None:
    if (
        not (ASSETS / "pyodide.mjs").is_file()
        or not any(ASSETS.glob("numpy-*.whl"))
        # M2-6 / SIL-758：等值线冒烟要 contourpy 的 wasm 轮子，缺了就别假装跑过。
        or not any(ASSETS.glob("contourpy-*.whl"))
    ):
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
    if meta.get("contourpy"):
        parts.append(f"contourpy {meta['contourpy']}")
    if meta.get("pyodide"):
        parts.append(f"pyodide {meta['pyodide']}")
    if meta.get("total_ms") is not None:
        parts.append(f"boot {meta['boot_ms']} ms + numpy {meta['numpy_load_ms']} ms")
    return ", ".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="X? Pyodide gate: IR byte equality.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--inject-diff",
        type=int,
        default=None,
        help="负向自测：让 Pyodide 侧产出的第 N 个字节翻一位",
    )
    parser.add_argument(
        "--inject-case",
        default=None,
        help="负向自测：把这条 case 的全量摘要改一个字符（默认取 --expect-diff 时的一条）",
    )
    parser.add_argument(
        "--expect-diff",
        action="store_true",
        help="负向自测的判定口径：这次每个相位都必须比对失败（门禁红）才算通过",
    )
    parser.add_argument(
        "--no-cases",
        action="store_true",
        help="只跑冒烟相位（调试用；正式判定必须全量）",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Pyodide 侧冒烟跑几次（每次都要过），并报告加载耗时中位数（M3-9 基线）",
    )
    args = parser.parse_args(argv)
    if args.expect_diff:
        if args.inject_diff is None:
            args.inject_diff = DEFAULT_INJECT_OFFSET
        if args.inject_case is None and not args.no_cases:
            args.inject_case = DEFAULT_INJECT_CASE

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
    # M2-6 / SIL-758：等值线（contourpy）的产物也要比——IR 字节一致只证明了编码器，
    # 证明不了「浏览器里画出来的等值线和桌面端是同一份几何」。版本同样要一致：
    # 两边跑不同 contourpy 的「一致」没有意义（pixi.toml 的 <1.4 就是为此）。
    contour_versions = sorted({meta["contourpy"] for meta in runs})
    contour_same = contour_versions == [cpython_meta["contourpy"]] and all(
        meta["contour"] == cpython_meta["contour"]
        and meta["contour_filled"] == cpython_meta["contour_filled"]
        for meta in runs
    )
    smoke_identical = (
        bad_run is None
        and bad_edge_run is None
        and contour_same
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
    print(
        f"  contour : stat_contour {cpython_meta['contour']['rows']} rows sha256 "
        f"{cpython_meta['contour']['sha256'][:16]}…, stat_contour_filled "
        f"{cpython_meta['contour_filled']['rows']} rows sha256 "
        f"{cpython_meta['contour_filled']['sha256'][:16]}…"
        f" (contourpy {cpython_meta['contourpy']})"
    )
    if not contour_same:
        print(
            "  contour diff: "
            f"contourpy {cpython_meta['contourpy']} (cpython) / "
            f"{', '.join(contour_versions)} (pyodide)；"
            f"contour {sorted({meta['contour']['sha256'][:16] for meta in runs})}，"
            f"filled {sorted({meta['contour_filled']['sha256'][:16] for meta in runs})}",
            file=sys.stderr,
        )
    if smoke_identical:
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

    cases_identical: bool | None = None
    if not args.no_cases:
        cpython_cases = run_cases_cpython(out_dir)
        pyodide_cases = run_cases_pyodide(out_dir, args.inject_case)
        cases_identical, problems = compare_cases(cpython_cases, pyodide_cases)
        total = len(cpython_cases["cases"]) + len(cpython_cases["failed"])
        print(
            f"  cases   : {len(cpython_cases['cases'])}/{total} built, "
            f"{len(cpython_cases['failed'])} failed, "
            f"{cpython_cases['total_bytes']} B IR, "
            f"sha256 {aggregate_digest(cpython_cases)[:16]}… "
            f"({cpython_cases['metrics']}, pyodide {pyodide_cases['run_ms']:.0f} ms)"
        )
        if not cases_identical:
            for problem in problems:
                print(f"    case diff: {problem}", file=sys.stderr)

    red = (not smoke_identical) or cases_identical is False
    if args.expect_diff:
        if not red:
            print(
                "gate:pyodide:selftest FAIL — 注入的差异没有被发现，门禁是瞎的",
                file=sys.stderr,
            )
            return 1
        if cases_identical is not None and cases_identical:
            # 冒烟相位红了但全量相位没红：说明逐条比较这一段是瞎的。
            print(
                "gate:pyodide:selftest FAIL — 注入的 case 摘要差异没有被发现",
                file=sys.stderr,
            )
            return 1
        print("gate:pyodide:selftest ok — 注入的差异被判定为红（负向对照成立）")
        return 0

    if smoke_identical and cases_identical is not False:
        scope = (
            "IR 字节完全一致"
            if cases_identical is None
            else f"冒烟 + {len(pyodide_cases['cases'])} 条 case 的 IR 字节完全一致"
        )
        print(f"gate:pyodide: ok — CPython 与 Pyodide 的 {scope}")
        return 0

    if not smoke_identical and bad_run is None and bad_edge_run is None and not contour_same:
        print(
            "gate:pyodide: FAIL — 等值线（contourpy）产物在两端不一致，见上面的 contour diff",
            file=sys.stderr,
        )
        return 1

    if not smoke_identical:
        print(
            "gate:pyodide: FAIL — CPython 与 Pyodide 的冒烟 IR 字节不一致"
            f"（第一个差异在 byte {offset}，见 .gate-pyodide/）",
            file=sys.stderr,
        )
        return 1

    print(
        "gate:pyodide: FAIL — 有 case 的两端 IR 不一致"
        f"（{len(problems)} 条，见上面的 case diff 与 .gate-pyodide/）",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())

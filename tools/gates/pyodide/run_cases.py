"""SIL-824 · 案例库**全量**过一遍 ggcore，写出每条 case 的 IR 摘要。

与 `run_ir.py` 同一套路：这个文件被两个运行时执行，输入相同、代码相同，只有
CBOR 实现与 numpy 版本不同（CPython: cbor2 + numpy 2.5；Pyodide: `ggcore.ir._cbor`
+ numpy 2.4）。`check_pyodide_ir.py` 逐条比摘要，任何一条不同即判红。

    CPython : PYTHONPATH=src pixi run python tools/gates/pyodide/run_cases.py --out a.json
    Pyodide : pixi run node tools/gates/pyodide/run_cases.mjs --out b.json

一条 case 的链路与生产一致（`docs/cases/README.md` 的三文件约定）：

    docs/cases/<name>/plot.py → ggcore.plotspec.load_plot() → build_scene() → ggcore.ir.encode()

**度量用哪一份**：`ggcore.metrics.fallback.TableMetrics`（兜底度量表），不是
`ggskia.text.ShaperMetrics`。浏览器里没有 skia / HarfBuzz，宽度只能来自表；门禁
两侧必须用同一个 `Metrics` 实现，否则「一致」比的是两份不同的版式。这也顺带把
表路径（run 切分 / kerning / advance 换算）拉进了逐字节门禁。

摘要写进一个 JSON（不写 4.5 MB 的 IR 本体）：`sha256` + 字节数 + 节点数。字节
不同时 `sha256` 必然不同，而 500 多条 case 的 IR 全量搬过 node 边界没有收益；
需要定位具体字节时用 `--case <name>` 单独写一份 IR。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import warnings
from pathlib import Path
from typing import Any

import numpy as np

from ggcore import ir
from ggcore.metrics.fallback import default_metrics
from ggcore.plotspec import PlotSpecError, build_scene, load_plot

HERE = Path(__file__).resolve().parent
#: 仓库根：CPython 侧从脚本位置推出；Pyodide 侧由 `run_cases.mjs` 把同一棵树挂在
#: `/app`（`GG_REPO` 环境变量可覆盖，两侧都不硬编码 `/app`）。
REPO = Path(__file__).resolve().parents[3]
CASES = REPO / "docs" / "cases"
PLOT_FILE = "plot.py"


def runtime_name() -> str:
    return "pyodide" if sys.platform == "emscripten" else "cpython"


def case_dirs(root: Path) -> list[Path]:
    """`docs/cases/<name>/plot.py` 的目录，按名字排序（两端同一份顺序）。"""
    return sorted(
        (path for path in root.iterdir() if (path / PLOT_FILE).is_file()),
        key=lambda path: path.name,
    )


def digest_scene(scene: ir.Scene) -> tuple[str, int, int]:
    data = ir.encode(scene)
    nodes = sum(1 for _ in ir.walk(scene.root))
    return hashlib.sha256(data).hexdigest(), len(data), nodes


def run_cases(root: Path, *, only: str | None = None) -> dict[str, Any]:
    metrics = default_metrics()
    entries: dict[str, Any] = {}
    failed: dict[str, str] = {}
    total_bytes = 0
    started = time.perf_counter()
    for directory in case_dirs(root):
        if only is not None and directory.name != only:
            continue
        case_started = time.perf_counter()
        try:
            scene = build_scene(load_plot(directory), metrics=metrics)
            digest, size, nodes = digest_scene(scene)
        except PlotSpecError as exc:
            failed[directory.name] = f"PlotSpecError: {exc}"
            continue
        except Exception as exc:
            failed[directory.name] = f"{type(exc).__name__}: {exc}"
            continue
        entries[directory.name] = {
            "sha256": digest,
            "bytes": size,
            "nodes": nodes,
            "ms": round((time.perf_counter() - case_started) * 1000.0, 3),
        }
        total_bytes += size
    return {
        "runtime": runtime_name(),
        "python": ".".join(str(part) for part in sys.version_info[:3]),
        "numpy": np.__version__,
        "cbor_backend": ir.CBOR_BACKEND,
        "metrics": type(metrics).__name__,
        "cases": entries,
        "failed": failed,
        "total_bytes": total_bytes,
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="docs/cases 全量 → IR 摘要（一个运行时）。")
    parser.add_argument("--out", type=Path, required=True, help="摘要 JSON 写到哪")
    parser.add_argument("--cases", type=Path, default=CASES, help="案例库根目录")
    parser.add_argument("--case", default=None, help="只跑一条（定位差异时用）")
    parser.add_argument(
        "--ir",
        type=Path,
        default=None,
        help="配合 --case：把这条例的 IR 字节也写出来（默认只写摘要）",
    )
    args = parser.parse_args(argv)

    # 案例里的 warning（`Removed N rows` 等）不影响字节，但会把 500 多条输出淹掉。
    warnings.simplefilter("ignore")
    report = run_cases(args.cases, only=args.case)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    if args.case and args.ir is not None:
        scene = build_scene(load_plot(args.cases / args.case), metrics=default_metrics())
        args.ir.parent.mkdir(parents=True, exist_ok=True)
        args.ir.write_bytes(ir.encode(scene))

    print(
        f"{report['runtime']}: {len(report['cases'])} cases, {len(report['failed'])} failed, "
        f"{report['total_bytes']} B, {report['elapsed_ms']:.0f} ms, "
        f"backend={report['cbor_backend']} metrics={report['metrics']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

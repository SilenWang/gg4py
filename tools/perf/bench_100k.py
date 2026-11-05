"""M3-5 · 10 万点端到端实测（降采样 / 度量缓存 / 增量重算）。

「端到端」的口径与浏览器编辑器同一条路：

    run_script(source) = exec 用户代码 → ggplot → build_plot → scene_from_plot
                         → ir.encode

也就是 `web/runtime/worker.js` 在 Pyodide 里跑的那一段（含 IR 字节，不含 TS 渲染与
页面合成）。度量固定用 `ggcore.metrics.fallback.default_metrics()`（TableMetrics），
与浏览器一致；桌面 skia 的 `ShaperMetrics` 不在这条路上。

三组数字：

* **cold**：`clear_caches()` 之后跑一遍（真实首跑：几何 + 版式 + 遍历 + 编码）；
* **warm**：同一段代码再跑一遍（内容没变 → 图层绘制与指令缓存命中）；
* **sampled**：`geom_point(max_points=N)` 的同一份数据（降采样打开）。

用法::

    pixi run perf:100k                       # 默认 10 万点，cold / warm / sampled
    pixi run perf:100k --rows 1000000        # 换行数
    pixi run perf:100k --check 300           # 预算判定：cold 中位数必须 < 300 ms
    pixi run perf:100k --no-cache            # 关掉缓存（前后对比的「前」）
    pixi run perf:100k --json                # 机器可读

退出码：0 = 跑完（或预算通过）；1 = `--check` 超预算。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import warnings
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from ggcore import perf  # noqa: E402
from ggcore.script import run_script  # noqa: E402

#: 10 万点是本任务的验收规模（父任务 M3-5）。
DEFAULT_ROWS = 100_000
#: 实测取中位数；runner 的 CPU 会抖，单次最小值容易太乐观。
DEFAULT_RUNS = 5
#: 降采样那一组的预算：留出 5 倍的余量给 Pyodide（浏览器里比 CPython 慢）。
DEFAULT_MAX_POINTS = 20_000

SOURCE = """
import numpy as np
from ggcore.plot import aes, geom_point, ggplot
from ggio.frame import to_column_table

needs = ["numpy"]

rng = np.random.default_rng(20261105)
DATA = {{
    "x": rng.normal(size={rows}),
    "y": rng.normal(size={rows}),
}}


def build():
    return {{
        "plot": ggplot(to_column_table(DATA), aes(x="x", y="y")) + geom_point({params}),
        "size": [5.0, 3.5],
    }}
"""


def source_for(rows: int, *, max_points: int | None = None) -> str:
    params = "" if max_points is None else f"max_points={max_points}"
    return SOURCE.format(rows=rows, params=params)


def _run_once(source: str) -> dict:
    started = time.perf_counter()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", perf.DownsampleWarning)
        result = run_script(source)
    elapsed = (time.perf_counter() - started) * 1000.0
    return {
        "ms": elapsed,
        "build_ms": result.meta["build_ms"],
        "encode_ms": result.meta["encode_ms"],
        "bytes": result.meta["bytes"],
        "nodes": result.meta["nodes"],
        "digest": result.meta["digest"],
    }


def measure(source: str, runs: int, *, fresh: bool) -> dict:
    samples: list[dict] = []
    for _ in range(runs):
        if fresh:
            perf.clear_caches()
        samples.append(_run_once(source))
    times = [item["ms"] for item in samples]
    return {
        "runs": runs,
        "min_ms": round(min(times), 1),
        "median_ms": round(statistics.median(times), 1),
        "max_ms": round(max(times), 1),
        "bytes": samples[-1]["bytes"],
        "nodes": samples[-1]["nodes"],
        "digest": samples[-1]["digest"],
        "build_ms": round(statistics.median([item["build_ms"] for item in samples]), 1),
        "encode_ms": round(statistics.median([item["encode_ms"] for item in samples]), 1),
        "caches": perf.cache_stats(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M3-5 · 10 万点端到端实测")
    parser.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--max-points", type=int, default=DEFAULT_MAX_POINTS)
    parser.add_argument("--no-cache", action="store_true", help="关掉增量重算缓存（对比用）")
    parser.add_argument("--check", type=float, default=None, help="cold 中位数预算（ms）")
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    args = parser.parse_args(argv)

    if args.no_cache:
        perf.disable_scene_cache()
    perf.clear_caches()

    plain = source_for(args.rows)
    sampled = source_for(args.rows, max_points=args.max_points)

    cold = measure(plain, args.runs, fresh=True)
    warm = measure(plain, args.runs, fresh=False)
    downsample = measure(sampled, args.runs, fresh=True)

    report = {
        "rows": args.rows,
        "runs": args.runs,
        "cache_enabled": perf.cache_stats()["enabled"],
        "end_to_end": "run_script: exec + build_plot + scene_from_plot + ir.encode",
        "cold": cold,
        "warm": warm,
        "sampled": {**downsample, "max_points": args.max_points},
    }
    if args.json:
        print(json.dumps(report, indent=1, sort_keys=True))
    else:
        _print_report(report)

    if args.check is not None and cold["median_ms"] >= args.check:
        print(
            f"FAIL: cold 中位数 {cold['median_ms']} ms ≥ 预算 {args.check:g} ms",
            file=sys.stderr,
        )
        return 1
    return 0


def _print_report(report: dict) -> None:
    rows = report["rows"]
    print(f"M3-5 · {rows:,} 点 · 缓存 {'on' if report['cache_enabled'] else 'off'}")
    print(f"  口径：{report['end_to_end']}")
    for label, key in (("cold ", "cold"), ("warm ", "warm"), ("sample", "sampled")):
        item = report[key]
        extra = f"  max_points={item['max_points']:,}" if key == "sampled" else ""
        print(
            f"  {label}: median {item['median_ms']:7.1f} ms "
            f"(min {item['min_ms']:6.1f} / max {item['max_ms']:6.1f})"
            f"  build {item['build_ms']:6.1f} + encode {item['encode_ms']:4.1f}"
            f"  {item['bytes'] / 1024:7.0f} KiB  {item['nodes']} nodes{extra}"
        )
    stats = report["warm"]["caches"]
    scene = stats["scene"]
    layers = stats["layers"]
    print(
        f"  warm 缓存命中：场景指令 {scene['hits']} / {scene['misses']}"
        f"（{scene['hit_rate']:.0%}），图层绘制 {layers['hits']} / {layers['misses']}"
        f"（{layers['hit_rate']:.0%}）"
    )


if __name__ == "__main__":
    raise SystemExit(main())

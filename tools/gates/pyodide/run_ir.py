"""M0-10 · 同一份 plot → IR，同一种运行时里跑一次，写出字节与元数据。

这个文件**同时**被两个运行时执行：

    CPython : PYTHONPATH=src pixi run python tools/gates/pyodide/run_ir.py --out a.ir
    Pyodide : pixi run node tools/gates/pyodide/run_ir.mjs --out b.ir

两边写出的字节由 `tools/gates/check_pyodide_ir.py` 逐字节比较。脚本自己不打印
IR（走文件），stdout 只留一行摘要，便于在 node 里读。

退出码：0 = 产出 + 解码回环都通过；1 = 产出失败。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

import mini_plot
import numpy as np

from ggcore.ir import CBOR_BACKEND, IR_VERSION_STR, decode, encode, scene_equal

HERE = Path(__file__).resolve().parent


def runtime_name() -> str:
    return "pyodide" if sys.platform == "emscripten" else "cpython"


def cbor2_version() -> str | None:
    if CBOR_BACKEND != "cbor2":
        return None
    from importlib.metadata import version

    try:
        return version("cbor2")
    except Exception:  # 发行包元数据在 Pyodide 里不存在，这里只在 CPython 侧调用
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="plot.json -> IR bytes, one runtime.")
    parser.add_argument("--out", type=Path, required=True, help="IR 字节写到哪")
    parser.add_argument("--meta", type=Path, default=None, help="运行时元数据（JSON）")
    parser.add_argument("--plot", type=Path, default=mini_plot.PLOT, help="plot 定义")
    args = parser.parse_args(argv)

    started = time.perf_counter()
    spec = mini_plot.load(args.plot)
    build_start = time.perf_counter()
    scene = mini_plot.build(spec)
    build_ms = (time.perf_counter() - build_start) * 1000.0

    encode_start = time.perf_counter()
    data = encode(scene)
    encode_ms = (time.perf_counter() - encode_start) * 1000.0

    # 回环：解码回 scene 必须与编码前逐位相同（浏览器端读 IR 走的也是这条路径）。
    roundtrip = scene_equal(decode(data), scene)
    total_ms = (time.perf_counter() - started) * 1000.0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(data)

    meta = {
        "runtime": runtime_name(),
        "python": ".".join(str(part) for part in sys.version_info[:3]),
        "platform": sys.platform,
        "machine": platform.machine(),
        "numpy": np.__version__,
        "cbor_backend": CBOR_BACKEND,
        "cbor2": cbor2_version(),
        "ir_version": IR_VERSION_STR,
        "ir_bytes": len(data),
        "ir_sha256": hashlib.sha256(data).hexdigest(),
        "build_ms": round(build_ms, 3),
        "encode_ms": round(encode_ms, 3),
        "script_ms": round(total_ms, 3),
        "roundtrip": roundtrip,
    }
    if args.meta is not None:
        args.meta.parent.mkdir(parents=True, exist_ok=True)
        args.meta.write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    digest = meta["ir_sha256"][:16]
    print(f"{meta['runtime']}: {len(data)} B sha256={digest} backend={CBOR_BACKEND}")
    return 0 if roundtrip else 1


if __name__ == "__main__":
    sys.exit(main())

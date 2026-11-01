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

from ggcore.ir import (
    CBOR_BACKEND,
    INT_MAX,
    IR_VERSION_STR,
    BlobTable,
    Node,
    NodeKind,
    Scene,
    decode,
    encode,
    f32,
    scene_equal,
)

HERE = Path(__file__).resolve().parent


def runtime_name() -> str:
    return "pyodide" if sys.platform == "emscripten" else "cpython"


def edge_scene() -> Scene:
    """线格式里最容易让两个实现写出不同字节的取值（SIL-646）。

    - f32 缓冲里放 NaN 的全部位型（正/负 quiet、带 payload）、±Inf、-0.0：这些值
      在线格式里是原始 float32 字节（byte string），两侧必须写出同一串字面字节、
      且 decode 回来的位型不变。NaN 作为 **CBOR 浮点**时的归一化（`f97e00`）由
      `gate:cbor` 守——IR 的浮点参数本身仍须有限，NaN 只出现在缓冲里；
    - `int` 参数取 64 位上界 `INT_MAX`：再大就要 bignum tag，而线格式不写 tag，
      所以上界是格式的一部分（`ggcore.ir.nodes.INT_MIN/INT_MAX`）。

    这份 scene 与 `plot.json` 那份一起过门禁：CPython 写得出来，Pyodide 就必须
    写得出同样的字节，并且解得回来。
    """
    bit_patterns = np.array(
        [
            [0x7FC00000, 0xFFC00000],  # 正 / 负 quiet NaN
            [0x7F800001, 0x7F800000],  # signaling NaN（payload 非零）/ +Inf
            [0xFF800000, 0x80000000],  # -Inf / -0.0
        ],
        dtype=np.uint32,
    )
    points = f32(bit_patterns.view(np.float32).copy())
    blobs, bid = BlobTable.empty().add(b"\x89PNG\r\n\x1a\n", "image/png")
    return Scene(
        root=Node(
            NodeKind.VIEWPORT,
            params={"clip": False},
            children=(
                Node(
                    NodeKind.POINTS,
                    params={"pch": INT_MAX, "size": 1.0},
                    bufs={"points": points},
                ),
                Node(
                    NodeKind.RASTER,
                    params={"blob": bid, "width": INT_MAX, "height": 1},
                    bufs={"rect": f32([[0.0, 0.0, 1.0, 1.0]])},
                ),
            ),
        ),
        blobs=blobs,
    )


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

    # 第二份：取值矩阵的边角（NaN 位型 / ±Inf / -0.0 / 64 位 int 上界）。
    edge = edge_scene()
    edge_data = encode(edge)
    edge_roundtrip = scene_equal(decode(edge_data), edge)
    edge_path = args.out.with_name(args.out.name + ".edge")
    edge_path.write_bytes(edge_data)

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
        "edge_bytes": len(edge_data),
        "edge_sha256": hashlib.sha256(edge_data).hexdigest(),
        "edge_roundtrip": edge_roundtrip,
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
    return 0 if roundtrip and edge_roundtrip else 1


if __name__ == "__main__":
    sys.exit(main())

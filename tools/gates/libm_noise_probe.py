"""SIL-884：把「某条 case 在 libm 噪声下漂移」摊到具体节点的具体字节上。

    pixi run python tools/gates/libm_noise_probe.py \
        --case upstream-geom-sf-north-carolina-county-boundaries-with-more-than-one-arrow

对每条 case：先用 baseline 编一份 IR，再在 `up` / `down` / `mixed` 三种噪声下各编
一份；sha256 不同就把两份 IR 解码成 `Scene` 逐节点、逐字段、逐缓冲元素 diff，
打印「第几个节点、哪个字段、哪一侧的值」。

它是排查工具，不进 `gate:libm-noise` 的判据：门禁只回答「漂没漂」，这个脚本回答
「漂在哪个顶点上」。CI 上漂、本机不漂时，把它的输出贴进 issue/PR 就能对拍。

    --fingerprint  顺带打印几组 libm 取值（`cos(0)` 与各断点的 `log10`）的十六进制，
                   用来对比两台机器的 libm 末位（glibc 版本不同时先看这里）。
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools" / "gates"))

import libm_noise  # noqa: E402

from ggcore import ir  # noqa: E402
from ggcore.metrics.fallback import default_metrics  # noqa: E402
from ggcore.plotspec import build_scene, load_plot  # noqa: E402

CASES = REPO / "docs" / "cases"

#: 与 ggplot2 的断点对拍时实际用到的几组输入（见 `docs/cases/.../plot.py`）。
FINGERPRINT_LOG10 = (81.8, 81.7, 36.25, 36.55, 0.09185, 0.06526666666666732)


def build_ir(case: Path) -> bytes:
    scene = build_scene(load_plot(case), metrics=default_metrics())
    return ir.encode(scene)


def diff_case(name: str, mode: str, seed: int, limit: int = 8) -> list[str]:
    """一条 case 在 `mode` 噪声下与 baseline 的逐节点差异（最多 `limit` 行）。

    `check_libm_noise.py` 判红时用它把「漂在哪个顶点」直接打进 CI 日志——门禁
    在另一台机器上红、本机复制不出来时，日志本身就是可复核的定位材料。
    """
    case = CASES / name
    baseline_bytes = build_ir(case)
    with libm_noise.libm_noise(mode, seed=seed):
        noisy_bytes = build_ir(case)
    if baseline_bytes == noisy_bytes:
        return []
    differences = diff_scene(ir.decode(baseline_bytes), ir.decode(noisy_bytes))
    return differences[:limit]


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value!r} ({value.hex()})"
    return repr(value)


def _diff_buffers(where: str, a: np.ndarray, b: np.ndarray, out: list[str]) -> None:
    if a.dtype != b.dtype or a.shape != b.shape:
        out.append(f"{where}: 形状/dtype 不同 {a.shape}/{a.dtype} vs {b.shape}/{b.dtype}")
        return
    if a.tobytes() == b.tobytes():
        return
    flat_a, flat_b = a.ravel(), b.ravel()
    moved = np.flatnonzero(flat_a.view(np.uint8) != flat_b.view(np.uint8))
    # 按元素归组（float32 = 4 字节 / int32 = 4 字节）
    indices = sorted({int(index) // a.itemsize for index in moved})
    for index in indices[:20]:
        out.append(f"{where}[{index}]: {_fmt(float(flat_a[index]))} → {_fmt(float(flat_b[index]))}")
    if len(indices) > 20:
        out.append(f"{where}: … 还有 {len(indices) - 20} 个元素")


def diff_scene(a: ir.Scene, b: ir.Scene) -> list[str]:
    out: list[str] = []
    if a.size != b.size:
        out.append(f"scene.size: {a.size} → {b.size}")
    if a.dpi != b.dpi:
        out.append(f"scene.dpi: {a.dpi} → {b.dpi}")

    nodes_a = list(ir.walk(a.root))
    nodes_b = list(ir.walk(b.root))
    if len(nodes_a) != len(nodes_b):
        out.append(f"节点数: {len(nodes_a)} → {len(nodes_b)}")
    for index, (node_a, node_b) in enumerate(zip(nodes_a, nodes_b, strict=False)):
        where = f"#{index}<{node_a.kind}>"
        if node_a.kind != node_b.kind:
            out.append(f"{where}: kind {node_a.kind} → {node_b.kind}")
            continue
        if node_a.texts != node_b.texts:
            changed = [
                (old, new)
                for old, new in zip(node_a.texts, node_b.texts, strict=False)
                if old != new
            ]
            out.append(f"{where}.texts: {changed[:5]}")
        for name in sorted(set(node_a.params) | set(node_b.params)):
            value_a = node_a.params.get(name)
            value_b = node_b.params.get(name)
            if isinstance(value_a, float) and isinstance(value_b, float):
                if value_a.hex() != value_b.hex():
                    out.append(f"{where}.params[{name}]: {_fmt(value_a)} → {_fmt(value_b)}")
            elif value_a != value_b:
                out.append(f"{where}.params[{name}]: {value_a!r} → {value_b!r}")
        for name in sorted(set(node_a.bufs) | set(node_b.bufs)):
            if name not in node_a.bufs or name not in node_b.bufs:
                out.append(f"{where}.bufs[{name}]: 只在一侧存在")
                continue
            _diff_buffers(f"{where}.bufs[{name}]", node_a.bufs[name], node_b.bufs[name], out)
        if node_a.gpar != node_b.gpar:
            out.append(f"{where}.gpar: {node_a.gpar} → {node_b.gpar}")
    return out


def fingerprint() -> None:
    try:
        glibc = subprocess.run(
            ["ldd", "--version"], capture_output=True, text=True, check=False
        ).stdout.splitlines()[0]
    except OSError:
        glibc = "（没有 ldd）"
    print(f"  glibc   : {glibc}")
    print(f"  numpy   : {np.__version__} · python {sys.version.split()[0]}")
    print(f"  cos(0.0): {math_cos0().hex()}  sin(0.0): {math_sin0().hex()}")
    for value in FINGERPRINT_LOG10:
        print(f"  log10({value!r}) = {math_log10(value).hex()}")


def math_cos0() -> float:
    import math

    return math.cos(0.0)


def math_sin0() -> float:
    import math

    return math.sin(0.0)


def math_log10(value: float) -> float:
    import math

    return math.log10(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="定位一条 case 在 libm 噪声下漂移的字节。")
    parser.add_argument("--case", required=True, help="docs/cases 下的目录名")
    parser.add_argument("--seed", type=int, default=7, help="mixed 模式的种子（低 3 位有效）")
    parser.add_argument("--limit", type=int, default=60, help="最多打印多少处差异")
    parser.add_argument("--fingerprint", action="store_true", help="打印 libm 取值指纹")
    args = parser.parse_args(argv)

    case = CASES / args.case
    if not (case / "plot.py").is_file():
        print(f"找不到 case：{case}", file=sys.stderr)
        return 2

    warnings.simplefilter("ignore")
    if args.fingerprint:
        fingerprint()

    baseline_bytes = build_ir(case)
    baseline = hashlib.sha256(baseline_bytes).hexdigest()
    print(f"  baseline: {baseline}")
    interactions = 0
    for mode in libm_noise.MODES:
        with libm_noise.libm_noise(mode, seed=args.seed):
            noisy_bytes = build_ir(case)
        noisy = hashlib.sha256(noisy_bytes).hexdigest()
        if noisy == baseline:
            print(f"  {mode:6s}: 一致")
            continue
        interactions += 1
        print(f"  {mode:6s}: 漂移 {noisy}")
        differences = diff_scene(ir.decode(baseline_bytes), ir.decode(noisy_bytes))
        print(f"    {len(differences)} 处差异：")
        for line in differences[: args.limit]:
            print(f"      {line}")
    return 1 if interactions else 0


if __name__ == "__main__":
    sys.exit(main())

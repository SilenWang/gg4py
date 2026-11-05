"""SIL-824 返工 · IR 的逐字节确定性不能依赖宿主 `libm`。

    pixi run gate:libm-noise

`gate:pyodide` 比的是「同一台机器上的 CPython 与 Pyodide」；这一道比的是
「**另一台机器**的 CPython」：把 `math` / `numpy` 的三角与指数函数整体偏移
±1 ULP（见 `tools/gates/libm_noise.py`），再把 `docs/cases` 全量跑一遍。任何一条
case 的 IR sha256 变了，就说明它的字节里还留着 libm 的末位噪声——在换一台
runner 之后就会变成 CI 红（2026-11-05 那 3 条 `coord_sf` 就是这样漂的）。

三种噪声各跑一遍，全部逐条相同才算绿：

| 模式 | 含义 |
| --- | --- |
| `up` | 所有取值朝 +∞ 偏 1 ULP（上界，比真实差异更狠） |
| `down` | 所有取值朝 -∞ 偏 1 ULP |
| `mixed` | 方向由取值的位模式决定（贴近真实：只有部分取值差 1 ULP，且可复现） |

退出码：0 = 三种噪声下逐条相同；1 = 有 case 漂移；2 = 环境不完整。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools" / "gates"))
sys.path.insert(0, str(REPO / "tools" / "gates" / "pyodide"))

import libm_noise  # noqa: E402
import run_cases  # noqa: E402

CASES = REPO / "docs" / "cases"
MODES = libm_noise.MODES


def digests() -> dict[str, str]:
    """全量 case 的 IR 摘要（与 `gate:pyodide` 的 CPython 侧同一份实现）。"""
    report = run_cases.run_cases(CASES)
    if report["failed"]:
        for name, error in sorted(report["failed"].items()):
            print(f"  构建失败 {name}: {error}", file=sys.stderr)
        raise SystemExit("gate:libm-noise: 有 case 构建不出来，先修它再谈确定性")
    return {name: entry["sha256"] for name, entry in report["cases"].items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="IR 在宿主 libm 噪声下必须逐条不变。")
    parser.add_argument("--seed", type=int, default=7, help="mixed 模式里翻转方向的位")
    parser.add_argument("--limit", type=int, default=10, help="每档最多列出的漂移 case 数")
    args = parser.parse_args(argv)

    if not CASES.is_dir():
        print(f"gate:libm-noise: 找不到案例库 {CASES}", file=sys.stderr)
        return 2

    baseline = digests()
    print(f"  baseline : {len(baseline)} case(s)")
    drifted: dict[str, list[str]] = {}
    noisy_by_mode: dict[str, dict[str, str]] = {}
    for mode in MODES:
        with libm_noise.libm_noise(mode, seed=args.seed):
            noisy = digests()
        noisy_by_mode[mode] = noisy
        changed = sorted(name for name in baseline if baseline[name] != noisy.get(name))
        drifted[mode] = changed
        print(f"  libm {mode:6s}: {len(changed)} drifted")

    total = sum(len(names) for names in drifted.values())
    if total == 0:
        print("gate:libm-noise: ok — 三种 libm 噪声下 515 条 case 的 IR 逐条相同")
        return 0

    for mode, names in drifted.items():
        for name in names[: args.limit]:
            other = noisy_by_mode[mode].get(name, "（缺失）")
            print(
                f"  {mode}: {name}  {baseline[name][:16]}… / {other[:16]}…",
                file=sys.stderr,
            )
        if len(names) > args.limit:
            print(f"  {mode}: … 还有 {len(names) - args.limit} 条", file=sys.stderr)
    print(
        f"gate:libm-noise: FAIL — {total} 处漂移：IR 里还有宿主 libm 的末位噪声，"
        "换一台机器（glibc / CPU 不同）就会变成 gate:pyodide 红",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())

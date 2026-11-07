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

`mixed` 的 `--seed` 只有低 3 位参与（`seed & 7`），即 seed 空间是 8 个等价类；
0–7 各是一份不同的噪声，8 与 0 逐位相同。证据是
`pixi run gate:libm-noise:seeds` 打印的 sha256 表（SIL-864）。

负向对照：

    pixi run gate:libm-noise:selftest   # = 本脚本 --expect-diff

把 libm 输出整体放大 1e-4（`libm_noise.libm_bias()`，远超 IR 的量化网格），
断言**至少有一条 case 漂移**。否则说明这道门看得不是字节，绿是假的。

退出码：0 = 三种噪声下逐条相同；1 = 有 case 漂移；2 = 环境不完整。
`--expect-diff` 上是 0 = 确实漂了（门禁有效）；1 = 一处都没漂（门禁失效）。
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
import libm_noise_probe  # noqa: E402
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


def drifted(baseline: dict[str, str], noisy: dict[str, str]) -> list[str]:
    return sorted(name for name in baseline if baseline[name] != noisy.get(name))


def expect_diff(args: argparse.Namespace) -> int:
    """负向对照：粗噪声必须让门禁判红，否则这道门形同虚设。"""
    baseline = digests()
    with libm_noise.libm_bias():
        biased = digests()
    changed = drifted(baseline, biased)
    print(f"  baseline : {len(baseline)} case(s)")
    print(f"  libm bias: {len(changed)} drifted（期望 > 0）")
    if not changed:
        print(
            "gate:libm-noise:selftest FAIL — 放大 1e-4 的 libm 偏移却一条 case 都没漂，"
            "说明门禁没在看 IR 字节",
            file=sys.stderr,
        )
        return 1
    for name in changed[: args.limit]:
        print(f"  bias: {name}  {baseline[name][:16]}… / {biased[name][:16]}…")
    if len(changed) > args.limit:
        print(f"  bias: … 还有 {len(changed) - args.limit} 条")
    print(f"gate:libm-noise:selftest ok — 粗噪声让 {len(changed)} 条 case 漂移，门禁有效")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="IR 在宿主 libm 噪声下必须逐条不变。")
    parser.add_argument(
        "--seed",
        type=int,
        default=7,
        help="mixed 模式选抽取位的种子（只用低 3 位，seed 空间 = 8 个等价类）",
    )
    parser.add_argument("--limit", type=int, default=10, help="每档最多列出的漂移 case 数")
    parser.add_argument(
        "--expect-diff",
        action="store_true",
        help="负向对照：注入 1e-4 的粗噪声，必须至少有一条 case 漂移",
    )
    args = parser.parse_args(argv)

    if not CASES.is_dir():
        print(f"gate:libm-noise: 找不到案例库 {CASES}", file=sys.stderr)
        return 2

    if args.expect_diff:
        return expect_diff(args)

    baseline = digests()
    print(f"  baseline : {len(baseline)} case(s)")
    drifted_by_mode: dict[str, list[str]] = {}
    noisy_by_mode: dict[str, dict[str, str]] = {}
    for mode in MODES:
        with libm_noise.libm_noise(mode, seed=args.seed):
            noisy = digests()
        noisy_by_mode[mode] = noisy
        drifted_by_mode[mode] = drifted(baseline, noisy)
        print(f"  libm {mode:6s}: {len(drifted_by_mode[mode])} drifted")

    total = sum(len(names) for names in drifted_by_mode.values())
    if total == 0:
        print(
            f"gate:libm-noise: ok — 三种 libm 噪声（seed={args.seed}）下 "
            f"{len(baseline)} 条 case 的 IR 逐条相同"
        )
        return 0

    for mode, names in drifted_by_mode.items():
        for name in names[: args.limit]:
            other = noisy_by_mode[mode].get(name, "（缺失）")
            print(
                f"  {mode}: {name}  {baseline[name][:16]}… / {other[:16]}…",
                file=sys.stderr,
            )
            # SIL-884：判红时把「漂在哪个节点 / 字段 / 元素」直接打出来。门禁在
            # 另一台机器（glibc / CPU 不同）上红、本机 0 drifted 时，CI 日志本身
            # 就是唯一能复核定位的材料——只打「1 处漂移」等于把人挡在门外。
            for line in libm_noise_probe.diff_case(name, mode, args.seed):
                print(f"      {line}", file=sys.stderr)
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

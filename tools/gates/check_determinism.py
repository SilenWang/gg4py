"""X1 门禁 · 同输入同字节。

把占位 scene 用两个独立的解释器进程（不同 `PYTHONHASHSEED`）各序列化一次，
比较 stdout：摘要不同即失败。真 IR 落地后这里的载荷换成真实 scene，判定方式
不变。

用法：
    pixi run gate:determinism
    python tools/gates/check_determinism.py --runs 3
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHILD = Path(__file__).resolve().parent / "_determinism_child.py"

# 取两个差异明显的种子：只要序列化路径里混进 set/dict 迭代顺序就会暴露。
HASH_SEEDS = ("0", "12345", "77")


def run_child(seed: str) -> tuple[int, str]:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = seed
    env.pop("PYTHONPATH", None)  # 子进程自己接管 sys.path，避免外部路径干扰
    proc = subprocess.run(
        [sys.executable, str(CHILD)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    output = proc.stdout.strip() + proc.stderr.strip()
    return proc.returncode, output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="X1: same input must yield identical bytes.")
    parser.add_argument(
        "--runs",
        type=int,
        default=len(HASH_SEEDS),
        help=f"number of child processes (default: {len(HASH_SEEDS)})",
    )
    args = parser.parse_args(argv)

    seeds = HASH_SEEDS[: max(args.runs, 2)]
    results: list[tuple[str, int, str]] = []
    for seed in seeds:
        code, output = run_child(seed)
        if code != 0:
            print(
                f"gate:determinism: FAIL — child (PYTHONHASHSEED={seed}) exited {code}",
                file=sys.stderr,
            )
            print(output, file=sys.stderr)
            return 2
        results.append((seed, code, output))

    baseline_seed, _, baseline = results[0]
    mismatched = [(seed, output) for seed, _, output in results[1:] if output != baseline]
    if mismatched:
        print("gate:determinism: FAIL — serialization is not byte-stable", file=sys.stderr)
        print(f"  PYTHONHASHSEED={baseline_seed}:\n{baseline}", file=sys.stderr)
        for seed, output in mismatched:
            print(f"  PYTHONHASHSEED={seed}:\n{output}", file=sys.stderr)
        return 1

    digest = next(
        (line.split("=", 1)[1] for line in baseline.splitlines() if line.startswith("digest=")),
        "<none>",
    )
    print(f"gate:determinism: ok — {len(results)} run(s), sha256={digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

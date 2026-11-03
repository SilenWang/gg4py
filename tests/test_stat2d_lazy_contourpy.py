"""SIL-758 · 缺 contourpy 时只有等值线路径失败（pytest 侧的薄壳）。

判定逻辑与对照数据在 `tools/gates/check_contourpy_lazy.py`——它把 contourpy 从
`sys.meta_path` 上挡掉，跑全部 8 个 2D stat 并核对「非 contour 可用 / contour 族
失败 / 非 contour 路径没加载 contourpy」。这里只负责在**子进程**里跑它：

- 子进程是必需的：模块缓存与 `sys.meta_path` 都不能被别的用例污染；
- `--json` 让 stdout 只有一行结果表，断言不用解析人类可读输出。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "gates" / "check_contourpy_lazy.py"


def test_missing_contourpy_only_breaks_the_contour_paths() -> None:
    env = dict(os.environ)
    extra = [part for part in env.get("PYTHONPATH", "").split(os.pathsep) if part]
    paths = [str(REPO / "src"), *extra]
    env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(paths))
    completed = subprocess.run(
        [sys.executable, str(TOOL), "--json"],
        capture_output=True,
        text=True,
        cwd=REPO,
        env=env,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    outcome = json.loads(completed.stdout)

    assert outcome["results"] == {
        "bin_2d": "ok",
        "bin_hex": "ok",
        "summary_2d": "ok",
        "summary_hex": "ok",
        "density_2d_grid": "ok",
        "contour": "ImportError",
        "contour_filled": "ImportError",
        "density_2d": "ImportError",
        "density_2d_filled": "ImportError",
    }
    # 非 contour 路径连 `ggcore.contour` 都不该碰：它一旦被 import，下一次
    # `_generator()` 就只剩 contourpy 这一层失败点了，回归会更难定位。
    assert outcome["non_contour_loaded_contourpy"] is False
    assert outcome["non_contour_loaded_ggcore_contour"] is False

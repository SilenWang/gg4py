"""SIL-758 · contourpy 只在等值线路径上加载。

审阅 PR #58 时发现的事实：`ggcore/stat2d.py` 顶层 `from ggcore.contour import …`、
`ggcore/contour.py` 顶层 `import contourpy`，于是**任何** 2D stat 一被调用就加载
contourpy，`bin_2d` / `bin_hex` / `summary_2d` / `summary_hex` 在缺 contourpy 的
运行时（例如只装了 numpy 的浏览器内核）也会炸。

这个用例在**子进程**里屏蔽 `contourpy`（`sys.meta_path` 前置一个 finder），
断言四个非 contour stat 照常跑完、contourpy 一个字节都没加载；只有
`stat_contour*` / `stat_density_2d*` 的 contour 分支才失败。子进程是刻意的：
模块缓存不会被别的用例污染，屏蔽对被测进程真的生效。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"

#: 子进程脚本：屏蔽 contourpy → 跑 2D stat → 打印结果表。
PROBE = """\
import importlib.abc
import json
import sys


class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name == "contourpy" or name.startswith("contourpy."):
            raise ImportError("contourpy is blocked for this run (SIL-758)")
        return None


sys.meta_path.insert(0, Blocker())

import numpy as np

from ggcore import registry
from ggcore.build import build_plot
from ggcore.data import Column, ColumnTable
from ggcore.plot import aes, ggplot

GRID = {
    "x": [x for _ in range(1, 5) for x in range(1, 6)],
    "y": [y for y in range(1, 5) for _ in range(1, 6)],
    "z": [x * 0.5 + y for y in range(1, 5) for x in range(1, 6)],
}


def table(values):
    return ColumnTable(
        [
            (name, Column("float", np.array(items, dtype=np.float64)))
            for name, items in values.items()
        ]
    )


def plot(stat):
    return ggplot(table(GRID), aes(x="x", y="y", z="z")) + stat


CASES = {
    "bin_2d": lambda: plot(registry.stat_bin_2d(binwidth=[1, 1])),
    "bin_hex": lambda: plot(registry.stat_bin_hex(binwidth=[1, 1])),
    "summary_2d": lambda: plot(registry.stat_summary_2d(binwidth=[1, 1])),
    "summary_hex": lambda: plot(registry.stat_summary_hex(binwidth=[1, 1])),
    "contour": lambda: plot(registry.stat_contour()),
    "contour_filled": lambda: plot(registry.stat_contour_filled()),
    "density_2d": lambda: plot(registry.stat_density_2d()),
    "density_2d_filled": lambda: plot(registry.stat_density_2d_filled()),
    # 密度网格本身不是等值线：`contour = FALSE` 时同样不该加载 contourpy。
    "density_2d_grid": lambda: plot(registry.stat_density_2d(contour=False, n=10)),
}

NON_CONTOUR = ("bin_2d", "bin_hex", "summary_2d", "summary_hex", "density_2d_grid")


def attempt(name):
    try:
        build_plot(CASES[name]())
    except ImportError:
        return "ImportError"
    return "ok"


results = {name: attempt(name) for name in NON_CONTOUR}
# 到这一步只碰过非 contour 路径：contourpy / ggcore.contour 都不得进 sys.modules。
loaded = {
    "non_contour_run_loaded_contourpy": "contourpy" in sys.modules,
    "non_contour_run_loaded_ggcore_contour": "ggcore.contour" in sys.modules,
}
results.update({name: attempt(name) for name in CASES if name not in NON_CONTOUR})

print(
    json.dumps(
        {
            "results": results,
            "non_contour": list(NON_CONTOUR),
            **loaded,
        },
        sort_keys=True,
    )
)
"""


def test_missing_contourpy_only_breaks_the_contour_paths(tmp_path: Path) -> None:
    script = tmp_path / "probe_missing_contourpy.py"
    script.write_text(PROBE, encoding="utf-8")
    env = dict(os.environ)
    paths = [str(SRC)] + [part for part in env.get("PYTHONPATH", "").split(os.pathsep) if part]
    env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(paths))
    completed = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
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
    assert outcome["non_contour_run_loaded_contourpy"] is False
    assert outcome["non_contour_run_loaded_ggcore_contour"] is False

"""SIL-758 · 缺 contourpy 时只有等值线路径失败。

审阅 PR #58 时发现的事实：`ggcore/stat2d.py` 顶层 `from ggcore.contour import …`、
`ggcore/contour.py` 顶层 `import contourpy`，于是**任何** 2D stat 一被调用就加载
contourpy，`bin_2d` / `bin_hex` / `summary_2d` / `summary_hex` 在缺 contourpy 的
运行时（例如只装了 numpy 的浏览器内核）也会炸。

这个脚本把 `contourpy` 从 `sys.meta_path` 上挡掉，跑全部 8 个 2D stat：

- `bin_2d` / `bin_hex` / `summary_2d` / `summary_hex` 必须成功；
- `density_2d(contour = FALSE)` 只是密度网格，也必须成功；
- `contour` / `contour_filled` / `density_2d` / `density_2d_filled` 必须失败
  （`ImportError`），因为它们的几何离不开 contourpy。

跑完非 contour 那组之后还会断言 `contourpy` 与 `ggcore.contour` 都**没有**进
`sys.modules`——否则「非 contour stat 不加载 contourpy」只是「碰巧还能用」。

用法：
    pixi run gate:contourpy-lazy       # 退出码 0 = 判定通过；1 = 有 stat 行为不对

`--json` 输出机器可读的结果表（`tests/test_stat2d_lazy_contourpy.py` 用它）。
"""

from __future__ import annotations

import argparse
import importlib.abc
import json
import sys
from typing import Any


class _BlockContourpy(importlib.abc.MetaPathFinder):
    """把 contourpy 变成「装了也导不进」：模拟只带 numpy 的浏览器运行时。"""

    def find_spec(self, name: str, path: Any = None, target: Any = None) -> None:
        if name == "contourpy" or name.startswith("contourpy."):
            raise ImportError("contourpy is blocked for this run (SIL-758)")
        return None


#: 与 `tests/test_stat_2d_r_parity.py` 的 `GRID` 同一份数字（够跑出等值线）。
GRID = {
    "x": [x for _ in range(1, 5) for x in range(1, 6)],
    "y": [y for y in range(1, 5) for _ in range(1, 6)],
    "z": [x * 0.5 + y for y in range(1, 5) for x in range(1, 6)],
}

#: 非 contour 路径：这些必须成功（`density_2d_grid` 是 `contour = FALSE`）。
NON_CONTOUR = ("bin_2d", "bin_hex", "summary_2d", "summary_hex", "density_2d_grid")


def _run() -> dict[str, Any]:
    import numpy as np

    from ggcore import registry
    from ggcore.build import build_plot
    from ggcore.data import Column, ColumnTable
    from ggcore.plot import aes, ggplot

    table = ColumnTable(
        [
            (name, Column("float", np.asarray(values, dtype=np.float64)))
            for name, values in GRID.items()
        ]
    )

    def plot(stat: Any) -> Any:
        return ggplot(table, aes(x="x", y="y", z="z")) + stat

    cases = {
        "bin_2d": lambda: plot(registry.stat_bin_2d(binwidth=[1, 1])),
        "bin_hex": lambda: plot(registry.stat_bin_hex(binwidth=[1, 1])),
        "summary_2d": lambda: plot(registry.stat_summary_2d(binwidth=[1, 1])),
        "summary_hex": lambda: plot(registry.stat_summary_hex(binwidth=[1, 1])),
        "contour": lambda: plot(registry.stat_contour()),
        "contour_filled": lambda: plot(registry.stat_contour_filled()),
        "density_2d": lambda: plot(registry.stat_density_2d()),
        "density_2d_filled": lambda: plot(registry.stat_density_2d_filled()),
        "density_2d_grid": lambda: plot(registry.stat_density_2d(contour=False, n=10)),
    }

    def attempt(name: str) -> str:
        try:
            build_plot(cases[name]())
        except ImportError:
            return "ImportError"
        return "ok"

    results = {name: attempt(name) for name in NON_CONTOUR}
    loaded = {
        "non_contour_loaded_contourpy": "contourpy" in sys.modules,
        "non_contour_loaded_ggcore_contour": "ggcore.contour" in sys.modules,
    }
    results.update({name: attempt(name) for name in cases if name not in NON_CONTOUR})
    return {"results": results, "non_contour": list(NON_CONTOUR), **loaded}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SIL-758: 2D stats without contourpy.")
    parser.add_argument("--json", action="store_true", help="机器可读的结果表")
    args = parser.parse_args(argv)

    sys.meta_path.insert(0, _BlockContourpy())
    outcome = _run()

    if args.json:
        print(json.dumps(outcome, sort_keys=True))
    else:
        for name, result in outcome["results"].items():
            print(f"  {name:20s} {result}")
        print(
            "  contourpy loaded by non-contour stats: "
            f"{outcome['non_contour_loaded_contourpy']}; "
            f"ggcore.contour loaded: {outcome['non_contour_loaded_ggcore_contour']}"
        )

    expected = {
        **{name: "ok" for name in NON_CONTOUR},
        "contour": "ImportError",
        "contour_filled": "ImportError",
        "density_2d": "ImportError",
        "density_2d_filled": "ImportError",
    }
    problems: list[str] = []
    if outcome["results"] != expected:
        problems.append(f"results: {outcome['results']} != {expected}")
    if outcome["non_contour_loaded_contourpy"]:
        problems.append("非 contour stat 加载了 contourpy")
    if outcome["non_contour_loaded_ggcore_contour"]:
        problems.append("非 contour stat 导入了 ggcore.contour")

    # `--json` 时判定行走 stderr：stdout 只留一行 JSON，调用方直接解析。
    verdict = sys.stderr if args.json else sys.stdout
    if problems:
        print("gate:contourpy-lazy: FAIL — " + "；".join(problems), file=verdict)
        return 1
    print(
        "gate:contourpy-lazy: ok — 缺 contourpy 时 4 个非 contour stat + "
        "density_2d(contour=FALSE) 可用，contour 族按预期失败，且非 contour 路径"
        "未加载 contourpy",
        file=verdict,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""E2 与 M0-7 必须按同一套规则切 run。

规则现在只有一份声明：`src/ggcore/metrics/data/rules.json`（Python 与 CanvasKit
脚本都读它）。M-1 的 `run_e2.py` 是冻结的实验脚本，仍保留自己的字面声明；本测试
比较两者，任何一侧改动都会红——早期两端集合各缺一段、只因语料恰好没覆盖才没
暴露，就是这么漏过去的。

CanvasKit 侧（`tools/metrics/measure_canvaskit.cjs`，spike 里的同名文件只是它的
薄壳）不再保有自己的区间声明，改为读同一份 rules.json；这里断言这个事实，避免
有人把区间内联回去。
"""

from __future__ import annotations

import re
from pathlib import Path

from ggcore.metrics.rules import GLUE_RANGES, RULES, RULES_VERSION

REPO = Path(__file__).resolve().parent.parent
PY_SRC = REPO / "docs" / "spike" / "e2_metrics" / "run_e2.py"
SPIKE_JS = REPO / "docs" / "spike" / "e2_metrics" / "measure_canvaskit.cjs"
SHARED_JS = REPO / "tools" / "metrics" / "measure_canvaskit.cjs"


def python_ranges() -> list[tuple[int, int]]:
    src = PY_SRC.read_text(encoding="utf-8")
    block = re.search(r"GLUE_RANGES = \[(.*?)\]", src, re.S)
    assert block, "GLUE_RANGES not found in run_e2.py"
    return [
        (int(lo, 16), int(hi, 16)) for lo, hi in re.findall(r"\(0x(\w+), 0x(\w+)\)", block.group(1))
    ]


def test_spike_and_rules_declare_the_same_glue_ranges() -> None:
    assert tuple(python_ranges()) == GLUE_RANGES


def test_glue_ranges_cover_the_full_variation_selector_blocks() -> None:
    assert (0x200C, 0x200D) in GLUE_RANGES, "ZWNJ/ZWJ must glue to the previous run"
    assert (0xFE00, 0xFE0F) in GLUE_RANGES, "VS1-16 must glue to the previous run"
    assert (0xE0100, 0xE01EF) in GLUE_RANGES, "VS17-256 must glue to the previous run"


def test_canvaskit_side_reads_the_shared_rules() -> None:
    shared = SHARED_JS.read_text(encoding="utf-8")
    assert "src/ggcore/metrics/data/rules.json" in shared
    assert "GLUE_RANGES" not in shared, "CanvasKit side must not keep a second copy of the ranges"

    spike = SPIKE_JS.read_text(encoding="utf-8")
    assert "tools/metrics/measure_canvaskit.cjs" in spike, "spike script must delegate"
    assert "GLUE_RANGES" not in spike


def test_rules_file_is_versioned() -> None:
    assert isinstance(RULES_VERSION, int) and RULES_VERSION >= 1
    assert RULES["version"] == RULES_VERSION
    assert RULES["default_font_stack"], "the default font stack must be declared in rules.json"

"""The two E2 harnesses must split text into font runs with the same rule.

If they drift, E2 can pass on a corpus that happens to avoid the difference and
then quietly disagree on real charts. The rule is declared as code-point ranges
in both files; this test reads them back and compares.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY_SRC = REPO / "docs" / "spike" / "e2_metrics" / "run_e2.py"
JS_SRC = REPO / "docs" / "spike" / "e2_metrics" / "measure_canvaskit.cjs"


def python_ranges() -> list[tuple[int, int]]:
    src = PY_SRC.read_text(encoding="utf-8")
    block = re.search(r"GLUE_RANGES = \[(.*?)\]", src, re.S)
    assert block, "GLUE_RANGES not found in run_e2.py"
    return [
        (int(lo, 16), int(hi, 16)) for lo, hi in re.findall(r"\(0x(\w+), 0x(\w+)\)", block.group(1))
    ]


def javascript_ranges() -> list[tuple[int, int]]:
    src = JS_SRC.read_text(encoding="utf-8")
    block = re.search(r"const GLUE_RANGES = \[(.*?)\];", src, re.S)
    assert block, "GLUE_RANGES not found in measure_canvaskit.cjs"
    return [
        (int(lo, 16), int(hi, 16)) for lo, hi in re.findall(r"\[0x(\w+), 0x(\w+)\]", block.group(1))
    ]


def test_glue_ranges_are_identical() -> None:
    assert python_ranges() == javascript_ranges()


def test_glue_ranges_cover_the_full_variation_selector_blocks() -> None:
    ranges = python_ranges()
    assert (0x200C, 0x200D) in ranges, "ZWNJ/ZWJ must glue to the previous run"
    assert (0xFE00, 0xFE0F) in ranges, "VS1-16 must glue to the previous run"
    assert (0xE0100, 0xE01EF) in ranges, "VS17-256 must glue to the previous run"

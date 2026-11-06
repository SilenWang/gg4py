"""`cases:audit` 的计数口径（SIL-844）：多行标签按**行**算，不按节点算。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "cases"))

import audit


def test_text_lines_counts_each_line() -> None:
    """一个 IR text 节点对应上游 svglite 的几个 `<text>`。"""
    assert audit._text_lines(("a",)) == 1
    assert audit._text_lines(("strawberry\ncake",)) == 2
    assert audit._text_lines(("a", "b")) == 2
    assert audit._text_lines(("a\nb\nc",)) == 3
    assert audit._text_lines(()) == 1


def test_multiline_label_counts_as_two_texts() -> None:
    """`half-circle-rotated-text` 的 11pt 按行展开是 14 个（2 层 × 6 行 + x/y 标题）。

    这条 case 每层有一个 `strawberry\ncake` 多行标签：按节点数是 2 层 × 5 + 2 = 12，
    按行数是 2 层 × 6 + 2 = 14，与上游 `expected.svg` 的 14 个 `font-size: 11.00px`
    对齐（SIL-844）。
    """
    case = ROOT / "docs" / "cases" / "upstream-coord-polar-half-circle-rotated-text"
    sizes = audit.ours_sizes(case)
    assert sizes is not None
    assert sizes[11.0] == 14

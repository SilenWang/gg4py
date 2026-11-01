"""文本 run 切分与 grapheme cluster 规则（M0-7）。

规则本身声明在 `data/rules.json`（`ggcore.metrics.rules` 读取），Python 度量端
（HarfBuzz）与浏览器端（CanvasKit）共用同一份：CanvasKit 的
`TypefaceFontProvider` 不跨字族回退，整串丢给主字族会退化成 `.notdef` 盒子
（200 条语料里 132 条量错，见 `docs/spike/e2_metrics/report.md`），所以「显式切
run」是规范而不是优化。

两个动作分开：

1. `split_runs()`：**run 切分**。逐码点选字体栈里第一个 cmap 覆盖它的字族；粘着
   码点（`U+200C–200D`、`U+FE00–FE0F`、`U+E0100–E01EF`）永远不单独起 run，黏在
   前一个 run 上。没有任何字族覆盖的码点留在当前 run（两端都渲染成 `.notdef`）。
2. `clusters()`：**grapheme cluster 切分**。仅兜底度量表（`ggcore.metrics.table`）
   用来判断「这个 emoji 序列应该算一个字形宽还是多个」。走 HarfBuzz 时用不到。

`is_supported()` 回答「这段文字能不能只用兜底表量」：阿拉伯/希伯来/印度诸语/
泰文/高棉/缅文/藏文/朝鲜 jamo 等需要上下文 shaping，逐码点 advance 表无法复现。
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from ggcore.metrics.rules import (
    COMPLEX_SCRIPT_RANGES,
    DEFAULT_FONT_STACK,
    GLUE_RANGES,
    RULES_VERSION,
)

__all__ = [
    "COMPLEX_SCRIPT_RANGES",
    "DEFAULT_FONT_STACK",
    "GLUE_RANGES",
    "RULES_VERSION",
    "Run",
    "clusters",
    "is_glue",
    "is_supported",
    "split_runs",
    "stack_tuple",
]

# 肤色修饰符：单独一个码点就是一次完整的 emoji 宽度，跟着 emoji 时被合字吞掉。
SKIN_TONE_RANGE = (0x1F3FB, 0x1F3FF)
# 区域指示符：成对构成国旗（两个 RI = 一个字形宽）。
REGIONAL_INDICATOR_RANGE = (0x1F1E6, 0x1F1FF)
# keycap 序列的收尾（`1` + VS16 + U+20E3）。
KEYCAP = 0x20E3
ZWJ = 0x200D

GLUE_CODEPOINTS: frozenset[int] = frozenset(
    cp for lo, hi in GLUE_RANGES for cp in range(lo, hi + 1)
)


def _in(value: int, ranges: Iterable[tuple[int, int]]) -> bool:
    return any(lo <= value <= hi for lo, hi in ranges)


def is_glue(codepoint: int) -> bool:
    """粘着码点：不单独起 run，也不占宽度。"""
    return codepoint in GLUE_CODEPOINTS


def is_supported(text: str) -> bool:
    """兜底度量表能否量这段文字（False 时必须走渲染端实测）。

    判据只否认明确列出的复杂书写系统：拉丁/希腊/西里尔/CJK/emoji/普通组合记号
    都在支持范围内。
    """
    return not any(_in(ord(ch), COMPLEX_SCRIPT_RANGES) for ch in text)


@dataclass(frozen=True)
class Run:
    """一段按字族切开的文字（`font_index` 指向 font_stack）。"""

    font_index: int
    text: str


def split_runs(text: str, covers: Callable[[int, int], bool], font_count: int) -> tuple[Run, ...]:
    """按「第一个覆盖该码点的字族」把 text 切成 runs。

    `covers(font_index, codepoint)` 由后端实现（HarfBuzz 查 cmap，兜底表查表）；
    `font_count` 是 font_stack 的长度。粘着码点与无人覆盖的码点留在当前 run 里。
    """
    if not text:
        return ()
    runs: list[Run] = []
    current_index = 0
    current: list[str] = []
    for ch in text:
        cp = ord(ch)
        index: int | None = None
        if cp not in GLUE_CODEPOINTS:
            for candidate in range(font_count):
                if covers(candidate, cp):
                    index = candidate
                    break
        if index is None:
            current.append(ch)
            continue
        if current and index != current_index:
            runs.append(Run(current_index, "".join(current)))
            current = []
        current_index = index
        current.append(ch)
    if current:
        runs.append(Run(current_index, "".join(current)))
    return tuple(runs)


def clusters(text: str) -> tuple[str, ...]:
    """简化的 extended grapheme cluster 切分（仅兜底表使用）。

    一个 cluster = 基码点 + 后续的组合记号 / 变体选择符 / 肤色修饰符 / keycap /
    ZWJ 及其后的码点，以及成对的区域指示符（国旗）。
    """
    out: list[list[str]] = []
    join_next = False
    for ch in text:
        cp = ord(ch)
        glue = (
            cp in GLUE_CODEPOINTS
            or (SKIN_TONE_RANGE[0] <= cp <= SKIN_TONE_RANGE[1])
            or cp == KEYCAP
            or unicodedata.category(ch).startswith("M")
        )
        pairs_as_flag = (
            bool(out)
            and REGIONAL_INDICATOR_RANGE[0] <= cp <= REGIONAL_INDICATOR_RANGE[1]
            and len(out[-1]) == 1
            and REGIONAL_INDICATOR_RANGE[0] <= ord(out[-1][0]) <= REGIONAL_INDICATOR_RANGE[1]
        )
        if out and (glue or join_next or pairs_as_flag):
            out[-1].append(ch)
            join_next = cp == ZWJ
            continue
        out.append([ch])
        join_next = cp == ZWJ
    return tuple("".join(cluster) for cluster in out)


def stack_tuple(font_stack: Sequence[str] | None, default: Sequence[str]) -> tuple[str, ...]:
    """把 font_stack 归一成 tuple（缓存键与确定性输出都要求可哈希、可比较）。"""
    return tuple(default if font_stack is None else font_stack)

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

import bisect
import json
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

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
    "SCRIPT_RANGES",
    "Run",
    "clusters",
    "is_glue",
    "is_supported",
    "script_of",
    "script_segments",
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

# 码点 → HarfBuzz script 标签（`data/scripts.json`，由 tools/metrics/build_scripts.py
# 从 HarfBuzz 自己的 unicode script 数据冻结而成）。ggcore 不能 import uharfbuzz
# （X1），但分段必须与它对此串的判定一致，所以只冻结数据、不冻结引擎。
# 表只服务 Python 侧的 shaping 分段：CanvasKit 的 SkParagraph 自己按 script 切段，
# 两端没有「script 表」契约，因此它不进 rules.json（也不触发兜底表重生成）。
_SCRIPTS_PATH = Path(__file__).with_name("data") / "scripts.json"
_SCRIPTS: dict = json.loads(_SCRIPTS_PATH.read_text(encoding="utf-8"))
# 按码点升序、互不重叠；`test_script_table_is_sorted_and_non_overlapping` 钉住。
SCRIPT_RANGES: tuple[tuple[int, int, str], ...] = tuple(
    (int(low, 16), int(high, 16), tag) for low, high, tag in _SCRIPTS["ranges"]
)
_SCRIPT_LOWS = tuple(low for low, _, _ in SCRIPT_RANGES)
# Common / Inherited / 未分配：unicode_script 没有强 script，不参与切段。
COMMON_SCRIPT = "Zyyy"


def _in(value: int, ranges: Iterable[tuple[int, int]]) -> bool:
    return any(lo <= value <= hi for lo, hi in ranges)


def is_glue(codepoint: int) -> bool:
    """粘着码点：不单独起 run，也不占宽度。"""
    return codepoint in GLUE_CODEPOINTS


def script_of(codepoint: int) -> str:
    """码点的真实 script 标签；Common / Inherited / 未分配返回 `Zyyy`。"""
    index = bisect.bisect_right(_SCRIPT_LOWS, codepoint) - 1
    if index >= 0:
        low, high, tag = SCRIPT_RANGES[index]
        if low <= codepoint <= high:
            return tag
    return COMMON_SCRIPT


def is_supported(text: str) -> bool:
    """兜底度量表能否量这段文字（False 时必须走渲染端实测）。

    判据只否认明确列出的复杂书写系统：拉丁/希腊/西里尔/CJK/emoji/普通组合记号
    都在支持范围内。
    """
    return not any(_in(ord(ch), COMPLEX_SCRIPT_RANGES) for ch in text)


def script_segments(text: str) -> tuple[str, ...]:
    """按真实 script 把一段文字切成 script 段（段内仍由 HarfBuzz 自己猜 script）。

    HarfBuzz 的 `guess_segment_properties()` 每段只取一个 script：整串
    `"n=각"` 按开头的拉丁字母判成 Latin，后面的 Hangul jamo 就不再合成
    音节（CanvasKit 的 SkParagraph 自己按 script 切段，同一串只占 32.34px，
    HarfBuzz 整段量出 61.78px）。所以 shape 前先按 script 切段。

    判定口径是「相邻两个**真实 script** 才切」：Hangul 音节（`AC00-D7A3`）与
    朝鲜 jamo（`1100-11FF`）都算 `Hang`，同一段；不能按「复杂/非复杂」二值切
    （那会把 `가`+尾 jamo、ZWJ 连写切成半截，见 tests/test_metrics.py）。
    粘着码点（ZWJ / ZWNJ / 变体选择符）与组合记号永远黏在前一段，不新起段。
    """
    out: list[str] = []
    current: list[str] = []
    resolved: str | None = None  # 当前段的强 script；None = 只有 Common/粘着码点
    for ch in text:
        codepoint = ord(ch)
        if codepoint in GLUE_CODEPOINTS or unicodedata.category(ch).startswith("M"):
            current.append(ch)
            continue
        script = script_of(codepoint)
        if current and resolved is not None and script != COMMON_SCRIPT and script != resolved:
            out.append("".join(current))
            current = []
            resolved = None
        current.append(ch)
        if resolved is None and script != COMMON_SCRIPT:
            resolved = script
    if current:
        out.append("".join(current))
    return tuple(out)


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

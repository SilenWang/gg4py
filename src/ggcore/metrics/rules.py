"""度量规则的唯一声明（M0-7）。

`data/rules.json` 是两端共用的规范：Python 度量（本模块）与 CanvasKit 度量脚本
（`tools/metrics/measure_canvaskit.cjs`）读同一份文件，改规则只改一处。

改动规则文件时：

1. `version` +1；
2. `pixi run metrics:table` 重新生成兜底表（表的头里带规则版本，版本不符会被
   `ggcore.metrics.table.decode_table` 拒绝）；
3. `pixi run gate:metrics` 复验双端一致性。
"""

from __future__ import annotations

import json
from pathlib import Path

RULES_PATH = Path(__file__).with_name("data") / "rules.json"
RULES: dict = json.loads(RULES_PATH.read_text(encoding="utf-8"))
RULES_VERSION: int = int(RULES["version"])


def _ranges(key: str) -> tuple[tuple[int, int], ...]:
    out: list[tuple[int, int]] = []
    for low, high in RULES[key]:
        lo, hi = int(low, 16), int(high, 16)
        if lo > hi:
            raise ValueError(f"{RULES_PATH.name}: {key} has an inverted range {low!r}-{high!r}")
        out.append((lo, hi))
    return tuple(out)


# 粘着码点：joiners（ZWNJ/ZWJ）与变体选择符永远属于前一个 run，且不占宽度。
GLUE_RANGES: tuple[tuple[int, int], ...] = _ranges("glue_ranges")
# 兜底度量表不建模的书写系统（上下文 shaping 无法逐码点复现）。
COMPLEX_SCRIPT_RANGES: tuple[tuple[int, int], ...] = _ranges("complex_script_ranges")

# 文件名 → 字族名。浏览器端 `TypefaceFontProvider.registerFont` 与 TS 侧
# `font-family` 用这里的名字，不要另写一份。
FONT_FAMILIES: dict[str, str] = {entry["file"]: entry["family"] for entry in RULES["fonts"]}
# 度量默认字体栈，顺序即回退优先级。
DEFAULT_FONT_STACK: tuple[str, ...] = tuple(RULES["default_font_stack"])

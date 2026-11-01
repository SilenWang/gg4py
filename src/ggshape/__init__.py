"""ggshape — 文本形状与度量后端（HarfBuzz）。

放在 `ggcore` **之外**是有原因的：`src/ggcore/` 的 import 白名单只允许标准库 /
numpy / CBOR 编码库（`docs/notes/gates.md` · X1），uharfbuzz 进不去；而 Pyodide
早期路径没有 HarfBuzz，只能走 `ggcore.metrics.table` 的预生成表。所以「怎么量」
是一个可替换后端，「量出来什么规则」留在 `ggcore.metrics` 里，两端共用。
"""

from __future__ import annotations

from ggshape.harfbuzz import HarfBuzzBackend, harfbuzz_provider

__all__ = ["HarfBuzzBackend", "harfbuzz_provider"]

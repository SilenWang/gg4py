"""ggcore — gg4py 的语法核心（纯 Python，只依赖 numpy）。

这条边界由 X1 门禁强制：`src/ggcore/` 里只允许 import 标准库、numpy 和
CBOR 编码库；pandas / Arrow / 任何绘图库都必须留在包外（见
`tools/gates/check_import_whitelist.py` 与 `docs/notes/gates.md`）。

IR（已解析几何的唯一中间表示）在 `ggcore.ir`，口径见 `docs/notes/ir.md`。
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"

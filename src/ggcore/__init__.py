"""ggcore — gg4py 的语法核心（纯 Python，只依赖 numpy）。

这条边界由 X1 门禁强制：`src/ggcore/` 里只允许 import 标准库、numpy 和
CBOR 编码库；pandas / Arrow / 任何绘图库都必须留在包外（见
`tools/gates/check_import_whitelist.py` 与 `docs/notes/gates.md`）。

语法层（M1-1）在 `ggcore.plot` / `ggcore.registry` / `ggcore.aes` /
`ggcore.layer` / `ggcore.components`：`ggplot()` 对象、`+` 组合、克隆语义与
方法链别名。

IR（已解析几何的唯一中间表示）在 `ggcore.ir`，口径见 `docs/notes/ir.md`。
坐标底座在 `ggcore.units` / `ggcore.viewport`，口径见 `docs/notes/units.md` /
`docs/notes/viewport.md`。
"""

from __future__ import annotations

import ggcore.aes as aes
import ggcore.components as components
import ggcore.data as data
import ggcore.grobs as grobs
import ggcore.gtable as gtable
import ggcore.layer as layer
import ggcore.plot as plot
import ggcore.plotspec as plotspec
import ggcore.registry as registry
import ggcore.units as units
import ggcore.viewport as viewport

__all__ = [
    "__version__",
    "aes",
    "components",
    "data",
    "grobs",
    "gtable",
    "layer",
    "plot",
    "plotspec",
    "registry",
    "units",
    "viewport",
]
__version__ = "0.1.0"

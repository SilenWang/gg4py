"""`gg4py.ir` — IR v0 的开发者入口（节点类型、CBOR codec）。

    import gg4py.ir

    blob = gg4py.ir.encode(gg4py.ir.demo_scene())
    scene = gg4py.ir.decode(blob)

只有转发：名字与 `ggcore.ir.__all__` 同源。普通用户不需要它；
`gg4py.io.save_ir` 已把「一张图 → IR 文件」包好了。
"""

from __future__ import annotations

from typing import Any

import ggcore.ir as _ir

__all__ = list(_ir.__all__)


def __getattr__(name: str) -> Any:
    try:
        return getattr(_ir, name)
    except AttributeError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None

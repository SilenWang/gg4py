"""`gg4py.io` — IR 落盘与 `ggsave` 的开发者入口（不需要 skia）。

    import gg4py.io

    gg4py.io.save_ir(p, "plot.ggir.cbor")      # 同一张图 → IR
    gg4py.io.export_ir_json(p, "plot.ir.json")  # 调试视图
    gg4py.io.ggsave(p, "plot.png")              # 需要已注册的渲染后端

只有转发：名字与 `ggcore.io.__all__` 同源。常规出图用顶层 `gg4py.ggsave`
（它会惰性导入 `ggskia` 并注册后端）；这里保留设备无关的编排与
`register_backend` / `save_ir` 这类扩展钩子。
"""

from __future__ import annotations

from typing import Any

import ggcore.io as _io

__all__ = list(_io.__all__)


def __getattr__(name: str) -> Any:
    try:
        return getattr(_io, name)
    except AttributeError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None

"""`gg4py.diff` — 参考图 × 实测图的差分（开发者 / 对拍入口）。

    import gg4py.diff

    result = gg4py.diff.compare_images(expected_png, current_png)
    gg4py.diff.rasterize_svg("expected.svg", "expected.png", dpi=72)

只有转发：名字与 `ggdiff.__all__` 同源。`numpy` 在导入时就会被拉起，
`pillow` 只在真正读写位图时用到。
"""

from __future__ import annotations

from typing import Any

import ggdiff as _diff

__all__ = list(_diff.__all__)


def __getattr__(name: str) -> Any:
    try:
        return getattr(_diff, name)
    except AttributeError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None

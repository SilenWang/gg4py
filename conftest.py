"""pytest 全局引导：把 `CONDA_PREFIX` 对齐到当前解释器所在的环境。

`ggcore.metrics` 按 `$CONDA_PREFIX/fonts` 找受管字体（M0-7）。`pixi run` 会把
`CONDA_PREFIX` 设成项目环境，所以正常的 `pixi run test` 不需要这里做任何事；
但如果直接用 `.pixi/envs/default/bin/python -m pytest`（或外层 shell 里还挂着
另一个环境的 `CONDA_PREFIX`），字体目录就会指到别处、`FontCatalog` 起不来。

这里只在**当前解释器自己的环境**确实带 `fonts/` 时覆盖；pixi 下两者本来就一致，
行为不变。测试自己用 `monkeypatch` 改 `CONDA_PREFIX` / `GG_FONT_DIR` 时照常生效
（`monkeypatch` 会在用例结束后还原成这里的值）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PREFIX = Path(sys.prefix)
if (_PREFIX / "fonts").is_dir():
    os.environ["CONDA_PREFIX"] = str(_PREFIX)

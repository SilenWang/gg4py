"""ggio — 输入适配层（pandas / Arrow / dict of arrays → `ggcore.data.ColumnTable`）。

`ggcore` 只认列式表，DataFrame-like 的解析在这里做。`import ggio` 本身只需要
numpy：pandas / pyarrow 在具体函数里可选导入，所以 prod 环境（没有 dev 依赖）
也能 import，只是用不了 pandas / arrow 两条路径。口径见 `docs/notes/data.md`。
"""

from __future__ import annotations

from ggio import frame
from ggio.frame import from_arrow, from_dict, from_pandas, to_column_table

__all__ = ["frame", "from_arrow", "from_dict", "from_pandas", "to_column_table"]

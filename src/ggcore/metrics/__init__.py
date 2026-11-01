"""文本度量（M0-7）。

```python
from ggshape import harfbuzz_provider

provider = harfbuzz_provider()
provider.advance("月份（万元）", 12)   # px
provider.runs("月份（万元）", 12)      # 显式 run 切分 + 每段宽度
provider.strheight("月份", 12)
```

CPython / 服务端用 `ggshape.harfbuzz.HarfBuzzBackend`；浏览器（Pyodide 早期路径）
用 `ggcore.metrics.table.TableBackend`，后端可换，规则不变：

* `runs.split_runs` —— 字族回退与粘着码点，两端逐字面一致；
* 尺寸换算 `font_units / upem * size`，单位是 CSS px。

口径与实测数据见 `docs/notes/metrics-ledger.md`（L1–L3、M0-7）。
"""

from __future__ import annotations

from ggcore.metrics.catalog import (
    DEFAULT_FONT_STACK,
    MANAGED_FONTS,
    FontCatalog,
    FontNotFound,
    ManagedFont,
)
from ggcore.metrics.provider import (
    FontMetrics,
    MetricProvider,
    MetricsBackend,
    RunMeasurement,
    ShapedRun,
)
from ggcore.metrics.runs import (
    COMPLEX_SCRIPT_RANGES,
    GLUE_RANGES,
    Run,
    clusters,
    is_supported,
    split_runs,
)
from ggcore.metrics.table import (
    RUN_RULES_VERSION,
    TABLE_VERSION,
    TableBackend,
    TableFont,
    decode_table,
    encode_table,
    table_path,
)

__all__ = [
    "COMPLEX_SCRIPT_RANGES",
    "DEFAULT_FONT_STACK",
    "GLUE_RANGES",
    "MANAGED_FONTS",
    "RUN_RULES_VERSION",
    "TABLE_VERSION",
    "FontCatalog",
    "FontMetrics",
    "FontNotFound",
    "ManagedFont",
    "MetricProvider",
    "MetricsBackend",
    "Run",
    "RunMeasurement",
    "ShapedRun",
    "TableBackend",
    "TableFont",
    "clusters",
    "decode_table",
    "encode_table",
    "is_supported",
    "split_runs",
    "table_path",
]

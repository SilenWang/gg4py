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
    FontFaceError,
    FontNotFound,
    ManagedFont,
    ResolvedFace,
)
from ggcore.metrics.faces import FAMILY_FACES, FontFace, available_styles, resolve_face

# 浏览器 / Pyodide 路径的 `ggcore.units.Metrics`：读兜底度量表，不需要 HarfBuzz
# 或字体文件（SIL-824）。放在最后 import：它依赖上面几个子模块已经就绪。
from ggcore.metrics.fallback import TableMetrics, default_metrics
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
    SCRIPT_RANGES,
    Run,
    clusters,
    is_supported,
    script_of,
    script_segments,
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
    "FAMILY_FACES",
    "GLUE_RANGES",
    "MANAGED_FONTS",
    "RUN_RULES_VERSION",
    "SCRIPT_RANGES",
    "TABLE_VERSION",
    "FontCatalog",
    "FontFace",
    "FontFaceError",
    "FontMetrics",
    "FontNotFound",
    "ManagedFont",
    "MetricProvider",
    "MetricsBackend",
    "ResolvedFace",
    "Run",
    "RunMeasurement",
    "ShapedRun",
    "TableBackend",
    "TableFont",
    "TableMetrics",
    "available_styles",
    "clusters",
    "decode_table",
    "default_metrics",
    "encode_table",
    "is_supported",
    "resolve_face",
    "script_of",
    "script_segments",
    "split_runs",
    "table_path",
]

"""共享夹具：R `datasets::mtcars` / `ggplot2::mpg` 的列。

上游快照的复刻图大量用这两份数据集。整份数据已经逐值内联在若干历史 case 的
`plot.py` 里；这里按文件路径读回那几份 DATA，避免在十几个新 case 里再抄一遍
234 行 / 32 行（口径仍是 R 4.5.3 的 `datasets::mtcars` 与 `ggplot2::mpg`）。

只给 case 资产用；`ggio` / `ggcore` 的公开 API 不依赖它。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(f"case_fixture_{abs(hash(path))}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


#: `mtcars` 全量列（mpg / cyl / disp / hp / drat / wt / qsec / vs / am / gear / carb）。
mtcars = _load("docs/cases/upstream-guide-axis-thick-axis-lines/plot.py").DATA
#: `ggplot2::mpg` 的 class / cty / hwy / displ 四列（`class` 在 4.0.3 里是 character）。
_mpg = _load("docs/cases/upstream-coord-transform-basic/plot.py").DATA
mpg = {"class": _mpg["cls"], "cty": _mpg["cty"], "hwy": _mpg["hwy"], "displ": _mpg["displ"]}

#: `ggplot2::mpg` 的 manufacturer / model / hwy 三列，外加 R 的
#: `levels(reorder(model, hwy))`（38 个水平，均值升序）。
#: 由 `pixi run -e refs Rscript` 逐值导出，见 `tools/upstream/fixtures/mpg_models.json`。
_models = json.loads(
    (ROOT / "tools" / "upstream" / "fixtures" / "mpg_models.json").read_text(encoding="utf-8")
)
mpg_models = {name: _models[name] for name in ("manufacturer", "model", "hwy")}
mpg_model_levels = _models["model_levels"]


def factor_column(values, levels):
    """`factor(values, levels = levels)`：categorical 列（缓冲是 levels 下标）。

    上游快照里大量用 `reorder(x, y)` 定轴序；R 的 `reorder()` 只改 factor 的
    **levels**，不改标度的 limits——`facet_grid(scales = "free", space = "free")`
    因此仍逐面板收缩范围。写成 `scale_*_discrete(limits = …)` 会把每个面板都钉到
    全量水平，`space = "free"` 就失效了（SIL-817）。
    """
    import numpy as np

    from ggcore.data import Column

    index = {level: position for position, level in enumerate(levels)}
    codes = np.asarray([index[value] for value in values], dtype=np.int32)
    return Column("categorical", codes, levels=tuple(levels))


def replace_column(table, name, column):
    """换掉 `ColumnTable` 里的一列（其余列原样保留）。"""
    from ggcore.data import ColumnTable

    return ColumnTable(
        [(item, column if item == name else table.column(item)) for item in table.names]
    )

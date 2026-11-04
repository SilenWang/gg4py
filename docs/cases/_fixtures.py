"""共享夹具：R `datasets::mtcars` / `ggplot2::mpg` 的列。

上游快照的复刻图大量用这两份数据集。整份数据已经逐值内联在若干历史 case 的
`plot.py` 里；这里按文件路径读回那几份 DATA，避免在十几个新 case 里再抄一遍
234 行 / 32 行（口径仍是 R 4.5.3 的 `datasets::mtcars` 与 `ggplot2::mpg`）。

只给 case 资产用；`ggio` / `ggcore` 的公开 API 不依赖它。
"""

from __future__ import annotations

import importlib.util
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

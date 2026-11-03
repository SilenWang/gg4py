"""guide：连续 colourbar（渐变条 + 刻度 + 标签）。

**ci = false**：色条本身已与 R 一致（SIL-722：端点取 palette(0..1)、1×nbin
位图、内侧白刻度），剩余 2.03% 来自图例整体右移 1.33pt——R 的 svglite 用拉丁
字体量标签宽（17.11pt），我们用 Noto Sans CJK SC 的拉丁字形量出 15.78pt，
是 `docs/notes/metrics-ledger.md` 里记的 M0-7 已知度量差。修度量再翻绿。
"""

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggio.frame import to_column_table

DATA = {
    "x": [0.10, 0.20, 0.35, 0.50, 0.65, 0.80, 0.90, 0.25, 0.75],
    "y": [0.20, 0.50, 0.35, 0.70, 0.45, 0.80, 0.60, 0.85, 0.15],
    "v": [0.00, 0.12, 0.25, 0.38, 0.50, 0.62, 0.75, 0.88, 1.00],
}

SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="v"))
        + geom_point(shape=19, size=3.2)
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
    )
    return {"plot": p, "size": SIZE}

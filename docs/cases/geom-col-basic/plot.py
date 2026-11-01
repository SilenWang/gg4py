"""geom-col / basic：连续 x 上的四根柱子，theme_void。

R 参考由 `tools/refs/cases_ref.R` 的 `geom-col-basic` 段生成
（`geom_col(width = 0.7)`，x / y 都 `expand = c(0, 0)`）。
"""

DATA = {
    "x": [0.5, 1.5, 2.5, 3.5],
    "y": [0.35, 0.75, 0.55, 0.9],
    "g": ["a", "b", "a", "b"],
}

PALETTE = {"a": "#4C78A8", "b": "#F58518"}


def build():
    return {
        "data": DATA,
        "mapping": {"x": "x", "y": "y", "fill": "g"},
        "layers": [{"geom": "col", "params": {"width": 0.7}}],
        "size": [4, 3],
        "limits": {"x": [0, 4], "y": [0, 1]},
        "palette": PALETTE,
    }

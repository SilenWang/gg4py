"""geom-text / cjk：带中文标签的文本图（M0-9 的三张基准之一）。

R 侧必须用同一份字体（`Noto Sans CJK SC`，pixi 的 `font-ttf-noto-cjk`），且
`svglite` 在 UTF-8 locale 下运行——否则标签会退化成 `.`（见 `docs/notes/diff.md`）。

字号 13 pt、五条标签：SIL-599 要求「人为偏移 2 像素必须判红」，文本太小时
2 px 位移在 2% 的图级阈值下看不出来（分母是整张画布）。
"""

DATA = {
    "x": [0.15, 0.5, 0.85, 0.3, 0.7],
    "y": [0.15, 0.35, 0.55, 0.75, 0.9],
}

LABELS = ["中文", "标签测试", "gg4py", "第三行", "混排 A1"]

PALETTE = {"a": "#222222", "b": "#C0392B"}


def build():
    return {
        "data": {**DATA, "label": LABELS, "g": ["a", "b", "a", "b", "a"]},
        "mapping": {"x": "x", "y": "y", "label": "label", "colour": "g"},
        "layers": [{"geom": "text", "params": {"size_pt": 13.0}}],
        "size": [4, 3],
        "limits": {"x": [0, 1], "y": [0, 1]},
        "palette": PALETTE,
    }

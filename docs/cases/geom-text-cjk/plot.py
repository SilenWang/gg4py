"""geom-text / cjk：长中文标签（M0-9 的文字基准，SIL-649 重做）。

R 侧必须用同一份字体（`Noto Sans CJK SC`，pixi 的 `font-ttf-noto-cjk`），且
`svglite` 在 UTF-8 locale 下运行——否则标签会退化成 `.`（见 `docs/notes/diff.md`）。

**为什么是「一条 18 字的左对齐长标签」，而不是五行居中的短标签**
（SIL-649 的实测，数字见 `docs/notes/snapshot-policy.md` §文字类）：

- 跨管线（R svglite vs 我们）的像素差主要来自文字**垂直**度量差：R 的
  `strheight` 与 skia 的 ascent/descent 不同源，两边基线差 0.032 em
  （10 pt ≈ 0.32 px，13 pt ≈ 0.42 px）。它落在每个字形的上下边缘上，与字号
  成正比，靠放大字号压不下去。
- 文字**宽度**误差（要抓的东西）沿字符串累积：左对齐时第 i 个字偏移
  ≈ 2% × i × 字号。标签越长、越靠左锚定，宽度误差换来的像素差越大。

短标签在 2% 的图级阈值下只剩噪声：改之前（五条居中短标签）实测侧把文字推进
+2% 只有 1.47% → 1.50%，压根进不了红区。本 case 的实测是基线 1.15%、
+2% → 1.78%，`tolerance.png` 因此收紧到 1.4%（两侧各留 ~24% 余量）。
"""

DATA = {
    "x": [0.03, 0.03],
    "y": [0.62, 0.28],
    "label": ["中文标签宽度基准校验第二行文本对比", "第三行"],
    "g": ["a", "b"],
}

PALETTE = {"a": "#222222", "b": "#C0392B"}


def build():
    return {
        "data": DATA,
        "mapping": {"x": "x", "y": "y", "label": "label", "colour": "g"},
        "layers": [{"geom": "text", "params": {"size_pt": 10.0, "hjust": 0.0}}],
        "size": [4, 3],
        "limits": {"x": [0, 1], "y": [0, 1]},
        "palette": PALETTE,
    }

"""text / emoji：emoji 与中文/拉丁混排（M1 文字测量）。

同一段文字里 emoji 走 Noto 的 emoji 字面、其余走 Noto Sans CJK SC——run
切分直接决定宽度与字面。参考图由 svglite 写 `<text>`，diff 管线按同一套
run 规则转轮廓（单色 Noto Emoji）。策略见 docs/notes/metrics-ledger.md。
"""

DATA = {
    "x1": [0.04],
    "y1": [0.80],
    "l1": ["smile 😀"],
    "x2": [0.04],
    "y2": [0.55],
    "l2": ["rocket 🚀 check ✅"],
    "x3": [0.04],
    "y3": [0.30],
    "l3": ["中文 😀 混排"],
}


def build():
    return {
        "data": DATA,
        "layers": [
            {
                "geom": "text",
                "mapping": {"x": f"x{i}", "y": f"y{i}", "label": f"l{i}"},
                "params": {
                    "size_pt": 14.0,
                    "hjust": 0.0,
                    "family": "Noto Sans CJK SC",
                },
            }
            for i in (1, 2, 3)
        ],
        "size": [4, 3],
        "limits": {"x": [0, 1], "y": [0, 1]},
        "palette": {},
    }

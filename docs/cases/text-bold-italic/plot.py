"""text / bold-italic：同一字族的四个真实字面（M1 文字测量）。

族用 `Noto Sans`：它的 regular / bold / italic / bold-italic 都在受管字体里
（`NotoSans-VF.ttf` + `NotoSans-Italic-VF.ttf`，可变字体用 `wght` 轴）。
每条标签左对齐、长度够长——字面选错（粗体落到常规）会让推进整段偏窄，
像素差沿字符串累积；短标签抓不住。
"""

DATA = {
    "x1": [0.04],
    "y1": [0.84],
    "l1": ["Regular text sample"],
    "x2": [0.04],
    "y2": [0.62],
    "l2": ["Bold text sample"],
    "x3": [0.04],
    "y3": [0.40],
    "l3": ["Italic text sample"],
    "x4": [0.04],
    "y4": [0.18],
    "l4": ["Bold italic sample"],
}


def _layer(suffix: str, fontface: str) -> dict:
    return {
        "geom": "text",
        "mapping": {"x": f"x{suffix}", "y": f"y{suffix}", "label": f"l{suffix}"},
        "params": {
            "size_pt": 12.0,
            "hjust": 0.0,
            "family": "Noto Sans",
            "fontface": fontface,
        },
    }


def build():
    return {
        "data": DATA,
        "layers": [
            _layer("1", "plain"),
            _layer("2", "bold"),
            _layer("3", "italic"),
            _layer("4", "bold.italic"),
        ],
        "size": [4, 3],
        "limits": {"x": [0, 1], "y": [0, 1]},
        "palette": {},
    }

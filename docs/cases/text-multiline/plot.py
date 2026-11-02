"""text / multiline：`\\n` 换行 + 整块 hjust/vjust（M1 文字测量）。

第一行中文、第二行中英混排、第三行中文：逐行宽度都要与 R 的 `stringWidth`
对得上；行距按 R 4.5.3 实测的 1.2 × lineheight × fontsize（默认 1.44×）。
第二条是两行居中标签，用来看整块锚点（不是单行锚点）。
"""

DATA = {
    "x1": [0.03],
    "y1": [0.72],
    "l1": ["多行文本第一行\n第二行 mixed Latin 文字\n第三行"],
    "x2": [0.55],
    "y2": [0.30],
    "l2": ["two lines\nsecond line"],
}


def build():
    return {
        "data": DATA,
        "layers": [
            {
                "geom": "text",
                "mapping": {"x": "x1", "y": "y1", "label": "l1"},
                "params": {
                    "size_pt": 10.0,
                    "hjust": 0.0,
                    "vjust": 0.5,
                    "family": "Noto Sans CJK SC",
                },
            },
            {
                "geom": "text",
                "mapping": {"x": "x2", "y": "y2", "label": "l2"},
                "params": {
                    "size_pt": 10.0,
                    "hjust": 0.5,
                    "vjust": 0.5,
                    "family": "Noto Sans CJK SC",
                },
            },
        ],
        "size": [4, 3],
        "limits": {"x": [0, 1], "y": [0, 1]},
        "palette": {},
    }

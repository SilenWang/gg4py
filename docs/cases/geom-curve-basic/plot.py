"""geom-curve / basic：两条二次拐弯的曲线（SIL-599 的集成级负向验证）。

这条 case 存在的理由不是「多一张图」，而是**让设备级的 curve 镜像 bug 能被矩阵
抓到**：`ggskia` 的 `_draw_curve` 必须先把页面坐标翻到 R 坐标求控制点，否则拐角
会跑到弦线的另一侧（SIL-636）。把那个翻转改回镜像版，本 case 的图级差异会远超
2%，`pixi run cases:matrix` 直接红。

R 参考由 `tools/refs/cases_ref.R` 的 `geom-curve-basic` 段生成。`geom_curve` 的
`curvature = 0.5`、`angle = 90`、`ncp = 5`、`linewidth = 1/.pt` 与这里一一对应。
"""

DATA = {
    "x": [0.15, 0.15],
    "y": [0.2, 0.8],
    "xend": [0.85, 0.85],
    "yend": [0.75, 0.25],
    "g": ["a", "b"],
}

PALETTE = {"a": "#4C78A8", "b": "#E45756"}


def build():
    return {
        "data": DATA,
        "mapping": {"x": "x", "y": "y", "xend": "xend", "yend": "yend", "colour": "g"},
        "layers": [
            {
                "geom": "curve",
                "params": {"curvature": 0.5, "angle": 90, "ncp": 5, "lwd": 1.0},
            }
        ],
        "size": [4, 3],
        "limits": {"x": [0, 1], "y": [0, 1]},
        "palette": PALETTE,
    }

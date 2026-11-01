"""geom-point / basic：两列数值 + 一列分组，theme_void 的散点。

R 参考由 `tools/refs/cases_ref.R` 的 `geom-point-basic` 段生成（ggplot2 4.0.3 +
svglite），两边共用同一份数据、limits、调色板与点大小。

25 个点是有意的：SIL-599 的验收要求「人为偏移 2 像素必须判红」。图级差异的分母
是整张画布，点太少时 2 px 的位移够不到 2%——这不是阈值松，是画面本来就没多少
墨。案例库的基准图要能当判据用，所以散点铺满面板。
"""

DATA = {
    "x": [0.1, 0.3, 0.5, 0.7, 0.9] * 5,
    "y": [
        0.12,
        0.12,
        0.12,
        0.12,
        0.12,
        0.31,
        0.31,
        0.31,
        0.31,
        0.31,
        0.50,
        0.50,
        0.50,
        0.50,
        0.50,
        0.69,
        0.69,
        0.69,
        0.69,
        0.69,
        0.88,
        0.88,
        0.88,
        0.88,
        0.88,
    ],
    "g": ["a", "b", "a", "b", "a"] * 5,
}

#: ggplot2 的 hue_pal 前两位（R 侧 `scale_colour_manual(values = ...)` 同值）。
PALETTE = {"a": "#F8766D", "b": "#00BA38"}


def build():
    return {
        "data": DATA,
        "mapping": {"x": "x", "y": "y", "colour": "g"},
        "layers": [{"geom": "point", "params": {"size_pt": 9.0}}],
        "size": [4, 3],
        "limits": {"x": [0, 1], "y": [0, 1]},
        "palette": PALETTE,
    }

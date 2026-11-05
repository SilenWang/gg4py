"""示例 7 / 9 · 等值线填充：contourpy 的 wasm 轮子按需下载。

`contourpy` 只在 `stat_contour*` 真正被调用时才 import，静态扫描看不见它，
所以这里显式写进 `needs`——否则浏览器会先报「没有 contourpy」。
"""

from ggcore.plot import aes, geom_contour_filled, ggplot, labs, theme_minimal
from ggio.frame import to_column_table

needs = ["numpy", "contourpy"]

GRID = {
    "x": [x for _ in range(1, 9) for x in range(1, 9)],
    "y": [y for y in range(1, 9) for _ in range(1, 9)],
    "z": [
        (x - 4.5) ** 2 / 6.0 + (y - 4.5) ** 2 / 9.0 + 0.35 * (x - 4.5) * (y - 4.5) / 4.0
        for y in range(1, 9)
        for x in range(1, 9)
    ],
}


def build():
    p = (
        ggplot(to_column_table(GRID), aes(x="x", y="y", z="z"))
        + geom_contour_filled(bins=6)
        + labs(
            title="Filled contours",
            subtitle="contourpy geometry, computed in wasm",
            x="x",
            y="y",
        )
        + theme_minimal()
    )
    return {"plot": p, "size": [5.0, 3.5]}

"""示例 2 / 3：等值线填充（`needs` 里多一个 contourpy —— 只在跑这一页时下载）。

contourpy 是 ggcore 唯一的 C++ 扩展依赖，也是「内核能进浏览器」最需要实测的一段：
桌面上它来自 pixi 的轮子，浏览器里来自 pyodide 的 wasm 轮子，两边**同一个版本**
（`pixi.toml` 的 `<1.4` 就是为此）。页面只在切到这一页时才 `loadPackage("contourpy")`。
"""

from ggcore.plot import aes, geom_contour_filled, ggplot, labs, theme_minimal
from ggio.frame import to_column_table

needs = ["numpy", "contourpy"]

#: 5×5 的确定性网格（`stat_contour` 的经典夹具，与门禁里的同一份数字）。
GRID = {
    "x": [x for _ in range(1, 6) for x in range(1, 6)],
    "y": [y for y in range(1, 6) for _ in range(1, 6)],
    "z": [x * 0.5 + y for y in range(1, 6) for x in range(1, 6)],
}


def build():
    p = (
        ggplot(to_column_table(GRID), aes(x="x", y="y", z="z"))
        + geom_contour_filled(bins=4)
        + labs(
            title="Filled contours", subtitle="contourpy geometry, computed in wasm", x="x", y="y"
        )
        + theme_minimal()
    )
    return {"plot": p, "size": [5.0, 3.6]}

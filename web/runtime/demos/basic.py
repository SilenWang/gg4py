"""示例 1 / 3：散点 + 折线（只依赖 numpy，`needs` 里也只写 numpy）。

每个示例都是「一页代码」的形状（与 `docs/cases/*/plot.py` 同一套契约）：

    needs = [...]      # 这一段代码要用到的 Pyodide 包（页面按需懒加载）
    build() -> dict     # {"plot": ggplot(...), "size": [宽 in, 高 in]}

桌面端（`tools/pyodide/check_runtime.py`）用**同一个文件**跑一遍，把 IR 的 sha256
与浏览器里算出来的比：同一段脚本、同一份 ggcore，两端必须逐字节相同。

文字刻意用 ASCII：受管 CJK 字面（`NotoSansCJKsc-VF.ttf`）是 35 MB，进了首屏就再也
谈不上「首访 4G ≤ 12 s」。页面只加载实际用到的拉丁字面（Arimo 325 KB）。CJK 的
排版与度量由 `pixi run viewer:cases` 的像素对拍覆盖，不靠这一页。
"""

from ggcore.plot import aes, geom_line, geom_point, ggplot, labs, theme_minimal
from ggio.frame import to_column_table

#: 这一段代码要用到的包。页面**只**在这里声明的范围内加载：没写 pandas 就不下载。
needs = ["numpy"]

DATA = {
    "x": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    "y": [2.1, 2.9, 4.2, 4.8, 6.1, 6.0, 7.4, 8.1, 8.0, 9.6, 10.2, 10.9],
    "group": ["a"] * 6 + ["b"] * 6,
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="group"))
        + geom_point(size=2.2)
        + geom_line()
        + labs(title="ggcore inside the browser", subtitle="points + line (numpy)", x="x", y="y")
        + theme_minimal()
    )
    return {"plot": p, "size": [5.0, 3.6]}

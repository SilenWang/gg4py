"""`pixi run ggsave` 的示例 plot 模块（M1-12 的验收图）。

```bash
pixi run ggsave tools/examples/ggsave_demo.py:plot /tmp/demo.png
pixi run ggsave tools/examples/ggsave_demo.py:plot /tmp/demo.svg --width 10 --units cm
pixi run ggsave tools/examples/ggsave_demo.py:plot /tmp/demo.ir.json
```

一张带标题、图例（`colour`）与分面（`facet_wrap`）的散点图：三份产物的差异
（PNG 的像素、SVG 的轮廓、PDF 的页面）都能在这张图上看到。数据由固定种子的
`numpy` 生成，所以同一台机器上两次输出的字节一致（`tests/test_io.py` 守着）。
"""

from __future__ import annotations

import numpy as np

from ggcore.plot import aes, facet_wrap, geom_point, ggplot, labs
from ggio.frame import from_dict

__all__ = ["data", "plot"]


def data() -> object:
    """固定的 90 行数据：两张分面（`panel`）× 三个颜色组（`group`）。"""
    rng = np.random.default_rng(20251102)
    size = 90
    return from_dict(
        {
            "x": rng.normal(size=size),
            "y": rng.normal(size=size),
            "group": np.array(["a", "b", "c"])[rng.integers(0, 3, size)],
            "panel": np.array(["早期", "晚期"])[rng.integers(0, 2, size)],
        }
    )


def plot() -> ggplot:
    """带图例的分面散点图（`ggsave` 的验收对象）。"""
    return (
        ggplot(data(), aes(x="x", y="y", colour="group"))
        + geom_point(size=2.0)
        + facet_wrap("panel")
        + labs(title="ggsave 冒烟", subtitle="两个分面 × 三个颜色组", x="x 值", y="y 值")
    )

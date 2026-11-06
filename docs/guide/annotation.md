# 注释：`annotate()` 与 `annotation_*()`

注释是「用向量加一层」：不给映射、不进图例、不参与分组。名字与上游一致。

## 1. `annotate()`

<!-- no-run: 函数签名片段，不是可执行示例（可跑的用法见 §1） -->
```python
annotate(geom, x=..., y=..., **params)
```

三点语义照 ggplot2 4.0.3：

1. 位置美学（`x` / `y` / `xmin` / `xmax` / `ymin` / `ymax` / `xend` / `yend`）进
   **数据 + 映射**，所以参与标度训练、会撑开范围；
2. 其它参数（`colour` / `size` / `label` / `fill` …）是**设值**，不进图例；
3. `stat = identity`、`position = identity`、`inherit_aes = FALSE`、
   `show_legend = FALSE`。

长度规则：所有参数最多只有一个长度 > 1 的值（其余标量广播），否则报错。

```python
from ggcore.plot import aes, annotate, geom_point, ggplot, labs
from ggcore.theme import theme_minimal
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3, 4], "y": [2.0, 1.5, 4.2, 3.1]}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y"))
    + geom_point(size=3, colour="#4C78A8")
    + annotate("rect", xmin=1.5, xmax=2.5, ymin=1.0, ymax=3.0, alpha=0.18, fill="#4C78A8")
    + annotate("text", x=2.0, y=4.5, label="highlight", size=4, colour="#E45756")
    + annotate("segment", x=1.0, y=1.0, xend=4.0, yend=4.5, linetype=2, colour="grey40")
    + labs(title="annotate(): rect + text + segment", x="x", y="y")
    + theme_minimal()
)
```

可以用字符串指定 geom（`"point"` / `"text"` / `"label"` / `"rect"` / `"tile"` /
`"segment"` / `"curve"` / `"line"` / `"path"` / `"polygon"` / `"ribbon"` …），也可以
传 `Geom` 对象。位置参数按 geom 的需要给：

| geom | 位置参数 |
| --- | --- |
| `"point"` / `"text"` / `"label"` | `x` `y` |
| `"rect"` | `xmin` `xmax` `ymin` `ymax` |
| `"tile"` | `x` `y`（可加 `width` / `height`） |
| `"segment"` / `"curve"` | `x` `y` `xend` `yend` |
| `"line"` / `"path"` | `x=[...]` `y=[...]` |
| `"polygon"` / `"ribbon"` | `x=[...]` `y=[...]`（或 `ymin` / `ymax`） |

```python
from ggcore.plot import aes, annotate, geom_point, ggplot, labs
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3, 4], "y": [1.0, 2.6, 2.1, 4.2]}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y"))
    + geom_point(size=2.6, colour="#4C78A8")
    + annotate("line", x=[1, 2, 3, 4], y=[3.5, 3.2, 3.8, 4.6], colour="#E45756", linewidth=1.0)
    + annotate("polygon", x=[2.0, 3.0, 2.5], y=[0.8, 0.8, 1.8], fill="#FDE725", alpha=0.5)
    + annotate("point", x=4.0, y=4.2, size=6, colour="#E45756")
    + labs(title="annotate() with vectors", x="x", y="y")
)
```

**不支持** `annotate("abline" / "hline" / "vline", ...)`：上游同样建议直接用
`geom_abline()` / `geom_hline()` / `geom_vline()`；gg4py 会给一条 warning，然后
按普通图层处理。

## 2. `annotation_logticks()`

对数轴的细刻度（不是标签）：

```python
from ggcore.plot import (
    aes,
    annotation_logticks,
    geom_point,
    ggplot,
    labs,
    scale_y_log10,
)
from ggcore.theme import theme_minimal
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3, 4, 5], "y": [1.0, 10.0, 100.0, 1000.0, 10000.0]}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y"))
    + geom_point(size=3, colour="#4C78A8")
    + scale_y_log10()
    + annotation_logticks(sides="l", base=10)
    + labs(title="annotation_logticks(sides = 'l')", x="x", y="y")
    + theme_minimal()
)
```

参数：`base` / `sides`（`"bl"` 这类）/ `scaled` / `short` / `mid` / `long`（长度，
cm 或 `unit`）/ `colour` / `linewidth` / `linetype` / `alpha`。`outside=True` 把
刻度画到轴外。它必须在 `scale_*_log10()` 之后加（标度决定刻度位置）。

## 3. `annotation_borders()`（与已废弃的 `borders()`）

把内置的一份地图边界画成多边形，等价于手工写
`annotate("polygon", x=, y=, group=)`：

```python
from ggcore.plot import annotation_borders, ggplot, labs, theme_void

p = (
    ggplot()
    + annotation_borders("state", "utah", fill="#D9D9D9", colour="white", linewidth=0.5)
    + theme_void()
    + labs(title='annotation_borders("state", "utah")')
)
```

本仓**只内置**了 `("state", "utah")` 与 `("usa", ".")` 两份地图数据（`maps` 是外部
数据包，完整移植不在范围内）。别的区域会报 `NotImplementedError` 并提示改用
`annotate("polygon", ...)` 自备坐标。

`borders()` 是上游 4.0 起软废弃的别名，调用会发 `DeprecationWarning`；新代码用
`annotation_borders()`。

## 4. 与上游的差异

- `annotate()` 的 geom 名用字符串；`annotate(geom_point())` 这种传对象也收。
- 只内置两份地图数据（见上）。
- `annotate("hline")` 等三条不给支持（warning + 按普通图层），用对应 `geom_*()`。
- 注释参与标度训练（会撑开面板范围），与上游一致；不想改变范围就把值放在已有
  范围内，或用 `coord_cartesian()` 裁视图。

# `facet_*`：分面

分面把数据按一个或多个离散列切成小面板，每个面板有自己的标度（可选）、条带标签
（strip）与轴。三个函数与上游同名：

| 函数 | 说明 |
| --- | --- |
| `facet_null()` | 不分面（默认）；给 `facet_grid()` 留空位用 |
| `facet_wrap(facets, ...)` | 按一个变量（或 `[a, b]`）折行排列 |
| `facet_grid(rows=None, cols=None, ...)` | 行 × 列网格 |

`facets` 用**字符串**（或字符串列表），不是 R 的公式：`facet_wrap("class")`、
`facet_grid(rows="drv", cols="year")`。`facet_wrap("~ class")` 的公式写法不支持
（`~` 会被当成表达式报错）。

## 1. `facet_wrap`

| 参数 | 缺省 | 说明 |
| --- | --- | --- |
| `ncol` / `nrow` | 自动 | 列数 / 行数（二选一） |
| `dir` | `"h"` | 填充方向：`"h"` / `"v"` |
| `scales` | `"fixed"` | `"fixed"` / `"free"` / `"free_x"` / `"free_y"` |
| `labeller` | `"label_value"` | 见 §4 |
| `drop` | `True` | 丢弃没有数据的水平 |
| `as.table` | `True` | `True` 从左上开始排，`False` 从左下 |
| `strip.position` | `"top"` | `"top"` / `"bottom"` / `"left"` / `"right"`（其它值报错） |

```python
from gg4py import (
    aes,
    facet_wrap,
    geom_point,
    geom_smooth,
    ggplot,
    labs,
    theme_minimal,
    to_column_table,
)

DATA = {
    "x": [1, 2, 3, 4, 1, 2, 3, 4, 1, 2, 3, 4, 1, 2, 3, 4],
    "y": [1.1, 2.3, 2.0, 3.4, 2.2, 1.6, 2.8, 2.4, 3.0, 4.1, 3.6, 5.0, 0.9, 1.8, 1.5, 2.2],
    "drv": ["4"] * 4 + ["f"] * 4 + ["r"] * 4 + ["4"] * 4,
    "panel": ["a"] * 4 + ["b"] * 4 + ["c"] * 4 + ["d"] * 4,
}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y"))
    + geom_point(size=2.2, colour="#4C78A8")
    + geom_smooth(method="lm", se=False, colour="#E45756", linewidth=0.9)
    + facet_wrap("panel", ncol=2)
    + labs(title="facet_wrap('panel', ncol = 2)", x="x", y="y")
    + theme_minimal()
)
```

## 2. `facet_grid`

行 / 列变量可以只给一个（另一个方向留空）或都给：

```python
from gg4py import aes, facet_grid, geom_point, ggplot, labs, theme_minimal, to_column_table

DATA = {
    "x": [1, 2, 3, 4, 1, 2, 3, 4, 1, 2, 3, 4, 1, 2, 3, 4],
    "y": [1.1, 2.3, 2.0, 3.4, 2.2, 1.6, 2.8, 2.4, 3.0, 4.1, 3.6, 5.0, 0.9, 1.8, 1.5, 2.2],
    "drv": ["4"] * 8 + ["f"] * 8,
    "year": ["1999"] * 4 + ["2008"] * 4 + ["1999"] * 4 + ["2008"] * 4,
}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y"))
    + geom_point(size=2.2, colour="#4C78A8")
    + facet_grid(rows="drv", cols="year")
    + labs(title="facet_grid(rows = 'drv', cols = 'year')", x="x", y="y")
    + theme_minimal()
)
```

`facet_grid(rows=..., cols=...)` 的关键字名就是这两个（R 的 `facet_grid(drv ~ year)`
公式写法不支持）。`switch="x"` / `"y"` / `"both"` 把条带换到另一侧；`space="free"`
只在**两维都 free** 时允许（`scales="free"` + `space="free"`），`free_x` / `free_y`
配 `space` 会报错（与上游 4.0.3 实测一致）。

## 3. 自由标度

```python
from gg4py import aes, facet_wrap, geom_point, ggplot, labs, to_column_table

DATA = {
    "x": [1, 2, 3, 4, 1, 2, 3, 4],
    "y": [1.0, 2.0, 3.0, 4.0, 100.0, 140.0, 120.0, 180.0],
    "panel": ["low"] * 4 + ["high"] * 4,
}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y"))
    + geom_point(size=2.6, colour="#4C78A8")
    + facet_wrap("panel", scales="free_y", ncol=2)
    + labs(title="scales = 'free_y'", x="x", y="y")
)
```

`"free"` 两个方向都放开；每个面板各自训练标度、各自画断点。固定标度 + `coord_fixed`
与自由标度 + 固定纵横比是两套语义，混用会报错。

## 4. 条带标签

| 写法 | 效果 |
| --- | --- |
| `labeller="label_value"` | 只写值（缺省） |
| `labeller="label_both"` | `变量: 值` |
| `labeller="label_context"` | 单变量同 value，多变量同 both |
| `labeller="label_parsed"` | 值当 plotmath 表达式（上下标） |
| `labeller=labeller(g={...})` | 逐变量映射 |
| `labeller=lambda labels: dict` | 自定义函数，返回 `{变量: [标签…]}` |

```python
from gg4py import (
    aes,
    facet_wrap,
    geom_point,
    ggplot,
    labeller,
    labs,
    theme_minimal,
    to_column_table,
)
from ggcore.theme import element_text, theme

DATA = {
    "x": [1, 2, 3, 4, 1, 2, 3, 4],
    "y": [1.0, 2.6, 2.1, 4.2, 2.2, 1.6, 2.8, 2.4],
    "panel": ["a", "a", "a", "a", "b", "b", "b", "b"],
}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y"))
    + geom_point(size=2.4, colour="#4C78A8")
    + facet_wrap("panel", ncol=2, labeller=labeller(panel={"a": "Alpha", "b": "Beta"}))
    + labs(title="labeller(...) 逐变量覆盖", x="x", y="y")
    + theme_minimal()
    + theme(**{"strip.text": element_text(face="bold", size=9)})
)
```

自定义函数的返回值必须是 `{变量名: [标签…]}`（长度等于该变量的水平数），返回
列表或字符串会报 `FacetError`。

## 5. 与上游的差异

- `facets` 是字符串 / 列表，不是公式；`vars()` 也没有。
- `strip.position` 支持 `"top"` / `"bottom"` / `"left"` / `"right"`（SIL-871）；
  换边后的 strip 在 `strip.placement = "outside"` 下按 `"inside"` 画（与
  `facet_grid(switch=)` 同一口径）。
- `facet_grid(margins=)` 未实现。
- 极坐标 / 放射坐标 + `space="free"` 会报错（上游自身在 4.0.3 里也失败）。
- 带点的参数名（`as.table`、`strip.position`）用 `**{"as.table": False}` 传。

# `scale_*`：标度

标度回答四件事：**范围**（limits + expand）、**断点**（breaks）、**标签**
（labels）、以及**数据值 → 美学值**的映射（调色板 / 大小范围 / 形状表）。
位置标度之外，`colour` / `fill` / `size` / `shape` / `alpha` / `linetype` /
`linewidth` 各有一套。

函数名与 ggplot2 4.0.3 一致（131 个 `NAMESPACE` 导出都有对应入口：130 个在注册表里，
`scale_type()` 是函数不是组件；`colour` /
`color` 两套拼写都注册）。完整按族清单见 [`r-to-python.md`](r-to-python.md) §6。

## 1. 位置标度

| 函数 | 用途 |
| --- | --- |
| `scale_x_continuous()` / `scale_y_continuous()` | 连续位置 |
| `scale_x_discrete()` / `scale_y_discrete()` | 离散位置（顺序由 `limits` 定） |
| `scale_x_log10()` / `scale_x_sqrt()` / `scale_x_reverse()` | 变换的糖 |
| `scale_x_binned()` | 分箱位置（图例用 coloursteps 那种风格） |
| `scale_x_date()` / `scale_x_datetime()` / `scale_x_time()` | 日期 / 时间 |
| `scale_x_continuous(trans="log10")` | 任意已实现的变换：`log10` / `log2` / `log` / `sqrt` / `reverse` / `pseudo_log`；复合变换用 `transform_compose(...)` |

通用参数：

| 参数 | 含义 |
| --- | --- |
| `name` | 轴标题（等价于 `labs(x=...)`，后加的赢） |
| `limits` | 数据范围（连续）或水平顺序（离散）；越界值默认变 NA |
| `breaks` | 断点；`None` 用算法自动挑，`[]` 关闭 |
| `labels` | 与 `breaks` 等长的字符串；`None` 用默认格式 |
| `expand` | 面板留白；连续缺省 `(0.05, 0.05)`（乘性），离散缺省 `(0.6, 0.6)`（加性） |
| `oob` | 越界策略：`"censor"`（默认，变 NA）/ `"squish"`（压到边界） |
| `na_value` | 缺失值的颜色（颜色类标度） |
| `guide` | `"none"` / `"legend"` / `"colourbar"` / `guide_*(...)` |
| `sec_axis` | 次轴：`sec_axis(fn, name=...)` / `dup_axis(...)` |

```python
from ggcore.plot import aes, geom_point, ggplot, labs, scale_x_continuous, scale_y_continuous
from ggcore.theme import theme_minimal
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3, 4], "y": [2.0, 1.5, 4.2, 3.1]}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y"))
    + geom_point(size=3, colour="#4C78A8")
    + scale_x_continuous(
        name="x (units)",
        limits=(0, 5),
        breaks=[0, 1, 2, 3, 4, 5],
        labels=["0", "1", "2", "3", "4", "5"],
        expand=(0, 0.1),
    )
    + scale_y_continuous(limits=(1, 5), breaks=[1, 2, 3, 4, 5], oob="squish")
    + labs(title="limits, breaks, labels, expand, oob")
    + theme_minimal()
)
```

离散顺序（不想用 `Categorical` 时）：

```python
from ggcore.plot import aes, geom_col, ggplot, labs, scale_x_discrete
from ggcore.theme import theme_minimal
from ggio.frame import to_column_table

DATA = {"class": ["suv", "compact", "midsize"], "n": [18.0, 12.0, 9.0]}

p = (
    ggplot(to_column_table(DATA), aes(x="class", y="n"))
    + geom_col(fill="#4C78A8")
    + scale_x_discrete(limits=["compact", "midsize", "suv"], labels=["compact", "midsize", "SUV"])
    + labs(title="scale_x_discrete(limits = ...)", x="class", y="n")
    + theme_minimal()
)
```

变换：

```python
from ggcore.plot import aes, geom_line, geom_point, ggplot, labs, scale_x_log10, scale_y_log10
from ggio.frame import to_column_table

DATA = {
    "x": [1.0, 10.0, 100.0, 1000.0],
    "y": [1.0, 4.0, 16.0, 64.0],
}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y"))
    + geom_line(linewidth=1.0, colour="#4C78A8")
    + geom_point(size=2.6)
    + scale_x_log10()
    + scale_y_log10()
    + labs(title="log10 两侧", x="x", y="y")
)
```

注意：变换在**训练之前**发生，所以 `limits` / `breaks` 都在**变换后的空间**里
（`scale_x_log10()` 下，数据 1/10/100 的范围是 0..2；想框住 1..1000 就写
`limits=(0, 3)`）。日期标度的 `breaks` 也是数值：`Date` 是「自 1970-01-01 起的
天」，`POSIXct` 是秒。口径全文见 `docs/notes/scales.md`。

## 2. 颜色与填充

| 需求 | 函数 |
| --- | --- |
| 连续 → 双色渐变 | `scale_colour_gradient(low=, high=)` |
| 连续 → 三色渐变 | `scale_colour_gradient2(low=, mid=, high=, midpoint=)` |
| 连续 → 自定义色板 | `scale_colour_gradientn(colours=[...])` |
| 连续 → 分步色阶 | `scale_colour_steps(n_bins=)` / `steps2` / `stepsn` |
| 分类 → 等距色相 | `scale_colour_hue()` / `scale_colour_discrete()` |
| 分类 → 内置色板 | `scale_colour_brewer(palette="Dark2")` |
| 连续 → ColourBrewer | `scale_colour_distiller(palette="Spectral")` |
| viridis | `scale_colour_viridis_c()` / `_d` / `_b`（`option=` `direction=`） |
| 灰度 | `scale_colour_grey(start=, end=)` |
| 手动指定 | `scale_colour_manual(values=[...] 或 {水平: 颜色})` |
| 数据里就是颜色 | `scale_colour_identity()` |
| 分箱 | `scale_colour_binned()` / `scale_colour_fermenter(palette=)` |

```python
from ggcore.plot import aes, geom_point, ggplot, labs, scale_colour_gradient2
from ggcore.theme import theme_minimal
from ggio.frame import to_column_table

DATA = {
    "x": [1, 2, 3, 4, 5, 6],
    "y": [2.0, 1.5, 4.2, 3.1, 5.4, 2.2],
    "z": [-1.0, 0.4, 1.2, 2.6, -0.8, 1.9],
}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y", colour="z"))
    + geom_point(size=4)
    + scale_colour_gradient2(low="#2166ac", mid="white", high="#b2182b", midpoint=0.0)
    + labs(title="scale_colour_gradient2(midpoint = 0)", x="x", y="y")
    + theme_minimal()
)
```

```python
from ggcore.plot import aes, geom_col, ggplot, labs, scale_fill_brewer
from ggcore.theme import theme_minimal
from ggio.frame import to_column_table

DATA = {
    "class": ["compact", "midsize", "suv", "compact", "midsize", "suv"],
    "year": ["1999", "1999", "1999", "2008", "2008", "2008"],
    "n": [12.0, 9.0, 15.0, 14.0, 11.0, 18.0],
}

p = (
    ggplot(to_column_table(DATA), aes(x="class", y="n", fill="year"))
    + geom_col(position="dodge", width=0.75)
    + scale_fill_brewer(palette="Set2")
    + labs(title="scale_fill_brewer(palette = 'Set2')", x="class", y="n")
    + theme_minimal()
)
```

```python
from ggcore.plot import aes, geom_point, ggplot, labs, scale_colour_manual
from ggcore.theme import theme_minimal
from ggio.frame import to_column_table

DATA = {
    "x": [1, 2, 3, 4],
    "y": [2.0, 1.5, 4.2, 3.1],
    "g": ["a", "b", "a", "b"],
}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y", colour="g"))
    + geom_point(size=3.4)
    + scale_colour_manual(values=["#E45756", "#4C78A8"])  # 顺序 = 水平顺序
    + labs(title="scale_colour_manual(values = [...])", x="x", y="y")
    + theme_minimal()
)
```

`values` 也可以是 `{水平: 颜色}`（按名字对齐，不受顺序影响）。颜色认 `#RRGGBB`
与 R 颜色名；写错颜色名在构图期报错并列出可用的名字。

## 3. 大小、形状、透明度、线

| 美学 | 标度 | 关键参数 |
| --- | --- | --- |
| `size` | `scale_size()` / `scale_size_area()` / `scale_size_binned()` / `scale_radius()` | `range=` `max_size=` |
| `shape` | `scale_shape()` / `scale_shape_manual()` | `values=` 是 **pch 码**（0–25） |
| `alpha` | `scale_alpha()` / `scale_alpha_binned()` | `range=` |
| `linetype` | `scale_linetype()` / `scale_linetype_manual()` | `values=` 是 1–6 或名字 |
| `linewidth` | `scale_linewidth()` | `range=` |

```python
from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    labs,
    scale_alpha_continuous,
    scale_shape_manual,
    scale_size_area,
)
from ggcore.theme import theme_minimal
from ggio.frame import to_column_table

DATA = {
    "x": [1, 2, 3, 4, 5],
    "y": [2.0, 1.5, 4.2, 3.1, 5.4],
    "n": [1.0, 3.0, 5.0, 7.0, 9.0],
    "g": ["a", "b", "a", "b", "a"],
}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y", size="n", shape="g", alpha="n"))
    + geom_point(colour="#4C78A8")
    + scale_size_area(max_size=10)
    + scale_shape_manual(values=[16, 17])
    + scale_alpha_continuous(range=(0.35, 1.0))
    + labs(title="size / shape / alpha scales", x="x", y="y")
    + theme_minimal()
)
```

## 4. 日期

```python
import datetime as dt

from ggcore.plot import aes, geom_line, geom_point, ggplot, labs, scale_x_date
from ggio.frame import to_column_table

DATA = {
    "date": [dt.date(2020, month, 1) for month in range(1, 7)],
    "value": [12.0, 15.0, 13.5, 19.0, 22.0, 21.0],
}

p = (
    ggplot(to_column_table(DATA), aes(x="date", y="value"))
    + geom_line(linewidth=1.0, colour="#4C78A8")
    + geom_point(size=2.4)
    + scale_x_date(date_breaks="1 month", date_labels="%b", name=None)
    + labs(title="scale_x_date(date_breaks = '1 month')", y="value")
)
```

`date_breaks` 支持 `"1 day"` / `"1 week"` / `"1 month"` / `"1 year"` 这类单位；
`date_labels` 是 `strftime` 风格。显式 `breaks` 要传数值（天 / 秒），不是
`datetime.date`：

```python
import datetime as dt

from ggcore.plot import aes, geom_line, ggplot, scale_x_date
from ggio.frame import to_column_table

DATA = {"date": [dt.date(2020, month, 1) for month in range(1, 5)], "value": [1.0, 3.0, 2.0, 5.0]}

p = (
    ggplot(to_column_table(DATA), aes(x="date", y="value"))
    + geom_line()
    + scale_x_date(breaks=[18262, 18383], labels=["Q1", "Q2"])  # 自 1970-01-01 起的天
)
```

## 5. 跨美学与通用标度

`scale_discrete_manual()` / `scale_discrete_identity()` / `scale_continuous_identity()`
用 `aesthetics=` 指定作用的美学：

```python
from ggcore.plot import aes, geom_point, ggplot, labs, scale_discrete_manual
from ggio.frame import to_column_table

DATA = {
    "x": [1, 2, 3, 4],
    "y": [2.0, 1.5, 4.2, 3.1],
    "g": ["a", "b", "a", "b"],
}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y", colour="g"))
    + geom_point(size=3.4)
    + scale_discrete_manual(aesthetics="colour", values=["#E45756", "#4C78A8"])
    + labs(title="scale_discrete_manual(aesthetics = 'colour')", x="x", y="y")
)
```

## 6. 边界

- `limits` 越界默认变 NA（`oob="censor"`），构图期会给一条 `BuildWarning:
  Removed N rows ...`；要和上游 R 一样「裁掉并告知」，不要静默改数据。
- 离散标度的 `NA` 本身是一个水平（排在最后），想让它有颜色就设 `na_value=`。
- `scale_shape_manual(values=...)` 收 pch 码（0–25）；写形状名给 `geom_point(shape=)`
  用（`"circle"` / `"triangle"` 等），标度里统一用码。
- 同一个美学被加两次标度：后加的赢（与 ggplot2 的顺序语义一致）。
- 未实现的参数（例如某些 `sec.axis` 组合）在**构造时**就报错并点名，不会拖到
  构图期或画出悄悄错位的图。

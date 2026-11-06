# `aes`：映射

`aes()` 把**数据列**接到**美学**（aesthetic）上。ggplot2 里它是 `aes(x = displ)`；
gg4py 里值是**字符串表达式**，列名就是表达式里的名字：

```python
from ggcore.plot import aes, geom_point, ggplot, labs
from ggcore.theme import theme_minimal
from ggio.frame import to_column_table

DATA = {
    "displ": [1.8, 2.0, 2.4, 3.0, 4.0, 5.3],
    "hwy": [29.0, 30.0, 27.0, 25.0, 20.0, 16.0],
    "class": ["compact", "compact", "midsize", "midsize", "suv", "suv"],
}

p = (
    ggplot(to_column_table(DATA), aes(x="displ", y="hwy", colour="class"))
    + geom_point(size=2.5)
    + labs(title="mapping class to colour", x="displacement", y="highway")
    + theme_minimal()
)
```

`colour="class"` 是**映射**（按列取值、自动出图例）；`geom_point(colour="red")` 是
**设值**（所有点同一个颜色、不进图例）。这两件事在 gg4py 里分开写，与 R 一致。

## 1. 能映射的美学

| 类别 | 名字 |
| --- | --- |
| 位置 | `x` `y` `xmin` `xmax` `ymin` `ymax` `xend` `yend` |
| 颜色 / 填充 | `colour`（`color` 自动标准化） `fill` `alpha` |
| 形状 / 大小 / 线 | `shape` `size` `linewidth` `linetype` `stroke` |
| 文本 | `label` `hjust` `vjust` `angle` |
| 统计 | `weight` `sample` `z` `group` |
| 空间 | `geometry`（`geom_sf` 族） |

别名照上游 `standardise_aes_names()`：`color` → `colour`、`col` → `colour`、
`pch` → `shape`、
`cex` → `size`、`lty` → `linetype`、`lwd` → `linewidth`、`srt` → `angle`、
`adj` → `hjust`、`bg` → `fill`、`fg` → `colour`、`min` → `ymin`、`max` → `ymax`。
同一个映射里 `color` 与 `colour` 各写一次会直接报错，不会静默丢一个。

## 2. 表达式

值是表达式，不是只能写列名：

```python
from ggcore.plot import aes, geom_point, ggplot, labs
from ggio.frame import to_column_table

DATA = {"x": [1.0, 2.0, 3.0, 4.0], "y": [2.0, 1.5, 4.2, 3.1]}

p = (
    ggplot(to_column_table(DATA), aes(x="x * 100", y="y"))
    + geom_point(aes(size="y if y > 3 else 1"), colour="#4C78A8")
    + labs(title="expressions inside aes()", x="x × 100", y="y")
)
```

白名单里的东西：

| 类别 | 写法 |
| --- | --- |
| 算术 | `+ - * / // % **`、逐元素 `&` / `\|` |
| 比较 | `< <= > >= == !=`（可链式：`18 <= x < 27`） |
| 逻辑 / 条件 | `and` / `or`、`a if cond else b` |
| 函数 | `log log10 log2 sqrt exp abs round floor ceil where isnan`（裸名与 `np.` 前缀等价）；`min` / `max` |
| 取列 | `col("列名")`：列名带空格 / 标点时唯一的入口 |

字符串常量要包一层引号，因为外层字符串本身就是表达式：

```python
from ggcore.plot import aes, geom_point, ggplot, labs
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [3, 1, 2]}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y", colour="'red'"))
    + geom_point(size=3)
    + labs(title="a string constant inside aes()")
)
```

安全边界：表达式不过 `eval()`，而是解析成 `AesSpec` 后用白名单解释器求值。
`__import__("os")`、`open(...)`、属性访问（`x.__class__`）一律 `AesWhitelistError`。

## 3. 列名不是合法标识符：`col()`

```python
from ggcore.plot import aes, geom_point, ggplot, labs
from ggio.frame import to_column_table

DATA = {"my x": [1.0, 2.0, 3.0], "response value": [3.0, 1.0, 2.0]}

p = (
    ggplot(to_column_table(DATA), aes(x='col("my x")', y='col("response value")'))
    + geom_point(size=3)
    + labs(title='col("…") for awkward column names', x="my x", y="response value")
)
```

空格的列名不能直接写进表达式；`col()` 只收一个字符串字面量。撞上 Python 关键字
的列名（`class`、`lambda`）不需要 `col()`：整串是标识符时按列名处理。

## 4. `after_stat()`：映射统计结果

stat 算完之后才有 `count` / `density` / `n` 这类列，用 `after_stat()` 取：

```python
from ggcore.plot import aes, after_stat, geom_bar, ggplot, labs
from ggio.frame import to_column_table

DATA = {"class": ["compact", "compact", "suv", "suv", "suv", "midsize"]}

p = (
    ggplot(to_column_table(DATA), aes(x="class"))
    + geom_bar(aes(y=after_stat("count")), fill="#4C78A8")
    + labs(title="after_stat('count')", x="class", y="count")
)
```

`..count..` / `..density..` 是 ggplot2 3.x 的旧写法，4.0 起用 `after_stat()`；
gg4py 只实现了后者。哪些列可用由 stat 决定（见 [`stat.md`](stat.md)），写错会在
构图期报「没有这一列」。

## 5. 分组

离散美学（`colour` / `fill` / `linetype` / `shape`）会自动分组；需要把多行连成
一条线、又不想给颜色时，显式写 `group`：

```python
from ggcore.plot import aes, geom_line, geom_point, ggplot, labs
from ggio.frame import to_column_table

DATA = {
    "x": [1, 2, 3, 1, 2, 3],
    "y": [1.0, 2.5, 4.0, 3.0, 2.0, 1.0],
    "panel": ["a", "a", "a", "b", "b", "b"],
}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y", group="panel"))
    + geom_line(colour="#4C78A8", linewidth=1.2)
    + geom_point(size=2.5)
    + labs(title="group = panel", subtitle="two lines, no legend")
)
```

多个离散列组合分组用 `+` 拼接（`aes(group="a + b")`）；`interaction()` 不在白名单。

## 6. 图层级映射与继承

`ggplot()` 上的映射被所有图层继承；图层自己给的映射逐键覆盖它。`inherit_aes=False`
时该图层**完全不继承**，必须自带 `x` / `y`：

```python
from ggcore.plot import aes, geom_line, geom_point, ggplot, labs
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3, 4], "y": [1.0, 2.5, 2.0, 4.0], "g": ["a", "a", "b", "b"]}
OTHER = {"x": [1.0, 4.0], "y": [3.5, 3.5]}

data = to_column_table(DATA)
p = (
    ggplot(data, aes(x="x", y="y"))
    + geom_line(aes(colour="g"))  # 继承 x / y，加颜色
    + geom_point(size=2.5)  # 只继承 plot 级映射
    + geom_point(  # 自带数据 + 映射
        aes(x="x", y="y"), data=to_column_table(OTHER), colour="#E45756", size=3
    )
    + labs(title="layer-level mapping, data and inherit_aes")
)
```

要点：

- 图层映射里没给的美学从 `ggplot()` 的映射继承，给了的覆盖；
- `data=` 换掉这一层的数据（同样要先转 `ColumnTable`）；
- `inherit_aes=False` 是「彻底不继承」，常用于 `annotate()` 与自定义图层。
